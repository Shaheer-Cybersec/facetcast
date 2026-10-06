"""
import_posts - load posts you already published (before Facetcast) into memory.

Why: the angle agent dedups new ideas against every post in memory. Posts you wrote by
hand are not there unless you import them. Optional; also makes the writer match YOUR
voice on top of the voice it reads from the README.

Put them in memory/voice/my_posts.md (gitignored) like this:

    ## Post: linkedin
    the full text of one post
    ---
    ## Post: x
    another post
    ---

  python -m memory.import_posts            import
  python -m memory.import_posts --dry-run  show what would be imported
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from config.settings import VOICE_DIR
from core.platforms import ALL_PLATFORMS
from memory import db
from memory import embeddings as E

PROJECT_ID = "manual/imported"
SECTION_RE = re.compile(r"^## Post[: ]*([^\n]*)\n(.*?)(?=^---\s*$|^## Post|\Z)", re.M | re.S)


def voice_files() -> list[Path]:
    return sorted(p for p in VOICE_DIR.glob("*.md") if p.name.lower() != "readme.md")


def parse_posts(text: str) -> list[tuple[str, str]]:
    out = []
    for m in SECTION_RE.finditer(text):
        body = m.group(2).strip()
        plat = (m.group(1) or "").strip().lower().replace("twitter", "x")
        if body:
            out.append((plat if plat in ALL_PLATFORMS else "linkedin", body))
    return out


def import_posts(path: Path | None = None, dry_run: bool = False) -> dict:
    files = [path] if path else voice_files()
    posts = [p for f in files if f.exists() for p in parse_posts(f.read_text(encoding="utf-8"))]
    db.init()
    added = skipped = embedded = 0
    with db.connect() as conn:
        existing = {r["text"] for r in conn.execute("SELECT text FROM posts")}
        if not dry_run and posts:
            db.upsert_project(conn, PROJECT_ID, "manual", None, datetime.now(timezone.utc).isoformat())
        for platform, text in posts:
            if text in existing:
                skipped += 1
                continue
            added += 1
            if dry_run:
                continue
            vec = E.embed(text)
            embedded += vec is not None
            db.insert_post(conn, PROJECT_ID, None, None, platform, text, E.to_blob(vec) if vec is not None else None)
    return {"found": len(posts), "added": added, "skipped": skipped, "embedded": embedded, "dry_run": dry_run}


if __name__ == "__main__":
    r = import_posts(dry_run="--dry-run" in sys.argv)
    print(f"found {r['found']} post(s): added {r['added']}, already there {r['skipped']}, "
          f"embedded {r['embedded']}" + ("  (dry run, nothing written)" if r["dry_run"] else ""))
