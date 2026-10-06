"""
[A06] strategist - LLM agent (mid tier). One core message, shaped per platform.

Input : ctx["chosen_angle"], ctx["platforms"] (picked at G1), ctx["analysis"],
        ctx["profile"], ctx["repo"], ctx["run_id"]
Output: ctx["strategy"]  {core_message, audience_note, evidence[], confidence, rationale,
                          plans: {platform: {format, hook, beats[], length, cta, hashtags[]}}}
        length means: linkedin = characters, x = tweets, instagram = slides, tiktok = seconds.

Static checks after the model answers:
  - evidence re-checked; at least 1 valid item must remain
  - a plan for every chosen content platform must exist (fail-closed)
  - hashtags cleaned and capped per platform; length clamped to the platform's range
Skips when only "github" was chosen (the showcase agent handles that alone).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from agents.common import compact, platform_rules, prompt, voice_block
from core import llm
from core import platforms as P
from core.base_agent import AgentError, BaseAgent, SkipStage
from core.evidence import validate
from core.schemas import Evidence

FORMATS = ("story", "lesson-list", "myth-vs-fact", "how-to", "breakdown", "hot-take", "thread",
           "carousel", "demo", "before-after", "timelapse", "talking-points", "listicle", "case-study")
RANGES = {"linkedin": (600, 2200), "x": (1, 10), "instagram": (3, 10), "tiktok": (15, 90)}


class PlatformPlan(BaseModel):
    platform: Literal[P.CONTENT_PLATFORMS]
    format: Literal[FORMATS]
    hook: str = Field(min_length=6, max_length=170)
    beats: list[str] = Field(min_length=2, max_length=10)
    length: int = Field(ge=1, le=3000, description="linkedin: chars, x: tweets, instagram: slides, tiktok: seconds")
    cta: str = Field(min_length=4, max_length=200)
    hashtags: list[str] = Field(default_factory=list, max_length=15)


class Strategy(BaseModel):
    core_message: str = Field(min_length=10, max_length=240, description="the one idea every platform carries")
    audience_note: str = Field(min_length=8)
    plans: list[PlatformPlan] = Field(min_length=1, max_length=4)
    evidence: list[Evidence] = Field(min_length=1)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    rationale: Optional[str] = Field(default=None, description="1-2 sentences: why these formats")


def content_platforms(ctx: dict) -> list[str]:
    return [p for p in P.normalize(ctx.get("platforms") or []) if p in P.CONTENT_PLATFORMS]


def build_user_prompt(angle: dict, platforms: list[str], analysis: dict, profile: dict) -> str:
    return "\n".join([
        "CHOSEN ANGLE:",
        compact({k: angle.get(k) for k in ("title", "summary", "hook", "post_type", "audience", "evidence")}),
        "",
        f"PLATFORMS TO PLAN (one plan each): {', '.join(platforms)}",
        platform_rules(platforms),
        "",
        "PROJECT:", f"summary: {analysis.get('summary', '')}", f"purpose: {analysis.get('purpose', '')}",
        f"kind: {analysis.get('project_kind')}  field: {analysis.get('field')}",
        "",
        "AUTHOR VOICE:", voice_block(profile),
        "",
        "Return the strategy as JSON matching the schema.",
    ])


def mock_output(angle: dict, platforms: list[str]) -> dict:
    fmt = {"linkedin": "lesson-list", "x": "thread", "instagram": "carousel", "tiktok": "demo"}
    length = {"linkedin": 1100, "x": 5, "instagram": 6, "tiktok": 40}
    return {
        "core_message": f"Mock core message: {angle['title']}"[:240],
        "audience_note": "Mock: curious peers who know the basics.",
        "plans": [{"platform": p, "format": fmt[p], "hook": angle.get("hook") or "Mock hook",
                   "beats": ["Mock beat: the fact", "Mock beat: why it matters", "Mock beat: what to try"],
                   "length": length[p], "cta": "Mock CTA: what would you try first?",
                   "hashtags": ["#BuildInPublic", "#Mock"]} for p in platforms],
        "evidence": angle["evidence"][:2], "confidence": 0.7, "rationale": "Mock: one fact, shaped per platform.",
    }


class Strategist(BaseAgent):
    agent_id = "A06"
    name = "strategist"
    title = "Plan each platform"
    requires = ("chosen_angle", "analysis", "profile", "repo", "run_id")
    produces = "strategy"
    uses_llm = True

    def run(self, ctx: dict) -> dict:
        plats = content_platforms(ctx)
        if not plats:
            raise SkipStage("no content platform chosen (GitHub kit only)")
        angle = ctx["chosen_angle"]
        s = llm.call(stage=self.name, tier="mid", system=prompt(__file__),
                     user=build_user_prompt(angle, plats, ctx["analysis"], ctx["profile"]),
                     schema=Strategy, mock=mock_output(angle, plats), run_id=ctx["run_id"])
        check = validate(s["evidence"], ctx["repo"])
        if not check["valid"]:
            raise AgentError("strategy has no valid evidence: " + check["invalid"][0]["reason"])
        plans = {}
        for plan in s["plans"]:
            p = plan["platform"]
            if p in plats and p not in plans:
                lo, hi = RANGES[p]
                plan["length"] = max(lo, min(hi, plan["length"]))
                plan["hashtags"] = P.clean_hashtags(plan["hashtags"], p)
                plans[p] = plan
        missing = [p for p in plats if p not in plans]
        if missing:
            raise AgentError(f"strategy has no plan for: {', '.join(missing)}")
        return {"core_message": s["core_message"], "audience_note": s["audience_note"],
                "evidence": check["valid"], "confidence": s.get("confidence"),
                "rationale": s.get("rationale"), "plans": plans, "platforms": plats}
