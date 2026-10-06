"""
[A07] visuals - LLM agent (mid tier). What each platform shows, and how to make it fast.

Input : ctx["strategy"], ctx["profile"], ctx["repo"], ctx["run_id"]
Output: ctx["visual_plan"] {graphic{style, headline, subline, stat},
                            shots[{shot, kind, how, file_path, lines, minutes, platforms[]}],
                            reuse[{file_path, use}], image_prompts[{platform, tool, prompt}],
                            rationale, dropped[]}

Facetcast renders the cover graphics itself (LinkedIn card, X card, Instagram slides,
TikTok cover, GitHub social preview) in the theme the profiler picked. This agent plans
the headline for them, the screenshots / photos / screen recordings worth capturing, which
images already in the project can be reused, and ready-to-paste prompts for image tools.

Static checks: any file_path must exist in the project (reuse items must be images);
minutes clamped to 1-10; at most 6 shots. Failures are dropped with the reason.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from agents.common import compact, prompt
from core import llm
from core import platforms as P
from core.base_agent import BaseAgent, SkipStage
from core.schemas import Graphic

MAX_SHOTS = 6
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


class Shot(BaseModel):
    shot: str = Field(min_length=4, max_length=120, description="what the image or clip shows")
    kind: Literal["screenshot", "screen-recording", "photo", "code", "terminal", "diagram", "b-roll", "text-card"]
    how: str = Field(min_length=10, description="concrete steps to produce it")
    file_path: Optional[str] = Field(default=None, description="project file it comes from, if any")
    lines: Optional[str] = Field(default=None)
    minutes: int = Field(ge=1, le=30)
    platforms: list[str] = Field(default_factory=list)


class Reuse(BaseModel):
    file_path: str
    use: str = Field(min_length=5, max_length=200)


class ImagePrompt(BaseModel):
    platform: str = Field(min_length=1, max_length=20)
    tool: str = Field(min_length=2, max_length=40, description="Canva, ChatGPT, Gemini, Midjourney, Ideogram...")
    prompt: str = Field(min_length=20, max_length=1200)


class VisualPlan(BaseModel):
    graphic: Graphic
    shots: list[Shot] = Field(default_factory=list, max_length=8)
    reuse: list[Reuse] = Field(default_factory=list, max_length=6)
    image_prompts: list[ImagePrompt] = Field(default_factory=list, max_length=4)
    rationale: str = Field(min_length=10)


def build_user_prompt(strategy: dict, profile: dict, repo: dict) -> str:
    plans = {p: {k: v for k, v in pl.items() if k in ("format", "hook", "beats")} for p, pl in strategy["plans"].items()}
    return "\n".join([
        f"CORE MESSAGE: {strategy['core_message']}",
        "PLATFORM PLANS:", compact(plans),
        "",
        f"THEME (rendered automatically): {compact(profile.get('theme'), None)}",
        "",
        "IMAGES ALREADY IN THE PROJECT:", *([f"- {p}" for p in repo.get("images", [])] or ["- (none)"]),
        "",
        f"FILE TREE of {repo['owner']}/{repo['repo']}:",
        *[f"- {f['path']}" for f in repo.get("tree", [])[:400]],
        "",
        "Return the visual plan as JSON matching the schema.",
    ])


def mock_output(strategy: dict, repo: dict) -> dict:
    plats = list(strategy["plans"])
    ev = strategy["evidence"][0]
    imgs = repo.get("images") or []
    return {"graphic": {"style": "headline", "headline": strategy["core_message"][:100], "subline": "Mock subline"},
            "shots": [{"shot": "Mock capture of the main file", "kind": "screenshot",
                       "how": "Mock: open the file, zoom 150%, crop to the key part.",
                       "file_path": ev["source_path"], "lines": None, "minutes": 3, "platforms": plats}],
            "reuse": [{"file_path": imgs[0], "use": "Mock: use as slide 2."}] if imgs else [],
            "image_prompts": [{"platform": plats[0], "tool": "Canva",
                               "prompt": "Mock: clean editorial card, one headline line, lots of empty space."}],
            "rationale": "Mock: one capture proves the main fact."}


def check(plan: dict, repo: dict) -> dict:
    paths = {f["path"] for f in repo.get("tree", [])}
    shots, dropped = [], []
    for s in plan["shots"]:
        fp = (s.get("file_path") or "").replace("\\", "/") or None
        s["file_path"] = fp
        s["platforms"] = P.normalize(s.get("platforms") or [])
        if fp and fp not in paths:
            dropped.append({"item": s["shot"], "reason": f"file not in project: {fp}"})
        elif s["kind"] == "code" and not fp:
            dropped.append({"item": s["shot"], "reason": "code shot without file_path"})
        elif len(shots) >= MAX_SHOTS:
            dropped.append({"item": s["shot"], "reason": f"more than {MAX_SHOTS} shots"})
        else:
            s["minutes"] = max(1, min(10, s["minutes"]))
            shots.append(s)
    reuse = []
    for r in plan.get("reuse") or []:
        fp = r["file_path"].replace("\\", "/")
        if fp in paths and Path(fp).suffix.lower() in IMAGE_EXT:
            reuse.append({**r, "file_path": fp})
        else:
            dropped.append({"item": fp, "reason": "not an image in the project"})
    plan.update(shots=shots, reuse=reuse, dropped=dropped)
    return plan


class Visuals(BaseAgent):
    agent_id = "A07"
    name = "visuals"
    title = "Plan the visuals"
    requires = ("profile", "repo", "run_id")
    produces = "visual_plan"
    uses_llm = True

    def run(self, ctx: dict) -> dict:
        strategy = ctx.get("strategy")
        if not strategy:
            raise SkipStage("no content platform chosen")
        plan = llm.call(stage=self.name, tier="mid", system=prompt(__file__),
                        user=build_user_prompt(strategy, ctx["profile"], ctx["repo"]),
                        schema=VisualPlan, mock=mock_output(strategy, ctx["repo"]), run_id=ctx["run_id"])
        return check(plan, ctx["repo"])
