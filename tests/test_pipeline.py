"""The whole pipeline, end to end, on the mock engine and on the bundled demo answers."""
import json
from pathlib import Path

import pytest

from core import orchestrator as O
from core.base_agent import AgentError
from memory import db

ALL = ["linkedin", "x", "instagram", "tiktok", "github"]


def statuses(st):
    return {k: r["status"] for k, r in st["records"].items()}


def test_mock_run_reaches_g1_then_g2_then_done(example):
    st = O.start(example, "p-mock")
    assert st["gate"] == "G1", st
    s = O.summary(st)
    assert len(s["angles"]) >= 3 and all(a["default_platforms"] for a in s["angles"])
    st = O.pick("p-mock", 1, ALL)
    assert st["gate"] == "G2", statuses(st)
    folder = Path(st["ctx"]["package"]["folder"])
    for f in ("00_REPORT.pdf", "00_START_HERE.md", "index.html", "linkedin/post.md", "linkedin/graphic.png",
              "x/thread.md", "x/card.png", "instagram/caption.md", "instagram/slide-01.png", "tiktok/script.md",
              "tiktok/cover.png", "github/README.suggested.md", "github/social-preview.png", "evidence.md",
              "voice-profile.md", "manifest.json"):
        assert (folder / f).exists(), f
    st = O.approve("p-mock")
    assert st["status"] == "done"
    assert set(st["ctx"]["memory_write"]["post_ids"]) == set(ALL)
    with db.connect() as c:
        assert c.execute("SELECT count(*) FROM posts WHERE run_id='p-mock'").fetchone()[0] == 5
        assert c.execute("SELECT count(*) FROM angles WHERE run_id='p-mock' AND status='queued'").fetchone()[0] >= 2


def test_only_picked_platforms_are_written(example):
    O.start(example, "p-two")
    st = O.pick("p-two", 2, "x,tiktok")
    pkg = st["ctx"]["package"]
    assert pkg["platforms"] == ["x", "tiktok"]
    assert statuses(st)["A11"] == "skipped"                     # no github -> no showcase
    assert not (Path(pkg["folder"]) / "linkedin").exists()


def test_github_only_skips_content_stages(example):
    O.start(example, "p-gh")
    st = O.pick("p-gh", 1, ["github"])
    s = statuses(st)
    assert s["A06"] == s["A07"] == s["A08"] == s["A09"] == s["A10"] == "skipped"
    assert s["A11"] == "success" and st["gate"] == "G2"


def test_demo_uses_saved_answers_and_grounds_everything():
    st = O.demo("p-demo")
    assert st["gate"] == "G1"
    st = O.pick("p-demo", 1, ALL)
    assert st["gate"] == "G2", statuses(st)
    ctx = st["ctx"]
    assert ctx["profile"]["voice"]["signature_phrases"]               # phrases found verbatim in the README
    assert ctx["critique"]["verdict"] == "revise"
    assert "loudest street in town" not in json.dumps(ctx["final_draft"]["platforms"])   # block flag was fixed
    assert ctx["package"]["evidence_checked"] >= 5


def test_rebuild_in_another_theme_and_edit_at_g2(example):
    O.start(example, "p-edit")
    O.pick("p-edit", 1, ["linkedin", "x"])
    st = O.rebuild("p-edit", "paper")
    assert st["ctx"]["package"]["theme"] == "paper"
    new = {"tweets": ["My own first tweet", "And a second one"]}
    st = O.edit("p-edit", "x", new)
    assert st["gate"] == "G2" and st["ctx"]["edited"] == ["x"]
    assert (Path(st["ctx"]["package"]["folder"]) / "x" / "thread.md").read_text().startswith("My own first tweet")
    with pytest.raises(AgentError):
        O.edit("p-edit", "x", {"tweets": []})                   # schema still enforced
    with pytest.raises(AgentError):
        O.rebuild("p-edit", "neon")


def test_packager_refuses_an_over_long_tweet(example):
    O.start(example, "p-long")
    O.pick("p-long", 1, ["x"])
    st = O.edit("p-long", "x", {"tweets": ["x" * 300]})
    assert st["status"] == "failed" and "tweet 1" in st["records"]["A12"]["error"]


def test_reject_and_gates_are_enforced(example):
    st = O.start(example, "p-rej")
    with pytest.raises(AgentError):
        O.approve("p-rej")                                      # not at G2
    with pytest.raises(AgentError):
        O.pick("p-rej", 99)
    st = O.reject("p-rej", "not now")
    assert st["status"] == "rejected"
    with pytest.raises(AgentError):
        O.reject("p-rej")
    with pytest.raises(AgentError):
        O.load("../etc")
