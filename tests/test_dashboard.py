"""Dashboard HTTP API, including its security checks."""
import json
import struct
import threading
import time
import urllib.error
import urllib.request

import pytest

from dashboard import server


@pytest.fixture(scope="module")
def base():
    httpd = server.serve(0)
    server.PORT = httpd.server_port
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def call(base, path, body=None, headers=None, raw=None):
    h = {"X-Facetcast": "1", "Content-Type": "application/json", **(headers or {})}
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait(base, rid, cond, secs=40):
    for _ in range(secs * 5):
        code, b = call(base, f"/api/runs/{rid}")
        if code == 200:
            d = json.loads(b)
            if not d["busy"] and cond(d):
                return d
        time.sleep(0.2)
    raise AssertionError(f"run {rid} never reached the state")


def test_static_and_meta(base):
    code, b = call(base, "/")
    assert code == 200 and b"Facetcast" in b
    code, b = call(base, "/static/app.js")
    assert code == 200
    assert json.loads(call(base, "/api/meta")[1])["platforms"][0]["id"] == "linkedin"
    assert call(base, "/static/../config/settings.py")[0] == 404


def test_csrf_and_host_checks(base):
    assert call(base, "/api/demo", {}, headers={"X-Facetcast": ""})[0] == 403
    assert call(base, "/api/demo", {}, headers={"Origin": "https://evil.example"})[0] == 403
    assert call(base, "/api/runs", headers={"Host": "evil.example"})[0] == 403


def test_demo_flow_through_the_api(base):
    code, b = call(base, "/api/demo", {})
    rid = json.loads(b)["run_id"]
    d = wait(base, rid, lambda d: d["summary"]["gate"] == "G1")
    assert d["outputs"]["A04"]["voice"]["tone"]
    call(base, f"/api/runs/{rid}/pick", {"n": 1, "platforms": ["linkedin", "instagram"]})
    d = wait(base, rid, lambda d: d["summary"]["gate"] == "G2")
    assert d["kit"]["platforms"] == ["linkedin", "instagram"]
    code, png = call(base, f"/api/runs/{rid}/kit/instagram/slide-01.png")
    assert code == 200 and png[:4] == b"\x89PNG"
    assert call(base, f"/api/runs/{rid}/kit/../../state.json")[0] in (400, 404)
    call(base, f"/api/runs/{rid}/approve", {})
    d = wait(base, rid, lambda d: d["summary"]["status"] == "done")
    assert d["summary"]["memory_write"]["post_ids"]


def frame(path, data):
    head = json.dumps({"p": path, "n": len(data)}).encode()
    return struct.pack(">I", len(head)) + head + data


def test_folder_upload_and_traversal(base):
    body = frame("proj/README.md", b"# Proj\nA small tool that counts words.") + frame("proj/main.py", b"print(1)")
    code, b = call(base, "/api/upload-folder?name=proj", raw=body)
    assert code == 202, b
    rid = json.loads(b)["run_id"]
    d = wait(base, rid, lambda d: d["summary"]["gate"] == "G1")
    assert d["outputs"]["A01"]["readme_path"] == "README.md"
    code, b = call(base, "/api/upload-folder?name=evil", raw=frame("../escape.txt", b"x"))
    assert code == 400 and b"unsafe" in b


def test_engines_api_masks_keys(base, env_file):
    code, b = call(base, "/api/engines/key", {"key": "OPENAI_API_KEY=sk-proj-abcdefghijklmnop1234"})
    assert code == 200, b
    blob = b.decode()
    assert "abcdefghijklmnop" not in blob and '"engine": "openai"' in blob
    code, b = call(base, "/api/engines/key", {"key": "hello there"})
    assert code == 400
