"""
[A08] writer - LLM agent (heavy tier). Writes every chosen platform, in the author's voice.

Input : ctx["strategy"], ctx["visual_plan"] (optional), ctx["profile"], ctx["repo"], ctx["run_id"]
Output: ctx["draft"]  {platforms: {linkedin: {text, first_comment},
                                    x: {tweets[]},
                                    instagram: {slides[{title, body}], caption},
                                    tiktok: {title, hook, duration_s, scenes[{seconds, visual, voiceover, on_screen}], caption}},
                       claims[], notes{platform: [..]}}

Static checks after the model answers:
  - claims re-checked; invalid ones dropped, at least 1 valid claim must remain
  - every chosen platform must be present (fail-closed)
  - markdown stripped (no platform renders it), plan hashtags appended if left out
  - hard limits: LinkedIn 3,000 chars, Instagram caption 2,200 -> stage fails
  - soft problems go to the critic as notes: tweets over 280, slide count, voiceover too
    long for the duration, hook changed, claimed observations ("I tested") and absolutes
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from agents.common import compact, platform_rules, prompt, strip_markdown, voice_block
from core import llm
from core import platforms as P
from core.base_agent import AgentError, BaseAgent, SkipStage
from core.evidence import validate
from core.schemas import Evidence

LENGTH_TOLERANCE = 0.3


class LinkedInPost(BaseModel):
    text: str = Field(min_length=150, max_length=3500)
    first_comment: Optional[str] = Field(default=None, max_length=1200)


class XThread(BaseModel):
    tweets: list[str] = Field(min_length=1, max_length=12)


class Slide(BaseModel):
    title: str = Field(min_length=1, max_length=90)
    body: str = Field(default="", max_length=400)


class IGCarousel(BaseModel):
    slides: list[Slide] = Field(min_length=2, max_length=12)
    caption: str = Field(min_length=20, max_length=2600)


class Scene(BaseModel):
    seconds: float = Field(gt=0, le=60)
    visual: str = Field(min_length=3, max_length=300, description="what is on screen")
    voiceover: str = Field(default="", max_length=600)
    on_screen: str = Field(default="", max_length=120, description="text overlay")


class TikTokScript(BaseModel):
    title: str = Field(min_length=3, max_length=100)
    hook: str = Field(min_length=3, max_length=120, description="on-screen text in the first 2 seconds")
    duration_s: int = Field(ge=5, le=180)
    scenes: list[Scene] = Field(min_length=2, max_length=14)
    caption: str = Field(min_length=10, max_length=2600)


class Drafts(BaseModel):
    linkedin: Optional[LinkedInPost] = None
    x: Optional[XThread] = None
    instagram: Optional[IGCarousel] = None
    tiktok: Optional[TikTokScript] = None
    claims: list[Evidence] = Field(min_length=1)


def build_user_prompt(strategy: dict, visual_plan: dict | None, profile: dict, repo: dict) -> str:
    plats = list(strategy["plans"])
    shots = (visual_plan or {}).get("shots") or []
    return "\n".join([
        f"PROJECT: {repo['owner']}/{repo['repo']}   url: {repo.get('url')}",
        f"CORE MESSAGE: {strategy['core_message']}",
        f"AUDIENCE: {strategy['audience_note']}",
        "",
        f"WRITE THESE PLATFORMS (and only these): {', '.join(plats)}",
        platform_rules(plats),
        "",
        "PLANS:", compact(strategy["plans"]),
        "",
        "EVIDENCE YOU MAY STATE (the only facts about the project you may use):",
        compact(strategy["evidence"]),
        "",
        "VISUALS THAT WILL BE CAPTURED (not taken yet):",
        *([f"- {s['shot']} ({', '.join(s.get('platforms') or [])})" for s in shots] or ["(none)"]),
        "",
        "AUTHOR VOICE (write like this person):", voice_block(profile),
        "",
        "Return all drafts as JSON matching the schema.",
    ])


def mock_output(strategy: dict) -> dict:
    filler = ("Mock filler so the draft clears the minimum length the schema enforces on real "
              "model output. It says nothing new.")
    out: dict = {"claims": strategy["evidence"][:2]}
    pl = strategy["plans"]
    if "linkedin" in pl:
        p = pl["linkedin"]
        out["linkedin"] = {"text": "\n\n".join([p["hook"], *p["beats"], filler, p["cta"], " ".join(p["hashtags"])]),
                           "first_comment": "Mock first comment with the link."}
    if "x" in pl:
        p = pl["x"]
        out["x"] = {"tweets": [p["hook"], *p["beats"][: max(0, p["length"] - 2)], p["cta"]]}
    if "instagram" in pl:
        p = pl["instagram"]
        slides = [{"title": p["hook"][:80], "body": "Swipe"}] + [{"title": b[:80], "body": "Mock slide body."} for b in p["beats"]]
        out["instagram"] = {"slides": slides + [{"title": "Save this", "body": p["cta"]}],
                            "caption": f"{p['hook']}\n\n{filler}\n\n{p['cta']}\n\n{' '.join(p['hashtags'])}"}
    if "tiktok" in pl:
        p = pl["tiktok"]
        out["tiktok"] = {"title": "Mock video", "hook": p["hook"][:110], "duration_s": p["length"],
                         "scenes": [{"seconds": 3, "visual": "Mock: hook text over the result", "voiceover": p["hook"], "on_screen": p["hook"][:60]}]
                         + [{"seconds": 8, "visual": "Mock: screen recording", "voiceover": b, "on_screen": b[:40]} for b in p["beats"]],
                         "caption": f"{p['cta']} {' '.join(p['hashtags'])}"}
    return out


OBSERVED_RE = re.compile(
    r"\b(?:screenshot|screenshots|screen ?shot|output|terminal|demo|video|photo)\b[^.\n]{0,25}\b(?:shows?|proves?|confirms?|demonstrates?)\b"
    r"|\bI (?:ran|tested|measured|benchmarked|scanned|verified|reproduced|confirmed|surveyed|interviewed)\b"
    r"|\bin my (?:tests?|testing|runs?|experiments?)\b", re.I)
QUANT_RE = re.compile(r"\b(?:always|never|every single|all of|in all cases|guaranteed|100%)\b", re.I)


def unbacked_language(text: str) -> list[str]:
    out = [f'claims a result or run the evidence does not show: "{m.group(0).strip()}"'
           for m in OBSERVED_RE.finditer(text)]
    out += [f'absolute wording, check the evidence supports it: "{m.group(0)}"' for m in QUANT_RE.finditer(text)]
    return out


def tidy(platform: str, d: dict, plan: dict) -> tuple[dict, list[str]]:
    """Clean one platform draft, enforce hard limits, return (draft, notes for the critic)."""
    s, notes, tags = P.SPECS[platform], [], plan.get("hashtags") or []
    if platform == "linkedin":
        d["text"] = P.ensure_hashtags(strip_markdown(d["text"]), tags)
        if len(d["text"]) > s["max_chars"]:
            raise AgentError(f"LinkedIn draft is {len(d['text'])} chars; the limit is {s['max_chars']}")
        if abs(len(d["text"]) - plan["length"]) > plan["length"] * LENGTH_TOLERANCE:
            notes.append(f"length {len(d['text'])} chars vs planned {plan['length']}")
    elif platform == "x":
        d["tweets"] = [strip_markdown(t) for t in d["tweets"] if t.strip()]
        missing = [t for t in tags if t.lower() not in " ".join(d["tweets"]).lower()]
        if missing and P.x_len(d["tweets"][-1] + " " + " ".join(missing)) <= s["tweet_max"]:
            d["tweets"][-1] = d["tweets"][-1].rstrip() + " " + " ".join(missing)
        for i, t in enumerate(d["tweets"], 1):
            if P.x_len(t) > s["tweet_max"]:
                notes.append(f"tweet {i} is {P.x_len(t)} chars, over {s['tweet_max']}")
    elif platform == "instagram":
        d["caption"] = P.ensure_hashtags(strip_markdown(d["caption"]), tags)
        if len(d["caption"]) > s["max_chars"]:
            raise AgentError(f"Instagram caption is {len(d['caption'])} chars; the limit is {s['max_chars']}")
        lo, hi = s["slides"]
        if not lo <= len(d["slides"]) <= hi:
            notes.append(f"{len(d['slides'])} slides; Instagram allows {lo}-{hi} here")
        for i, sl in enumerate(d["slides"], 1):
            sl["title"], sl["body"] = strip_markdown(sl["title"]), strip_markdown(sl["body"])
            if len(sl["body"].split()) > s["slide_body_words"]:
                notes.append(f"slide {i} body has {len(sl['body'].split())} words; keep it under {s['slide_body_words']}")
    elif platform == "tiktok":
        d["caption"] = P.ensure_hashtags(strip_markdown(d["caption"]), tags)
        total = round(sum(sc["seconds"] for sc in d["scenes"]))
        d["duration_s"] = total or d["duration_s"]
        words, wps = P.voiceover_words(d), s["words_per_second"]
        if words > d["duration_s"] * wps * 1.15:
            notes.append(f"voiceover has {words} words for {d['duration_s']}s; at ~{wps} words/s it needs "
                         f"{round(words / wps)}s. Cut words or lengthen scenes")
        lo, hi = s["duration"]
        if not lo <= d["duration_s"] <= hi:
            notes.append(f"video is {d['duration_s']}s; aim for {lo}-{hi}s")
    head = P.headline_of(platform, d).strip()
    if plan.get("hook") and head != plan["hook"].strip() and platform in ("linkedin", "x"):
        notes.append("first line differs from the planned hook")
    return d, notes + unbacked_language(P.draft_text(platform, d))


class Writer(BaseAgent):
    agent_id = "A08"
    name = "writer"
    title = "Write every platform"
    requires = ("profile", "repo", "run_id")
    produces = "draft"
    uses_llm = True

    def run(self, ctx: dict) -> dict:
        strategy = ctx.get("strategy")
        if not strategy:
            raise SkipStage("no content platform chosen")
        d = llm.call(stage=self.name, tier="heavy", system=prompt(__file__),
                     user=build_user_prompt(strategy, ctx.get("visual_plan"), ctx["profile"], ctx["repo"]),
                     schema=Drafts, mock=mock_output(strategy), run_id=ctx["run_id"])
        check = validate(d["claims"], ctx["repo"])
        if not check["valid"]:
            raise AgentError("draft has no valid claims: " + check["invalid"][0]["reason"])
        missing = [p for p in strategy["plans"] if not d.get(p)]
        if missing:
            raise AgentError(f"writer left out: {', '.join(missing)}")
        platforms, notes = {}, {}
        for p, plan in strategy["plans"].items():
            platforms[p], notes[p] = tidy(p, d[p], plan)
        if check["invalid"]:
            notes.setdefault("all", []).extend(f"claim dropped: {i['reason']}" for i in check["invalid"])
        return {"platforms": platforms, "claims": check["valid"], "notes": notes}
