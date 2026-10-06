"""
[A13] archive - static agent (no LLM). Runs last, only after you approve (G2).

Input : ctx["repo"], ctx["run_id"], ctx["approved"] (the platform texts you approved),
        ctx["chosen_angle"], ctx["angle_set"]
Output: ctx["memory_write"]  {post_ids{platform: id}, angles_used, angles_queued, angles_dropped,
                              embedded, note}

In ONE database transaction (all or nothing):
  1. upsert the project, mark the run done
  2. store the chosen angle as 'used', the rest as 'queued' (dedup-rejected ones as 'dropped')
  3. store each platform's text as a post, with its embedding (NULL when embeddings are off)
Then writes a read-only markdown note (data/notes/, Obsidian-friendly).
Future runs dedup new angles against everything stored here.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from config.settings import NOTES_DIR, ROOT
from core import platforms as P
from core.base_agent import AgentError, BaseAgent
from memory import db
from memory import embeddings as E


def _slug(text: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:n] or "post"


def note(repo: dict, run_id: str, angle: dict | None, approved: dict, ids: dict) -> str:
    lines = ["---", f"project: {repo['owner']}/{repo['repo']}", f"ref: {repo['head_sha'][:12]}", f"run: {run_id}",
             f"platforms: {', '.join(approved)}", f"written: {datetime.now().isoformat(timespec='seconds')}", "---", "",
             f"# {(angle or {}).get('title') or 'GitHub & portfolio kit'}", ""]
    for p, text in approved.items():
        lines += [f"## {P.label(p)} (post {ids.get(p)})", "", text.strip(), ""]
    return "\n".join(lines) + "\n"


class Archive(BaseAgent):
    agent_id = "A13"
    name = "archive"
    title = "Remember it"
    requires = ("repo", "run_id", "approved")
    produces = "memory_write"
    uses_llm = False

    def run(self, ctx: dict) -> dict:
        repo, run_id, approved = ctx["repo"], ctx["run_id"], ctx["approved"]
        if not isinstance(approved, dict):
            raise AgentError("approved must be {platform: text}")
        pid = f"{repo['owner']}/{repo['repo']}"
        chosen = ctx.get("chosen_angle")
        angles = (ctx.get("angle_set") or {}).get("angles") or []
        saved_ctx = {k: v for k, v in ctx.items() if k not in ("memory_write", "_records")}
        vecs = {p: E.embed(t) for p, t in approved.items()}
        db.init()
        used = queued = dropped = 0
        ids = {}
        with db.connect() as conn:
            db.upsert_project(conn, pid, repo.get("url") or "", repo.get("head_sha"), repo.get("ingested_at"))
            db.finish_run(conn, run_id, pid, ",".join(ctx.get("platforms") or approved), json.dumps(saved_ctx))
            angle_id = None
            if chosen:
                angle_id = db.insert_angle(conn, pid, run_id, chosen.get("title", ""), chosen.get("summary"),
                                           chosen.get("score"), chosen.get("dedup_status"), "used")
                used = 1
            for a in angles:
                if chosen and a.get("title") == chosen.get("title"):
                    continue
                status = "dropped" if a.get("dedup_status") == "rejected" else "queued"
                db.insert_angle(conn, pid, run_id, a.get("title", ""), a.get("summary"), a.get("score"),
                                a.get("dedup_status"), status)
                queued += status == "queued"
                dropped += status == "dropped"
            for p, text in approved.items():
                v = vecs[p]
                ids[p] = db.insert_post(conn, pid, run_id, angle_id, p, text, E.to_blob(v) if v is not None else None)
        name = f"{datetime.now():%Y-%m-%d}-{_slug(repo['repo'], 30)}-{_slug((chosen or {}).get('title', 'kit'))}.md"
        path = NOTES_DIR / name
        path.write_text(note(repo, run_id, chosen, approved, ids), encoding="utf-8")
        try:
            rel = path.relative_to(ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()
        return {"post_ids": ids, "angles_used": used, "angles_queued": queued, "angles_dropped": dropped,
                "embedded": all(v is not None for v in vecs.values()) and bool(vecs), "note": rel}
