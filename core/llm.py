"""
llm - one call() for every LLM agent, whatever engine is active.

    result = llm.call(stage="analyzer", tier="heavy", system=..., user=...,
                      schema=AnalysisOut, mock={...}, run_id=ctx["run_id"])

Engines (core/engines.py picks the active one):
  claude      MANUAL. The stage writes data/runs/<run_id>/<stage>.prompt.md and pauses
              the run (HandoffPending). You paste the prompt into Claude, paste the JSON
              answer back (dashboard) or save it as <stage>.response.json; resume.
  claude_cli  Claude Code on this machine ("claude -p"), logged in with your Claude plan.
              Answer streamed live to <stage>.live.txt. Tools are disabled for these calls
              and they run in an empty temp folder, so Claude only answers.
  API engines anthropic / openai / openrouter / groq / gemini / ollama / lmstudio / custom.
  mock        returns the agent's own mock dict. Free, instant, used by every test.

Every engine's output is validated against the same Pydantic schema, so an agent never
sees malformed data. Invalid JSON gets exactly one repair turn (the model sees its own
answer and the validation errors), then the stage fails with a readable reason.
Every answer is saved as <stage>.response.json, so resuming a run never pays twice.
Every call is logged to data/runs/<run_id>/llm_log.jsonl.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from config.settings import APP_NAME, ROOT, RUNS_DIR
from core import engines as E
from core.base_agent import AgentError, HandoffPending

TIERS = ("heavy", "mid")
SYSTEM_PREAMBLE = ("You are one stage of a content pipeline. Follow the instructions exactly and "
                   "reply with a single JSON object and nothing else.")


class LLMError(AgentError):
    """An LLM call could not produce valid output. Message says why."""


# ---------- routing ----------

def backend_for(stage: str) -> str:
    if E.active() == "mock":                        # tests: mock always wins
        return "mock"
    over = (E.load_models().get("stages") or {}).get(stage)
    return over if over in E.ENGINES else E.active()


# ---------- validation ----------

def _parse(raw: str | dict, schema: type[BaseModel]) -> dict:
    """JSON text or dict -> validated plain dict. Raises LLMError with readable reasons."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as e:
        raise LLMError(f"not valid JSON: {e.msg} at line {e.lineno} col {e.colno}")
    try:
        return schema.model_validate(data).model_dump()
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or '(root)'}: {err['msg']}"
                             for err in e.errors()[:8])
        raise LLMError(f"does not match schema: {problems}")


def extract_json(text: str) -> str:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            t = t[i:j + 1]
    return t


def _log(run_id: str, entry: dict) -> None:
    d = RUNS_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "llm_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def handoff_paths(run_id: str, stage: str) -> tuple[Path, Path]:
    d = RUNS_DIR / run_id
    return d / f"{stage}.prompt.md", d / f"{stage}.response.json"


def _rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def _schema_text(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(), indent=1)


def full_prompt(system: str, user: str, schema: type[BaseModel]) -> str:
    return (f"## System\n\n{system}\n\n## Task\n\n{user}\n\n"
            f"## Output\n\nReply with ONLY one JSON object that validates against this JSON "
            f"Schema. No prose before or after it, no code fences.\n\n{_schema_text(schema)}\n")


def _saved(stage: str, schema: type[BaseModel], run_id: str) -> dict | None:
    _, response_path = handoff_paths(run_id, stage)
    if not response_path.exists():
        return None
    try:
        return _parse(extract_json(response_path.read_text(encoding="utf-8")), schema)
    except LLMError as e:
        raise LLMError(f"{response_path.name} {e}. Fix or delete the file and resume.")


# ---------- engines ----------

def _mock(stage: str, schema: type[BaseModel], mock: Any) -> tuple[dict, dict]:
    if mock is None:
        raise LLMError(f"{stage}: no mock output provided for mock mode")
    return _parse(mock, schema), {}


def _handoff(stage: str, system: str, user: str, schema: type[BaseModel], run_id: str) -> tuple[dict, dict]:
    prompt_path, response_path = handoff_paths(run_id, stage)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(
        f"# {APP_NAME} stage: {stage} (run `{run_id}`)\n\n"
        "Answer this ONE stage only. Do not run any tool or pipeline to do it: just follow the\n"
        "System and Task sections and produce the JSON result.\n"
        "- In a chat: reply with ONLY the JSON object.\n"
        f"- With file access to this project: save ONLY the JSON to `{_rel(response_path)}`.\n\n"
        + full_prompt(system, user, schema), encoding="utf-8")
    raise HandoffPending(f"waiting for a manual answer: prompt at {_rel(prompt_path)}, "
                         f"save the answer as {response_path.name}")


NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0     # no console pop-ups on Windows


