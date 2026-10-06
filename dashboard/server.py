"""
Facetcast dashboard - local web UI over the orchestrator.

    python facetcast.py serve            then open http://127.0.0.1:8765

Standard library only. Listens on 127.0.0.1 only: nothing on your network can reach it.

Security model (it is a local app that can read folders and hold API keys):
  - binds to 127.0.0.1, and rejects any request whose Host header is not 127.0.0.1/localhost
    (stops DNS-rebinding attacks from a malicious web page)
  - every state-changing request must carry the header "X-Facetcast: 1" and, when the
    browser sends one, a same-origin Origin header (stops cross-site request forgery:
    other sites cannot add custom headers without a CORS preflight, which is refused)
  - files are only served from the static folder and from a run's own kit folder,
    with path traversal checks
  - API keys are written to .env and only ever returned masked

Long steps (ingest, LLM calls, packaging) run in a background thread; the page polls
/api/runs/<id>. Progress lives in state.json on disk, so the CLI and the dashboard see
the same runs.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import struct
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse

from config import settings
from core import engines as E
from core import orchestrator as O
from core import platforms as P
from core.base_agent import AgentError
from core.graphics import THEMES
from core.report import STAGES, final_platforms
from memory import db

STATIC = Path(__file__).with_name("static")
MAX_UPLOAD = 300 * 1024 * 1024
MAX_FOLDER_FILES = 20_000
PRODUCES = {"A01": "repo", "A02": "memory", "A03": "analysis", "A04": "profile", "A05": "angle_set",
            "A06": "strategy", "A07": "visual_plan", "A08": "draft", "A09": "critique", "A10": "final_draft",
            "A11": "showcase", "A12": "package", "A13": "memory_write"}
STAGE_NAME = {t: n for t, n, _, _ in STAGES}

_busy: set[str] = set()
_errors: dict[str, str] = {}
_lock = threading.Lock()
PORT = settings.DASHBOARD_PORT


# ---------------- background work ----------------

def _in_background(run_id: str, fn, *args) -> None:
    with _lock:
        if run_id in _busy:
            raise AgentError(f"run '{run_id}' is already working, wait for it")
        _busy.add(run_id)
        _errors.pop(run_id, None)

    def work():
        try:
            fn(*args)
        except AgentError as e:
            _errors[run_id] = str(e)
        except Exception as e:                     # a bug: show it, keep the server alive
            _errors[run_id] = f"{type(e).__name__}: {e}"
        finally:
            with _lock:
                _busy.discard(run_id)

    threading.Thread(target=work, daemon=True).start()


def start(source: str, platforms=None) -> str:
    source = (source or "").strip()
    if not source:
        raise AgentError("give a GitHub URL, a zip, or a folder path")
    run_id = O.new_run_id(source)
    _in_background(run_id, O.start, source, run_id, platforms or None)
    return run_id


def demo() -> str:
    run_id = O.new_run_id("demo-night-shift")
    _in_background(run_id, O.demo, run_id)
    return run_id


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", Path(name).name)[:80] or "upload"


def save_zip(name: str, data: bytes) -> Path:
    if not name.lower().endswith(".zip"):
        raise AgentError("only .zip files here (or drop the folder itself)")
    if len(data) > MAX_UPLOAD:
        raise AgentError("upload is over 300 MB")
    p = settings.UPLOADS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{_safe_name(name)}"
    p.write_bytes(data)
    return p


def save_folder(name: str, body: bytes) -> Path:
    """Body = repeated [4-byte length][JSON header {"p": path, "n": size}][n bytes]."""
    root = settings.UPLOADS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{_safe_name(name)}"
    i, count = 0, 0
    root.mkdir(parents=True)
    while i < len(body):
        if i + 4 > len(body):
            raise AgentError("folder upload is truncated")
        (hl,) = struct.unpack(">I", body[i:i + 4])
        i += 4
        try:
            head = json.loads(body[i:i + hl].decode("utf-8"))
        except ValueError:
            raise AgentError("folder upload header is not valid")
        i += hl
        n = int(head.get("n", 0))
        rel = str(head.get("p", "")).replace("\\", "/")
        parts = PurePosixPath(rel).parts
        if not rel or rel.startswith("/") or ".." in parts or (parts and ":" in parts[0]) or n < 0:
            raise AgentError(f"unsafe path in folder upload: {rel}")
        dest = (root / rel).resolve()
        if root.resolve() not in dest.parents:
            raise AgentError(f"unsafe path in folder upload: {rel}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body[i:i + n])
        i += n
        count += 1
        if count > MAX_FOLDER_FILES:
            raise AgentError("folder has too many files")
    if count == 0:
        raise AgentError("the folder was empty")
    entries = [p for p in root.iterdir()]
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else root


def pending_stage(st: dict) -> tuple[str, str] | None:
    if st["status"] not in ("waiting", "failed") or st["pos"] >= len(O.PLAN):
        return None
    tag = O.PLAN[st["pos"]]
    return (tag, STAGE_NAME[tag]) if tag.startswith("A") else None


def get_prompt(run_id: str) -> dict:
    st = O.load(run_id)
    p = pending_stage(st)
    if not p:
        raise AgentError("no stage is waiting for an answer")
    f = settings.RUNS_DIR / run_id / f"{p[1]}.prompt.md"
    if not f.exists():
        raise AgentError(f"{f.name} not found")
    return {"stage": p[0], "name": p[1], "text": f.read_text(encoding="utf-8")}


def submit_response(run_id: str, text: str) -> None:
    st = O.load(run_id)
    p = pending_stage(st)
    if not p:
        raise AgentError("no stage is waiting for an answer")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        raise AgentError(f"that is not valid JSON: {e}")
    (settings.RUNS_DIR / run_id / f"{p[1]}.response.json").write_text(text, encoding="utf-8")
    _in_background(run_id, O.resume, run_id)


def kit_folder(run_id: str) -> Path:
    st = O.load(run_id)
    pkg = st["ctx"].get("package")
    if not pkg:
        raise AgentError("this run has no kit yet")
    return Path(pkg["folder"])


def kit_file(run_id: str, rel: str) -> tuple[bytes, str]:
    root = kit_folder(run_id).resolve()
    target = (root / rel).resolve()
    if root != target and root not in target.parents:
        raise AgentError("not in this kit")
    if not target.is_file():
        raise AgentError("file not found")
    return target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream"


def open_folder(run_id: str) -> str:
    folder = kit_folder(run_id)
    if sys.platform == "win32":
        os.startfile(str(folder))                       # noqa: S606 - our own kit folder
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
    return str(folder)


# ---------------- views ----------------

def _trim_repo(r: dict) -> dict:
    return {k: r.get(k) for k in ("source_type", "host", "owner", "repo", "url", "head_sha", "source_ref_kind",
                                  "file_count", "tree_truncated", "languages", "cache_hit", "kind_hint",
                                  "readme_path", "images")} | {
        "commits": (r.get("commits") or [])[:8],
        "key_files": [{"path": p, "chars": len(t or "")} for p, t in (r.get("key_files") or {}).items()],
        "tree": [f["path"] for f in (r.get("tree") or [])[:500]],
        "readme": (r.get("readme") or "")[:4000]}


def stage_view(st: dict, busy: bool) -> list[dict]:
    out = []
    for i, (tag, name, title, who) in enumerate(STAGES):
        rec = st["records"].get(tag)
        status = rec["status"] if rec else "pending"
        if tag in ("G1", "G2"):
            status = "gate" if st["gate"] == tag else ("done" if st["pos"] > i else "pending")
        elif i == st["pos"] and busy:
            status = "running"
        if st["status"] == "rejected" and i >= st["pos"] and status == "pending":
            status = "cancelled"
        out.append({"tag": tag, "name": name, "title": title, "who": who, "status": status,
                    "ms": rec["duration_ms"] if rec else None,
                    "error": rec["error"] if rec and rec["status"] in ("failed", "skipped") else None})
    return out


def live_view(st: dict, busy: bool) -> dict | None:
    if st["pos"] >= len(O.PLAN) or not O.PLAN[st["pos"]].startswith("A"):
        return None
    tag = O.PLAN[st["pos"]]
    f = settings.RUNS_DIR / st["run_id"] / f"{STAGE_NAME[tag]}.live.txt"
    text = f.read_text(encoding="utf-8", errors="replace") if f.exists() else ""
    if not busy and not text:
        return None
    return {"tag": tag, "name": STAGE_NAME[tag], "since": st["updated"], "chars": len(text), "text": text[-3000:]}


def events(st: dict) -> list[dict]:
    ev = [{"at": r.get("at", ""), "tag": tag, "kind": "stage", "status": r["status"], "ms": r["duration_ms"],
           "error": r["error"]} for tag, r in st["records"].items()]
    f = settings.RUNS_DIR / st["run_id"] / "llm_log.jsonl"
    if f.exists():
        tags = {n: t for t, n, _, _ in STAGES}
        for line in f.read_text(encoding="utf-8").splitlines()[-80:]:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev.append({"at": e.get("at", ""), "tag": tags.get(e.get("stage"), e.get("stage")), "kind": "llm",
                       "backend": e.get("backend"), "model": e.get("model"), "ms": e.get("duration_ms"),
                       "ok": e.get("ok"), "repaired": e.get("repaired"), "error": e.get("error"),
                       "waiting": e.get("waiting")})
    return sorted(ev, key=lambda e: e["at"] or "")[-100:]


def kit_view(st: dict) -> dict | None:
    ctx = st["ctx"]
    pkg = ctx.get("package")
    if not pkg:
        return None
    from core.report import collect, kits
    m = collect(ctx, st["records"])
    folder = Path(pkg["folder"])
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) if folder.exists() else []
    return {"folder": str(folder), "files": files, "platforms": pkg.get("platforms") or m["platforms"],
            "theme": pkg.get("theme") or m["theme"], "warnings": pkg.get("warnings") or [],
            "kits": kits(m), "drafts": final_platforms(ctx), "showcase": ctx.get("showcase"),
            "stats": pkg.get("stats") or {}, "claims": m["claims"], "edited": ctx.get("edited") or [],
            "brand": m["brand"], "has_pdf": (folder / "00_REPORT.pdf").exists()}


def run_detail(run_id: str) -> dict:
    st = O.load(run_id)
    busy = run_id in _busy
    ctx = st["ctx"]
    outputs = {}
    for tag, key in PRODUCES.items():
        if key in ctx:
            outputs[tag] = _trim_repo(ctx[key]) if key == "repo" else ctx[key]
    if "chosen_angle" in ctx:
        outputs["G1"] = {"angle": ctx["chosen_angle"], "platforms": ctx.get("platforms")}
    return {"summary": O.summary(st), "source": st["source"], "busy": busy, "live": live_view(st, busy),
            "events": events(st), "error": _errors.get(run_id), "created": st["created"], "updated": st["updated"],
            "stages": stage_view(st, busy), "outputs": outputs, "pending": pending_stage(st),
            "kit": kit_view(st), "project": (ctx.get("repo") or {}).get("repo")}


def list_runs() -> list[dict]:
    rows = O.list_runs()
    for r in rows:
        r["busy"] = r["run_id"] in _busy
    for rid in list(_busy):
        if not any(r["run_id"] == rid for r in rows):
            rows.insert(0, {"run_id": rid, "status": "running", "gate": None, "source": "", "updated": "9999",
                            "project": None, "platforms": [], "busy": True})
    return rows


def meta() -> dict:
    return {"app": settings.APP_NAME, "version": settings.VERSION, "themes": list(THEMES),
            "platforms": [{"id": p, "label": P.label(p), "kind": P.SPECS[p]["kind"]} for p in P.ALL_PLATFORMS],
            "stages": [{"tag": t, "name": n, "title": ti, "who": w} for t, n, ti, w in STAGES],
            "author": {"name": settings.AUTHOR_NAME, "handle": settings.AUTHOR_HANDLE}}


# ---------------- engines ----------------

def engines_view() -> dict:
    return E.status()


def engines_action(action: str, body: dict) -> dict:
    try:
        if action == "key":
            text = body.get("key") or ""
            engine = body.get("engine")
            if engine:
                key = text.strip()
            else:
                key, engine = E.extract_key(text)
                if not engine:
                    raise E.EngineError("couldn't recognise that key. Pick the provider below and paste it there.")
            E.save_key(engine, key)
            result = {"engine": engine, "masked": E.mask(key)}
            try:
                result["test"] = E.test(engine)
            except E.EngineError as e:
                result["test"] = {"ok": False, "message": str(e), "models": []}
            E.configure(engine, make_active=bool(body.get("activate", True)))
            return {**engines_view(), "saved": result}
        if action == "use":
            E.configure(body.get("engine", ""), body.get("heavy"), body.get("mid"), body.get("base_url"))
            return engines_view()
        if action == "test":
            return {**engines_view(), "test": {"engine": body.get("engine"), **E.test(body.get("engine", ""))}}
        if action == "forget":
            E.forget_key(body.get("engine", ""))
            return engines_view()
    except E.EngineError as e:
        raise AgentError(str(e))
    raise AgentError("unknown engines action")


# ---------------- HTTP ----------------

class Handler(BaseHTTPRequestHandler):
    server_version = "Facetcast/1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body, ctype="application/json", extra: dict | None = None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "text" in ctype or "json" in ctype or "javascript" in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _allowed_host(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        return host in {f"127.0.0.1:{PORT}", f"localhost:{PORT}", "127.0.0.1", "localhost"}

    def _csrf_ok(self) -> bool:
        if self.headers.get("X-Facetcast") != "1":
            return False
        origin = self.headers.get("Origin")
        return not origin or origin.lower() in {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            raise AgentError("request too large")
        return self.rfile.read(n) if n else b""

    def _json(self) -> dict:
        b = self._body()
        try:
            return json.loads(b) if b else {}
        except ValueError:
            raise AgentError("request body is not JSON")

    def _static(self, rel: str):
        base = STATIC if not rel.startswith("fonts/") else settings.FONTS_DIR.parent
        target = (base / rel).resolve()
        if base.resolve() not in target.parents or not target.is_file():
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            ctype = "text/javascript"
        return self._send(200, target.read_bytes(), ctype, {"Cache-Control": "no-cache"})

    def _route(self, method: str):
        if not self._allowed_host():
            return self._send(403, {"error": "forbidden host"})
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = parse_qs(u.query)
        try:
            if method == "GET" and not parts:
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html",
                                  {"Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; "
                                                              "style-src 'self' 'unsafe-inline'; script-src 'self'; "
                                                              "font-src 'self'; connect-src 'self'; frame-ancestors 'none'"})
            if method == "GET" and parts[0] == "static":
                return self._static("/".join(parts[1:]))
            if method == "GET" and parts[0] == "fonts":
                return self._static("fonts/" + "/".join(parts[1:]))
            if parts[:1] != ["api"]:
                return self._send(404, {"error": "not found"})
            if method == "POST" and not self._csrf_ok():
                return self._send(403, {"error": "missing X-Facetcast header or cross-site request"})
            p = parts[1:]
            if method == "GET":
                if p == ["runs"]:
                    return self._send(200, list_runs())
                if p == ["memory"]:
                    return self._send(200, db.overview())
                if p == ["engines"]:
                    return self._send(200, engines_view())
                if p == ["meta"]:
                    return self._send(200, meta())
                if len(p) == 2 and p[0] == "runs":
                    return self._send(200, run_detail(O.check_id(p[1])))
                if len(p) == 3 and p[0] == "runs" and p[2] == "prompt":
                    return self._send(200, get_prompt(O.check_id(p[1])))
                if len(p) >= 4 and p[0] == "runs" and p[2] == "kit":
                    data, ctype = kit_file(O.check_id(p[1]), "/".join(p[3:]))
                    return self._send(200, data, ctype, {"Cache-Control": "no-cache"})
            if method == "POST":
                if p == ["runs"]:
                    b = self._json()
                    return self._send(202, {"run_id": start(b.get("source", ""), b.get("platforms"))})
                if p == ["demo"]:
                    return self._send(202, {"run_id": demo()})
                if p == ["upload"]:
                    name = (q.get("name") or ["upload.zip"])[0]
                    zp = save_zip(name, self._body())
                    return self._send(202, {"run_id": start(str(zp), (q.get("platforms") or [None])[0])})
                if p == ["upload-folder"]:
                    name = (q.get("name") or ["project"])[0]
                    folder = save_folder(name, self._body())
                    return self._send(202, {"run_id": start(str(folder), (q.get("platforms") or [None])[0])})
                if len(p) == 2 and p[0] == "engines":
                    return self._send(200, engines_action(p[1], self._json()))
                if len(p) == 3 and p[0] == "runs":
                    rid, act = O.check_id(p[1]), p[2]
                    b = self._json()
                    if act == "pick":
                        _in_background(rid, O.pick, rid, int(b.get("n", 0)), b.get("platforms"))
                    elif act == "approve":
                        _in_background(rid, O.approve, rid)
                    elif act == "reject":
                        O.reject(rid, b.get("reason", "") or "rejected in the dashboard")
                    elif act == "resume":
                        _in_background(rid, O.resume, rid)
                    elif act == "response":
                        submit_response(rid, b.get("text", ""))
                    elif act == "theme":
                        _in_background(rid, O.rebuild, rid, b.get("theme"))
                    elif act == "edit":
                        _in_background(rid, O.edit, rid, b.get("platform", ""), b.get("data") or {})
                    elif act == "open":
                        return self._send(200, {"folder": open_folder(rid)})
                    else:
                        return self._send(404, {"error": "unknown action"})
                    return self._send(202, {"ok": True})
            return self._send(404, {"error": "not found"})
        except AgentError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")


def serve(port: int = settings.DASHBOARD_PORT) -> ThreadingHTTPServer:
    global PORT
    PORT = port
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(port: int = settings.DASHBOARD_PORT, open_browser: bool = True) -> int:
    try:
        httpd = serve(port)
    except OSError as e:
        print(f"could not start on port {port}: {e}. Try: python facetcast.py serve --port {port + 1}")
        return 1
    st = E.status()
    url = f"http://127.0.0.1:{port}"
    print(f"{settings.APP_NAME} {settings.VERSION}   engine: {st['active']}")
    print(f"dashboard: {url}   (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Facetcast dashboard")
    ap.add_argument("--port", type=int, default=settings.DASHBOARD_PORT)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    sys.exit(main(a.port, not a.no_browser))
