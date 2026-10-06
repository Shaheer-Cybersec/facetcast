"""
[A05] angles - LLM agent (heavy tier). Finds 5-8 distinct angles and where each one lands.

Input : ctx["analysis"], ctx["profile"], ctx["memory"], ctx["repo"], ctx["run_id"]
Output: ctx["angle_set"]  {
            "angles": [ {title, summary, hook, post_type, audience, score, platform_fit{},
                         best_platforms[], evidence[], why,
                         dedup_status: ok|unchecked|rejected, max_similarity, reject_reason} ],
            "counts": {ok, unchecked, rejected, dropped}, "dropped": [...],
            "recommendation": {title, reason, platforms[], source}
        }
        Ranked ok (by score) -> unchecked -> rejected. You pick one at G1.

Static steps after the model answers:
  1. Evidence re-check. Angles with no valid evidence are dropped.
  2. Dedup against everything you published before (embeddings, threshold in settings).
     Embeddings unavailable -> "unchecked" (fail-closed, never a fake score).
  3. Dedup inside the batch: two angles that say the same thing -> lower score rejected.
  4. platform_fit normalised; best_platforms re-derived from it when the model left it empty.
  5. Fewer than 3 usable angles -> the stage fails.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from agents.common import compact, prompt, voice_block
from config.settings import DEDUP_THRESHOLD
from core import llm
from core import platforms as P
from core.base_agent import AgentError, BaseAgent
from core.evidence import validate
from core.schemas import Evidence
from memory import db
from memory import embeddings as E

MIN_USABLE = 3
FINDING_SECTIONS = ("components", "decisions", "highlights", "limitations")
POST_TYPES = ("lesson", "breakdown", "story", "how-to", "opinion", "showcase", "behind-the-scenes",
              "result", "myth-vs-fact", "tutorial")


class Angle(BaseModel):
    title: str = Field(min_length=8, max_length=120)
    summary: str = Field(min_length=20, description="what the content delivers, 1-2 sentences")
    hook: str = Field(min_length=8, max_length=170, description="possible first line")
    post_type: Literal[POST_TYPES]
    audience: str = Field(min_length=3)
    score: float = Field(ge=0, le=1, description="honest confidence this angle lands (0-1)")
    platform_fit: dict[str, float] = Field(default_factory=dict,
                                           description="0-1 per content platform: linkedin, x, instagram, tiktok")
    best_platforms: list[str] = Field(default_factory=list, max_length=4)
    evidence: list[Evidence] = Field(min_length=1)
    why: Optional[str] = Field(default=None, description="1 sentence: why this angle suits this author and project")


class AnglesOut(BaseModel):
    angles: list[Angle] = Field(min_length=5, max_length=8)
    recommended: Optional[str] = Field(default=None, description="exact title of the angle you would pick")
    recommendation_reason: Optional[str] = Field(default=None)


def build_user_prompt(repo: dict, analysis: dict, profile: dict, memory: dict) -> str:
    comp = {k: analysis.get(k) for k in ("summary", "purpose", "project_kind", "field", *FINDING_SECTIONS)}
    past = memory.get("past_posts", [])
    queued = memory.get("queued_angles", [])
    fit = {p: (profile.get("platform_fit") or {}).get(p, {}).get("score") for p in P.CONTENT_PLATFORMS}
    return "\n".join([
        f"PROJECT: {repo['owner']}/{repo['repo']}",
        "",
        "AUTHOR VOICE:", voice_block(profile),
        "",
        "AUDIENCES:", *[f"- {a['name']}: {a['cares_about']}" for a in profile.get("audiences", [])],
        "",
        f"PROJECT-LEVEL PLATFORM FIT (profiler): {compact(fit, None)}",
        "",
        "ANALYSIS (grounded; reuse its evidence items exactly):",
        compact(comp),
        "",
        "ALREADY PUBLISHED (do not repeat these ideas):",
        *([f"- [{p.get('platform')}] {p.get('angle_title') or ''}: {p['text'][:180]}" for p in past[:20]] or ["- (nothing yet)"]),
        "",
        "QUEUED ANGLES for this project (already saved, do not repeat):",
        *([f"- {a['title']}" for a in queued] or ["- (none)"]),
        "",
        "Return 5-8 distinct angles as JSON matching the schema.",
    ])


def mock_output(analysis: dict) -> dict:
    findings = [f for s in FINDING_SECTIONS for f in analysis.get(s, [])]
    types = ["lesson", "story", "how-to", "showcase", "behind-the-scenes", "result"]
    plats = list(P.CONTENT_PLATFORMS)
    angles = []
    for i, f in enumerate((findings * 6)[:6]):
        fit = {p: round(0.9 - ((i + j) % 4) * 0.15, 2) for j, p in enumerate(plats)}
        angles.append({
            "title": f"Mock angle {i + 1}: {f['title']}"[:120],
            "summary": f"Mock: content built around '{f['title']}'.",
            "hook": f"Mock hook {i + 1} about {f['title']}"[:170],
            "post_type": types[i % len(types)], "audience": "curious peers",
            "score": round(0.9 - i * 0.08, 2), "platform_fit": fit,
            "best_platforms": sorted(fit, key=lambda p: -fit[p])[:2],
            "evidence": f["evidence"][:1], "why": "Mock: concrete and easy to show.",
        })
    return {"angles": angles, "recommended": angles[0]["title"],
            "recommendation_reason": "Mock: highest score and the most concrete evidence."}


def _angle_text(a: dict) -> str:
    return f"{a['title']}. {a['summary']}"


def ground(angles: list[dict], repo: dict) -> tuple[list[dict], list[dict]]:
    kept, dropped = [], []
    for a in angles:
        check = validate(a["evidence"], repo)
        if check["valid"]:
            kept.append({**a, "evidence": check["valid"]})
        else:
            dropped.append({"title": a["title"], "reason": "no valid evidence: " + check["invalid"][0]["reason"]})
    return kept, dropped


def normalise_platforms(a: dict) -> dict:
    fit = {p: float(max(0.0, min(1.0, (a.get("platform_fit") or {}).get(p, 0.0) or 0.0)))
           for p in P.CONTENT_PLATFORMS}
    best = P.normalize(a.get("best_platforms") or [])
    best = [p for p in best if p in P.CONTENT_PLATFORMS]
    if not best:
        best = [p for p in sorted(fit, key=lambda p: -fit[p]) if fit[p] >= 0.55][:3] or \
               [max(fit, key=fit.get)]
    return {**a, "platform_fit": fit, "best_platforms": best}


def past_vectors(memory: dict) -> list[list[float]]:
    ids = memory.get("embedded_post_ids") or []
    if not ids:
        return []
    with db.connect() as conn:
        blobs = db.post_vectors(conn, ids)
    return [E.from_blob(b) for b in blobs.values()]


def dedup(angles: list[dict], past: list[list[float]]) -> list[dict]:
    """Mark each angle ok / unchecked / rejected. Never invents a score."""
    vecs = [E.embed(_angle_text(a)) for a in angles]
    on = all(v is not None for v in vecs)
    for a, v in zip(angles, vecs):
        a["max_similarity"], a["reject_reason"] = None, None
        if not on:
            a["dedup_status"] = "unchecked"
            continue
        sim = max((E.cosine(v, p) for p in past), default=0.0)
        a["max_similarity"] = round(sim, 3)
        if sim > DEDUP_THRESHOLD:
            a["dedup_status"], a["reject_reason"] = "rejected", f"too close to something you published ({sim:.2f})"
        else:
            a["dedup_status"] = "ok"
    if on:
        order = sorted(range(len(angles)), key=lambda i: -angles[i]["score"])
        for pos, i in enumerate(order):
            if angles[i]["dedup_status"] == "rejected":
                continue
            for j in order[:pos]:
                if angles[j]["dedup_status"] == "rejected":
                    continue
                sim = E.cosine(vecs[i], vecs[j])
                if sim > DEDUP_THRESHOLD:
                    angles[i]["dedup_status"] = "rejected"
                    angles[i]["reject_reason"] = f"same idea as '{angles[j]['title']}' ({sim:.2f})"
                    break
    return angles


def rank(angles: list[dict]) -> list[dict]:
    order = {"ok": 0, "unchecked": 1, "rejected": 2}
    return sorted(angles, key=lambda a: (order[a["dedup_status"]], -a["score"]))


def recommend(angles: list[dict], title: str | None, reason: str | None) -> dict | None:
    usable = [a for a in angles if a["dedup_status"] != "rejected"]
    if not usable:
        return None
    for a in usable:
        if title and a["title"].strip().lower() == title.strip().lower():
            return {"title": a["title"], "reason": reason, "platforms": a["best_platforms"], "source": "model"}
    note = "the model's pick was removed by the evidence/dedup checks; " if title else ""
    return {"title": usable[0]["title"], "reason": f"{note}highest-scoring usable angle.",
            "platforms": usable[0]["best_platforms"], "source": "fallback"}


class Angles(BaseAgent):
    agent_id = "A05"
    name = "angles"
    title = "Find the angles"
    requires = ("analysis", "profile", "memory", "repo", "run_id")
    produces = "angle_set"
    uses_llm = True

    def run(self, ctx: dict) -> dict:
        repo, analysis = ctx["repo"], ctx["analysis"]
        raw = llm.call(stage=self.name, tier="heavy", system=prompt(__file__),
                       user=build_user_prompt(repo, analysis, ctx["profile"], ctx["memory"]),
                       schema=AnglesOut, mock=mock_output(analysis), run_id=ctx["run_id"])
        angles, dropped = ground(raw["angles"], repo)
        angles = rank(dedup([normalise_platforms(a) for a in angles], past_vectors(ctx["memory"])))
        counts = {s: sum(a["dedup_status"] == s for a in angles) for s in ("ok", "unchecked", "rejected")}
        counts["dropped"] = len(dropped)
        usable = counts["ok"] + counts["unchecked"]
        if usable < MIN_USABLE:
            raise AgentError(f"only {usable} usable angle(s) after evidence + dedup checks "
                             f"(need {MIN_USABLE}). counts={counts}")
        return {"angles": angles, "counts": counts, "dropped": dropped,
                "recommendation": recommend(angles, raw.get("recommended"), raw.get("recommendation_reason"))}