def _run_claude(prompt: str, model: str, timeout: int, live: Path) -> str:
    exe = E.claude_bin()
    if not exe:
        raise LLMError("Claude Code CLI not found. Install it (npm install -g @anthropic-ai/claude-code), "
                       "run `claude` once to log in, then retry. Or pick another engine.")
    cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
           "--tools", "", "--model", model, "--no-session-persistence", "--strict-mcp-config",
           "--system-prompt", SYSTEM_PREAMBLE]
    killed = threading.Event()
    with tempfile.TemporaryDirectory(prefix="fc_cli_", ignore_cleanup_errors=True) as cwd, \
            tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=err, text=True, encoding="utf-8", errors="replace",
                                creationflags=NO_WINDOW)
        timer = threading.Timer(timeout, lambda: (killed.set(), proc.kill()))
        timer.start()
        result = None
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
            with open(live, "a", encoding="utf-8") as out:
                for line in proc.stdout:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("type") == "stream_event":
                        delta = (ev.get("event") or {}).get("delta") or {}
                        piece = delta.get("text") or delta.get("thinking")
                        if piece:
                            out.write(piece)
                            out.flush()
                    elif ev.get("type") == "result":
                        result = ev
            proc.wait()
        finally:
            timer.cancel()
        err.seek(0)
        stderr = err.read()[-400:]
    if killed.is_set():
        raise LLMError(f"Claude Code took longer than {timeout}s (limits.claude_cli_timeout_s in config/models.yaml)")
    if result is None:
        raise LLMError(f"Claude Code exited ({proc.returncode}) without an answer. "
                       f"If it is not logged in, run `claude` once in a terminal. {stderr.strip()}")
    if result.get("is_error"):
        raise LLMError(f"Claude Code error: {str(result.get('result') or result.get('subtype'))[:300]}")
    return result.get("result") or ""


def _ask_with_repair(stage: str, ask, prompt: str, schema: type[BaseModel], live: Path) -> tuple[dict, bool]:
    raw = ask(prompt)
    try:
        return _parse(extract_json(raw), schema), False
    except LLMError as first:
        with open(live, "a", encoding="utf-8") as out:
            out.write(f"\n\n--- answer rejected ({first}); asking for a fix ---\n\n")
        fix = (f"{prompt}\n\n## Your previous answer was rejected\n\n{first}\n\n"
               f"Previous answer:\n{raw[:20000]}\n\nReturn the corrected JSON object only.")
        try:
            return _parse(extract_json(ask(fix)), schema), True
        except LLMError as second:
            raise LLMError(f"{stage}: invalid output after 1 repair turn: {second}")


def _live(run_id: str, stage: str, prompt: str) -> Path:
    prompt_path, _ = handoff_paths(run_id, stage)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    live = prompt_path.with_name(f"{stage}.live.txt")
    live.write_text("", encoding="utf-8")
    return live


def _claude_cli(stage: str, tier: str, system: str, user: str, schema, run_id: str) -> tuple[dict, dict]:
    model = E.model_for("claude_cli", tier) or "sonnet"
    timeout = int(E.limits()["claude_cli_timeout_s"])
    prompt = full_prompt(system, user, schema)
    live = _live(run_id, stage, prompt)
    result, repaired = _ask_with_repair(stage, lambda p: _run_claude(p, model, timeout, live), prompt, schema, live)
    return result, {"model": model, "repaired": repaired}


def _api(engine: str, stage: str, tier: str, system: str, user: str, schema, run_id: str) -> tuple[dict, dict]:
    model = E.model_for(engine, tier)
    prompt = full_prompt(system, user, schema)
    live = _live(run_id, stage, prompt)

    def ask(p: str) -> str:
        try:
            text = E.complete(engine, model, SYSTEM_PREAMBLE, p)
        except E.EngineError as e:
            raise LLMError(f"{E.ENGINES[engine]['label']}: {e}")
        with open(live, "a", encoding="utf-8") as out:
            out.write(text)
        return text

    result, repaired = _ask_with_repair(stage, ask, prompt, schema, live)
    return result, {"model": model, "repaired": repaired}


# ---------- public entry point ----------

def call(stage: str, tier: str, system: str, user: str, schema: type[BaseModel],
         mock: Any = None, run_id: str = "adhoc") -> dict:
    if tier not in TIERS:
        raise LLMError(f"unknown tier {tier!r}; use one of {TIERS}")
    backend = backend_for(stage)
    t0 = time.perf_counter()
    entry = {"stage": stage, "tier": tier, "backend": backend,
             "prompt_chars": len(system) + len(user), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        saved = _saved(stage, schema, run_id)               # resume / demo: never pay for an answer twice
        if saved is not None:
            result, meta = saved, {"response_file": f"{stage}.response.json"}
            entry["backend"] = "saved"
        elif backend == "mock":
            result, meta = _mock(stage, schema, mock)
        else:
            if backend == "claude":
                result, meta = _handoff(stage, system, user, schema, run_id)
            elif backend == "claude_cli":
                result, meta = _claude_cli(stage, tier, system, user, schema, run_id)
            elif backend in E.API_ENGINES:
                result, meta = _api(backend, stage, tier, system, user, schema, run_id)
            else:
                raise LLMError(f"unknown engine {backend!r}")
            _, response_path = handoff_paths(run_id, stage)
            if not response_path.exists():
                response_path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
        entry.update(meta, ok=True, response_chars=len(json.dumps(result)))
        return result
    except HandoffPending:
        entry.update(ok=None, waiting=True)
        raise
    except LLMError as e:
        entry.update(ok=False, error=str(e)[:300])
        raise
    finally:
        entry["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        _log(run_id, entry)
