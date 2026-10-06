"""
[A02] recall - static agent (no LLM). What has already been published?

Input : ctx["repo"]
Output: ctx["memory"]   {project_id, past_posts[], past_post_count, queued_angles[], embedded_post_ids[]}

  - past_posts: recent posts from ALL projects and platforms, so the angle agent never
    repeats an idea you already published about another project.
  - queued_angles: unused angles from earlier runs of THIS project, so a second run can
    go straight to a fresh one.
Embedding bytes never enter the context (the angle agent loads vectors itself).
A brand-new database is not an error: first run -> empty lists.
"""
from __future__ import annotations

from core.base_agent import BaseAgent
from memory import db

RECENT_LIMIT = 60


def project_id(repo: dict) -> str:
    return f"{repo['owner']}/{repo['repo']}"


class Recall(BaseAgent):
    agent_id = "A02"
    name = "recall"
    title = "Check what you already posted"
    requires = ("repo",)
    produces = "memory"
    uses_llm = False

    def run(self, ctx: dict) -> dict:
        pid = project_id(ctx["repo"])
        db.init()
        with db.connect() as conn:
            posts = db.recent_posts(conn, RECENT_LIMIT)
            queued = db.queued_angles(conn, pid)
        return {"project_id": pid, "past_posts": posts, "past_post_count": len(posts),
                "queued_angles": queued,
                "embedded_post_ids": [p["id"] for p in posts if p["has_embedding"]]}
