"""
engines - where the LLM stages run, and the paste-a-key setup behind the dashboard.

No-key engines (the defaults):
  claude_cli  Claude Code on this machine ("claude -p"), logged in with your Claude plan.
  claude      Manual: Facetcast writes each prompt, you paste Claude's JSON answer back.

API engines (optional; paste a key in the dashboard's Engines panel or run
`python facetcast.py engine key <paste>` and the provider is detected from the key):
  anthropic   Claude API                 ANTHROPIC_API_KEY
  openai      OpenAI                     OPENAI_API_KEY
  openrouter  OpenRouter (any model)     OPENROUTER_API_KEY
  groq        Groq                       GROQ_API_KEY
  gemini      Google Gemini              GEMINI_API_KEY
  ollama      Ollama on this machine     (no key)
  lmstudio    LM Studio on this machine  (no key)
  custom      any OpenAI-compatible URL  FACETCAST_CUSTOM_API_KEY + FACETCAST_CUSTOM_BASE_URL
Test-only:
  mock        canned outputs, validated against the same schemas

Keys live in .env (gitignored). The dashboard only ever sees them masked.
Which engine is active is saved in data/engine.json; FACETCAST_ENGINE overrides it.
Standard library only: no SDKs to install.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from config import settings

MODELS_FILE = settings.ROOT / "config" / "models.yaml"

ENGINES: dict[str, dict] = {
    "claude_cli": {"label": "Claude Code (this PC)", "kind": "local", "protocol": "claude_cli",
                   "blurb": "Runs every stage through the Claude Code CLI with your Claude plan. No API key.",
                   "docs": "https://docs.claude.com/en/docs/claude-code/overview"},
    "claude": {"label": "Manual copy-paste", "kind": "manual", "protocol": "handoff",
               "blurb": "You paste each prompt into any Claude chat and paste the JSON answer back. No key, no install."},
    "anthropic": {"label": "Claude API (Anthropic)", "kind": "api", "protocol": "anthropic",
                  "key_env": "ANTHROPIC_API_KEY", "base": "https://api.anthropic.com/v1",
                  "prefixes": ("sk-ant-",), "docs": "https://console.anthropic.com/settings/keys"},
    "openai": {"label": "OpenAI", "kind": "api", "protocol": "openai",
               "key_env": "OPENAI_API_KEY", "base": "https://api.openai.com/v1",
               "prefixes": ("sk-proj-", "sk-svcacct-", "sk-"), "docs": "https://platform.openai.com/api-keys"},
    "openrouter": {"label": "OpenRouter", "kind": "api", "protocol": "openai",
                   "key_env": "OPENROUTER_API_KEY", "base": "https://openrouter.ai/api/v1",
                   "prefixes": ("sk-or-",), "docs": "https://openrouter.ai/keys"},
    "groq": {"label": "Groq", "kind": "api", "protocol": "openai",
             "key_env": "GROQ_API_KEY", "base": "https://api.groq.com/openai/v1",
             "prefixes": ("gsk_",), "docs": "https://console.groq.com/keys"},
    "gemini": {"label": "Google Gemini", "kind": "api", "protocol": "openai",
               "key_env": "GEMINI_API_KEY", "base": "https://generativelanguage.googleapis.com/v1beta/openai",
               "prefixes": ("AIza",), "docs": "https://aistudio.google.com/apikey"},
    "ollama": {"label": "Ollama (local)", "kind": "local-api", "protocol": "openai",
               "base_fn": lambda: f"{settings.OLLAMA_HOST}/v1", "docs": "https://ollama.com/download"},
    "lmstudio": {"label": "LM Studio (local)", "kind": "local-api", "protocol": "openai",
                 "base_fn": lambda: f"{settings.LMSTUDIO_HOST}/v1", "docs": "https://lmstudio.ai"},
    "custom": {"label": "Custom (OpenAI-compatible)", "kind": "api", "protocol": "openai",
               "key_env": "FACETCAST_CUSTOM_API_KEY", "base_env": "FACETCAST_CUSTOM_BASE_URL",
               "blurb": "Any endpoint that speaks the OpenAI chat-completions API (Together, Mistral, DeepSeek, vLLM...)."},
    "mock": {"label": "Mock (tests)", "kind": "test", "protocol": "mock"},
}
API_ENGINES = tuple(n for n, e in ENGINES.items() if e["protocol"] in ("anthropic", "openai"))
KEY_RE = re.compile(r"^[A-Za-z0-9_\-.:+/=]{8,400}$")
URL_OK = re.compile(r"^https?://[A-Za-z0-9.\-:\[\]]+(/[A-Za-z0-9._~\-/]*)?$")


class EngineError(Exception):
    pass


# ---------------------------------------------------------------- config files

def load_models() -> dict:
    try:
        return yaml.safe_load(MODELS_FILE.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def _engine_file() -> dict:
    try:
        return json.loads(settings.ENGINE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_engine_file(data: dict) -> None:
    settings.ENGINE_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def claude_bin() -> str | None:
    """Full path of the Claude Code CLI, or None if it is not installed."""
    found = shutil.which(settings.CLAUDE_BIN)
    return found or (settings.CLAUDE_BIN if Path(settings.CLAUDE_BIN).is_file() else None)


def active() -> str:
    """The engine LLM stages use. Env var > saved choice > Claude Code if installed > manual."""
    env = os.getenv("FACETCAST_ENGINE", "").strip().lower()
    if env in ENGINES:
        return env
    saved = _engine_file().get("engine")
    if saved in ENGINES:
        return saved
    return "claude_cli" if claude_bin() else "claude"


def locked() -> bool:
    """FACETCAST_ENGINE in the environment wins over the dashboard."""
    return os.getenv("FACETCAST_ENGINE", "").strip().lower() in ENGINES


def model_for(engine: str, tier: str) -> str:
    saved = (_engine_file().get("models") or {}).get(engine) or {}
    if saved.get(tier):
        return saved[tier]
    if engine == "custom" and os.getenv("FACETCAST_CUSTOM_MODEL"):
        return os.environ["FACETCAST_CUSTOM_MODEL"]
    return ((load_models().get("tiers") or {}).get(tier) or {}).get(engine, "") or ""


def limits() -> dict:
    d = {"claude_cli_timeout_s": 900, "api_timeout_s": 300, "api_retries": 3,
         "max_output_tokens": 12000, "temperature": 0.4}
    d.update(load_models().get("limits") or {})
    return d


def base_url(engine: str) -> str:
    e = ENGINES[engine]
    if e.get("base_env"):
        return (os.getenv(e["base_env"]) or _engine_file().get("custom_base_url") or "").rstrip("/")
    if e.get("base_fn"):
        return e["base_fn"]()
    return e.get("base", "")


def api_key(engine: str) -> str:
    env = ENGINES[engine].get("key_env")
    return (os.getenv(env) or "").strip() if env else ""


def mask(key: str) -> str:
    if not key:
        return ""
    return key[:6] + "…" + key[-4:] if len(key) > 14 else "…" + key[-3:]


def detect(key: str) -> str | None:
    """Which provider a pasted key belongs to, from its prefix."""
    k = (key or "").strip()
    for name in ("anthropic", "openrouter", "groq", "gemini", "openai"):   # specific prefixes first
        if any(k.startswith(p) for p in ENGINES[name].get("prefixes", ())):
            return name
    return None


def extract_key(text: str) -> tuple[str | None, str | None]:
    """Find the first API key in pasted or dropped text (a raw key, a .env line, JSON...)."""
    for token in re.findall(r"[A-Za-z0-9_\-.:+/=]{16,400}", text or ""):
        token = token.strip("'\"=")
        if "=" in token:
            token = token.split("=", 1)[1]
        prov = detect(token)
        if prov:
            return token, prov
    return None, None


# ---------------------------------------------------------------- .env writer

def _upsert_env(values: dict[str, str]) -> None:
    lines = settings.ENV_FILE.read_text(encoding="utf-8").splitlines() if settings.ENV_FILE.exists() else []
    done = set()
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip()
        if k in values:
            lines[i] = f"{k}={values[k]}"
            done.add(k)
    if not lines:
        lines = ["# Facetcast local settings. Never commit this file."]
    lines += [f"{k}={v}" for k, v in values.items() if k not in done]
    settings.ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k, v in values.items():
        os.environ[k] = v


def save_key(engine: str, key: str) -> None:
    if engine not in ENGINES or not ENGINES[engine].get("key_env"):
        raise EngineError(f"{engine} does not use an API key")
    key = (key or "").strip()
    if not KEY_RE.match(key):
        raise EngineError("that does not look like an API key")
    _upsert_env({ENGINES[engine]["key_env"]: key})


def forget_key(engine: str) -> None:
    env = ENGINES.get(engine, {}).get("key_env")
    if env:
        _upsert_env({env: ""})


def configure(engine: str, model_heavy: str | None = None, model_mid: str | None = None,
              custom_base_url: str | None = None, make_active: bool = True) -> None:
    if engine not in ENGINES:
        raise EngineError(f"unknown engine {engine!r}. Use one of: {', '.join(ENGINES)}")
    data = _engine_file()
    if make_active:
        data["engine"] = engine
    models = data.setdefault("models", {})
    if model_heavy is not None or model_mid is not None:
        m = models.setdefault(engine, {})
        for tier, val in (("heavy", model_heavy), ("mid", model_mid)):
            if val is not None:
                val = val.strip()
                if val and not re.match(r"^[A-Za-z0-9_.:/@\-]{1,120}$", val):
                    raise EngineError(f"bad model name: {val!r}")
                m[tier] = val
    if custom_base_url is not None:
        u = custom_base_url.strip().rstrip("/")
        if u and not URL_OK.match(u):
            raise EngineError("custom base URL must look like https://host/v1")
        data["custom_base_url"] = u
        _upsert_env({"FACETCAST_CUSTOM_BASE_URL": u})
    _write_engine_file(data)


def ready(engine: str) -> tuple[bool, str]:
    """Can this engine run right now? (ok, reason)"""
    e = ENGINES[engine]
    if engine == "claude_cli":
        return (True, "Claude Code found") if claude_bin() else (False, "Claude Code CLI not installed")
    if e["kind"] in ("manual", "test"):
        return True, "always available"
    if e.get("key_env") and not api_key(engine):
        return False, "no API key yet"
    if engine == "custom" and not base_url(engine):
        return False, "no base URL yet"
    if not model_for(engine, "heavy"):
        return False, "no model chosen"
    return True, "key saved" if e.get("key_env") else "local server (start it before running)"


def status() -> dict:
    cur = active()
    rows = []
    for name, e in ENGINES.items():
        if name == "mock" and cur != "mock":
            continue
        ok, why = ready(name)
        rows.append({"name": name, "label": e["label"], "kind": e["kind"], "blurb": e.get("blurb", ""),
                     "docs": e.get("docs", ""), "needs_key": bool(e.get("key_env")),
                     "key": mask(api_key(name)) if e.get("key_env") else "",
                     "base_url": base_url(name) if e["protocol"] == "openai" or name == "anthropic" else "",
                     "models": {"heavy": model_for(name, "heavy"), "mid": model_for(name, "mid")},
                     "ready": ok, "why": why, "active": name == cur})
    return {"active": cur, "locked": locked(), "engines": rows,
            "claude_cli": {"path": claude_bin()}}


# ---------------------------------------------------------------- HTTP

def _http(url: str, payload: dict | None, headers: dict, timeout: int, retries: int = 1) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if payload is not None else "GET",
                                 headers={"Content-Type": "application/json", "User-Agent": "facetcast/1",
                                          **headers})
    last = None
    for attempt in range(max(1, retries)):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            if e.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                last = f"HTTP {e.code}: {body}"
                continue
            hint = {401: "the API key was rejected", 403: "the key has no access to this",
                    404: "wrong URL or model name", 429: "rate limited / out of credit"}.get(e.code, "")
            raise EngineError(f"HTTP {e.code}{' (' + hint + ')' if hint else ''}: {_short(body)}")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = f"{type(e).__name__}: {e}"
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
    raise EngineError(f"could not reach {url.split('/v1')[0]} ({last})")


def _short(body: str) -> str:
    try:
        j = json.loads(body)
        err = j.get("error")
        return (err.get("message") if isinstance(err, dict) else str(err or j))[:240]
    except ValueError:
        return body[:240]


def _headers(engine: str, key: str | None = None) -> dict:
    key = key if key is not None else api_key(engine)
    if ENGINES[engine]["protocol"] == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    h = {"Authorization": f"Bearer {key or 'local'}"}
    if engine == "openrouter":
        h.update({"HTTP-Referer": "https://github.com/facetcast", "X-Title": "Facetcast"})
    return h


def test(engine: str, key: str | None = None) -> dict:
    """Check the engine answers. API engines: list the models the key can use."""
    if engine not in ENGINES:
        raise EngineError(f"unknown engine {engine!r}")
    e = ENGINES[engine]
    if engine == "claude_cli":
        path = claude_bin()
        return {"ok": bool(path), "models": ["opus", "sonnet", "haiku"],
                "message": f"Claude Code at {path}" if path else "Claude Code CLI not found. Install it, run `claude` once to log in."}
    if e["kind"] in ("manual", "test"):
        return {"ok": True, "models": [], "message": "nothing to test"}
    base = base_url(engine)
    if not base:
        raise EngineError("set the base URL first")
    if e.get("key_env") and not (key or api_key(engine)):
        raise EngineError("paste a key first")
    j = _http(f"{base}/models", None, _headers(engine, key), timeout=25)
    ids = sorted({m.get("id") or m.get("name") for m in (j.get("data") or j.get("models") or [])
                  if isinstance(m, dict)} - {None})
    return {"ok": True, "models": ids[:400], "message": f"connected, {len(ids)} model(s) available"}


def complete(engine: str, model: str, system: str, user: str, timeout: int | None = None) -> str:
    """One chat turn on an API engine. Returns the model's text."""
    lim = limits()
    timeout = timeout or int(lim["api_timeout_s"])
    if not model:
        raise EngineError(f"no model set for {engine}. Pick one in the Engines panel.")
    base = base_url(engine)
    if ENGINES[engine]["protocol"] == "anthropic":
        j = _http(f"{base}/messages", {"model": model, "max_tokens": int(lim["max_output_tokens"]),
                                       "temperature": lim["temperature"], "system": system,
                                       "messages": [{"role": "user", "content": user}]},
                  _headers(engine), timeout, int(lim["api_retries"]))
        if j.get("stop_reason") == "max_tokens":
            raise EngineError("answer was cut off (max_output_tokens in config/models.yaml)")
        return "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
    payload = {"model": model, "temperature": lim["temperature"],
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
               "response_format": {"type": "json_object"}}
    try:
        j = _http(f"{base}/chat/completions", payload, _headers(engine), timeout, int(lim["api_retries"]))
    except EngineError as e:
        if "HTTP 400" not in str(e):
            raise
        payload.pop("response_format")              # some servers do not support JSON mode
        j = _http(f"{base}/chat/completions", payload, _headers(engine), timeout, int(lim["api_retries"]))
    try:
        return j["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise EngineError(f"unexpected response shape: {str(j)[:200]}")
