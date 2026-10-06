"""Engines: paste-a-key detection, the .env writer, and real HTTP against fake providers."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from pydantic import BaseModel

from core import engines as E
from core import llm


class Out(BaseModel):
    answer: str


class Fake(BaseHTTPRequestHandler):
    calls: list = []
    replies: list = []

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        Fake.calls.append(("GET", self.path, dict(self.headers)))
        if "bad" in (self.headers.get("Authorization", "") + self.headers.get("x-api-key", "")):
            return self._send({"error": {"message": "invalid key"}}, 401)
        self._send({"data": [{"id": "model-a"}, {"id": "model-b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.calls.append(("POST", self.path, body))
        text = Fake.replies.pop(0)
        if self.path.endswith("/messages"):
            return self._send({"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"})
        self._send({"choices": [{"message": {"content": text}}]})


@pytest.fixture
def fake(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/v1"
    monkeypatch.setitem(E.ENGINES["openai"], "base", base)
    monkeypatch.setitem(E.ENGINES["anthropic"], "base", base)
    Fake.calls.clear()
    Fake.replies.clear()
    yield base
    srv.shutdown()


def test_detect_and_extract_keys():
    assert E.detect("sk-ant-api03-xyz") == "anthropic"
    assert E.detect("sk-or-v1-abc") == "openrouter"
    assert E.detect("sk-proj-abc") == "openai"
    assert E.detect("gsk_abc") == "groq"
    assert E.detect("AIzaSyAbc") == "gemini"
    assert E.detect("hello") is None
    key, prov = E.extract_key("# my env\nOPENROUTER_API_KEY=sk-or-v1-0123456789abcdef\nOTHER=1")
    assert prov == "openrouter" and key == "sk-or-v1-0123456789abcdef"
    assert E.mask("sk-ant-api03-0123456789") == "sk-ant…6789"


def test_save_key_writes_env_and_never_twice(env_file):
    E.save_key("groq", "gsk_firstkey12345")
    E.save_key("groq", "gsk_secondkey6789")
    text = env_file.read_text()
    assert text.count("GROQ_API_KEY=") == 1 and "gsk_secondkey6789" in text
    with pytest.raises(E.EngineError):
        E.save_key("groq", "bad key\nINJECT=1")
    with pytest.raises(E.EngineError):
        E.save_key("claude", "whatever-key-123")


def test_status_never_leaks_a_full_key(env_file, real_engine):
    E.save_key("openai", "sk-proj-SECRETSECRETSECRET1234")
    blob = json.dumps(E.status(), ensure_ascii=False)
    assert "SECRETSECRET" not in blob and "sk-pro…1234" in blob


def test_openai_compatible_test_and_call_with_repair(env_file, real_engine, fake, tmp_path):
    E.save_key("openai", "sk-proj-goodkey12345678")
    r = E.test("openai")
    assert r["ok"] and r["models"] == ["model-a", "model-b"]
    E.configure("openai", "model-a", "model-a")
    Fake.replies[:] = ["not json at all", '{"answer": "fixed"}']      # first answer fails, repair turn fixes it
    out = llm.call("stage1", "heavy", "sys", "user", Out, run_id="eng-oa")
    assert out == {"answer": "fixed"}
    posts = [c for c in Fake.calls if c[0] == "POST"]
    assert len(posts) == 2 and posts[0][2]["model"] == "model-a" and "rejected" in posts[1][2]["messages"][1]["content"]
    # resume never pays twice: the saved answer is reused
    assert llm.call("stage1", "heavy", "sys", "user", Out, run_id="eng-oa") == {"answer": "fixed"}
    assert len([c for c in Fake.calls if c[0] == "POST"]) == 2


def test_anthropic_protocol_and_bad_key(env_file, real_engine, fake):
    E.save_key("anthropic", "sk-ant-goodkey1234567")
    E.configure("anthropic", "claude-x", "claude-x")
    Fake.replies[:] = ['```json\n{"answer": "hi"}\n```']
    assert llm.call("stage2", "mid", "sys", "user", Out, run_id="eng-an") == {"answer": "hi"}
    post = [c for c in Fake.calls if c[0] == "POST"][0]
    assert post[1].endswith("/messages") and post[2]["system"] and post[2]["model"] == "claude-x"
    E.save_key("anthropic", "sk-ant-badkey1234567")
    with pytest.raises(E.EngineError, match="rejected"):
        E.test("anthropic")


def test_manual_engine_writes_a_prompt_and_waits(real_engine):
    from core.base_agent import HandoffPending
    E.configure("claude")
    with pytest.raises(HandoffPending):
        llm.call("stage3", "mid", "sys", "user", Out, run_id="eng-manual")
    p, r = llm.handoff_paths("eng-manual", "stage3")
    assert p.exists() and "JSON Schema" in p.read_text()
    r.write_text('{"answer": "pasted"}')
    assert llm.call("stage3", "mid", "sys", "user", Out, run_id="eng-manual") == {"answer": "pasted"}
