"""Ingest: every kind of source, and the zip hardening."""
import io
import zipfile

import pytest

from agents.ingest.agent import Ingest, classify, safe_extract
from core.base_agent import AgentError


def test_classify_sources(tmp_path, example):
    assert classify("https://github.com/a/b")["kind"] == "git"
    assert classify("https://github.com/a/b/tree/main/docs")["repo"] == "b"
    assert classify("https://gitlab.com/a/b.git")["host"] == "gitlab.com"
    assert classify("https://github.com/a/b/archive/refs/heads/main.zip")["kind"] == "zip_url"
    assert classify(example)["kind"] == "dir"
    z = tmp_path / "p.zip"
    z.write_bytes(b"x")
    assert classify(str(z))["kind"] == "zip_file"
    for bad in ("", "http://github.com/a/b", "https://example.com/page", str(tmp_path / "missing")):
        with pytest.raises(AgentError):
            classify(bad)


def test_local_folder_reads_readme_first(example):
    ctx = {"source": example}
    rec = Ingest().execute(ctx)
    assert rec["status"] == "success", rec
    r = ctx["repo"]
    assert r["readme_path"] == "README.md" and "Night Shift" in r["readme"]
    assert r["source_ref_kind"] == "content-hash" and len(r["head_sha"]) == 40
    assert "chapters/01-method.md" in r["key_files"] and r["owner"] == "local"


def test_local_folder_skips_junk(tmp_path):
    (tmp_path / "README.md").write_text("# Hi\nA tool.")
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "i.js").write_text("junk")
    (tmp_path / "main.py").write_text("print(1)")
    ctx = {"source": str(tmp_path)}
    assert Ingest().execute(ctx)["status"] == "success"
    paths = [f["path"] for f in ctx["repo"]["tree"]]
    assert "main.py" in paths and not any("node_modules" in p for p in paths)


def _zip(entries: dict, comment: bytes = b"") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
        z.comment = comment
    return buf.getvalue()


def test_zip_with_github_comment_uses_commit_sha(tmp_path):
    sha = "a" * 40
    p = tmp_path / "proj-main.zip"
    p.write_bytes(_zip({"proj-main/README.md": "# Proj\nHello", "proj-main/a.py": "x=1"}, sha.encode()))
    ctx = {"source": str(p)}
    assert Ingest().execute(ctx)["status"] == "success"
    assert ctx["repo"]["head_sha"] == sha and ctx["repo"]["repo"] == "proj"


def test_zip_slip_is_refused(tmp_path):
    p = tmp_path / "evil.zip"
    p.write_bytes(_zip({"../../evil.txt": "pwned"}))
    with pytest.raises(AgentError, match="unsafe path"):
        safe_extract(p, tmp_path / "out")
    assert not (tmp_path.parent / "evil.txt").exists()
