"""
common - small helpers several agents share (prompt pieces, voice, evidence lists).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from config.settings import VOICE_DIR
from core import platforms as P

USER_VOICE_CHARS = 8_000
FENCE_RE = re.compile(r"^```[a-z]*\s*$", re.M)
HEADING_RE = re.compile(r"^#{1,6}\s+", re.M)       # '# Title' (space after #), not '#hashtag'
BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.S)


def prompt(agent_file: str) -> str:
    return Path(agent_file).with_name("prompt.md").read_text(encoding="utf-8")


def user_voice() -> str:
    """Optional: the user's own past posts (memory/voice/*.md). They refine the README voice."""
    parts = []
    for p in sorted(VOICE_DIR.glob("*.md")):
        if p.name.lower() != "readme.md":
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n\n".join(parts)[:USER_VOICE_CHARS]


def voice_block(profile: dict | None) -> str:
    """The voice profile, formatted for writing agents."""
    if not profile:
        return "(no voice profile: write plainly, first person, concrete)"
    v = profile.get("voice") or {}
    lines = [
        f"person: {v.get('person')}   formality: {v.get('formality')}/5   energy: {v.get('energy')}/5   "
        f"humor: {v.get('humor')}   emoji: {v.get('emoji')}",
        f"tone: {', '.join(v.get('tone') or [])}",
        f"sentences: {v.get('sentence_style')}",
        f"vocabulary: {v.get('vocabulary')}",
    ]
    if v.get("signature_phrases"):
        lines.append("phrases the author really uses: " + " | ".join(v["signature_phrases"]))
    if v.get("do"):
        lines.append("do: " + "; ".join(v["do"]))
    if v.get("avoid"):
        lines.append("avoid: " + "; ".join(v["avoid"]))
    lines.append(f"positioning: {profile.get('positioning', '')}")
    if profile.get("user_voice_used"):
        lines.append("(also calibrated on the author's own past posts)")
    return "\n".join(lines)


def evidence_lines(items: list[dict]) -> list[str]:
    return [f"- {e['claim']}  [{e['source_path']} @ {e['source_ref']}]" for e in items]


def allowed_refs(repo: dict) -> list[str]:
    refs = [c["sha"][:12] for c in repo.get("commits", [])]
    return refs or [repo["head_sha"][:12]]


def strip_markdown(text: str) -> str:
    text = FENCE_RE.sub("", text or "")
    text = HEADING_RE.sub("", text)
    text = BOLD_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def project_label(repo: dict) -> str:
    return repo.get("repo") if repo.get("owner") in ("local", "remote", None) else f"{repo['owner']}/{repo['repo']}"


def compact(obj, n: int = 1) -> str:
    return json.dumps(obj, indent=n, ensure_ascii=False)


def platform_rules(platforms: list[str]) -> str:
    out = []
    for p in platforms:
        s = P.SPECS[p]
        out.append(f"- {p} ({s['label']}): " + " ".join(s["tips"]))
    return "\n".join(out)
