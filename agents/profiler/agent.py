"""
[A04] profiler - LLM agent (mid tier). NEW. Reads the author's VOICE from the README.

Facetcast is not tuned to one person. Every project arrives with its own voice: how its
README is written (first person or "we", dry or playful, technical or plain, emoji or
none) is the best sample of how its author talks. The profiler turns that into a voice
profile every writing agent follows, plus where this project will land best.

Input : ctx["repo"], ctx["analysis"], ctx["run_id"]
        optional: memory/voice/*.md (the author's own past posts) refine the voice
Output: ctx["profile"]  {voice{...}, audiences[], positioning, readme{score, strengths, gaps},
                         platform_fit{platform: {score, why}}, theme{name, accent, why},
                         voice_source, user_voice_used, phrases_dropped[]}

Static checks after the model answers:
  - signature_phrases must appear word for word in the README (else dropped)
  - accent must be a #RRGGBB colour (else the theme's default)
  - every platform gets a fit score (missing ones -> 0.5, "not scored")
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from agents.common import compact, prompt, user_voice
from core import llm
from core import platforms as P
from core.base_agent import BaseAgent

THEMES = ("midnight", "paper", "bold", "terminal", "pastel")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class Voice(BaseModel):
    person: Literal["I", "we", "impersonal"] = Field(description="how the author refers to themselves")
    tone: list[str] = Field(min_length=2, max_length=5, description="3-5 adjectives")
    formality: int = Field(ge=1, le=5, description="1 = casual chat, 5 = academic")
    energy: int = Field(ge=1, le=5, description="1 = calm, 5 = excited")
    humor: Literal["none", "light", "playful"]
    emoji: Literal["none", "some", "heavy"]
    sentence_style: str = Field(min_length=5, max_length=200, description="length and rhythm of sentences")
    vocabulary: str = Field(min_length=5, max_length=200, description="jargon level and word choice")
    signature_phrases: list[str] = Field(default_factory=list, max_length=6,
                                         description="short phrases copied exactly from the README")
    do: list[str] = Field(default_factory=list, max_length=5)
    avoid: list[str] = Field(default_factory=list, max_length=5)


class Audience(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    cares_about: str = Field(min_length=5, max_length=200)


class Fit(BaseModel):
    score: float = Field(ge=0, le=1)
    why: str = Field(min_length=5, max_length=240)


class Readme(BaseModel):
    score: int = Field(ge=0, le=100, description="how well the README sells and explains the project")
    strengths: list[str] = Field(default_factory=list, max_length=5)
    gaps: list[str] = Field(default_factory=list, max_length=6)


class Theme(BaseModel):
    name: Literal[THEMES]
    accent: str = Field(description="#RRGGBB accent colour that suits the project")
    why: str = Field(min_length=5, max_length=200)


class ProfileOut(BaseModel):
    voice: Voice
    audiences: list[Audience] = Field(min_length=1, max_length=4)
    positioning: str = Field(min_length=10, max_length=200, description="one-line pitch in the author's voice")
    readme: Readme
    platform_fit: dict[str, Fit] = Field(description="keys: linkedin, x, instagram, tiktok, github")
    theme: Theme


def build_user_prompt(repo: dict, analysis: dict, mine: str) -> str:
    return "\n".join([
        f"PROJECT: {repo['owner']}/{repo['repo']}   kind: {analysis.get('project_kind')}   field: {analysis.get('field')}",
        f"SUMMARY: {analysis.get('summary')}",
        f"PURPOSE: {analysis.get('purpose')}",
        "",
        f"README ({repo.get('readme_path') or 'none'}) - the main voice sample:",
        "<<<", repo.get("readme") or "(no README)", ">>>",
        "",
        "COMMIT MESSAGES (secondary voice sample):",
        *([f"- {c['subject']}" for c in repo.get("commits", [])[:20]] or ["- (none)"]),
        "",
        "THE AUTHOR'S OWN PAST POSTS (strongest voice sample when present):",
        mine or "(none provided)",
        "",
        "HIGHLIGHTS FROM THE ANALYSIS:",
        compact([{"title": f["title"], "detail": f["detail"]} for f in analysis.get("highlights", [])][:8]),
        "",
        "Return the profile as JSON matching the schema.",
    ])


def mock_output(repo: dict) -> dict:
    words = (repo.get("readme") or "A small project").split()
    return {
        "voice": {"person": "I", "tone": ["plain", "curious", "direct"], "formality": 2, "energy": 3,
                  "humor": "light", "emoji": "none", "sentence_style": "Short sentences, mostly under 15 words.",
                  "vocabulary": "Plain words, little jargon.", "signature_phrases": [" ".join(words[:3])],
                  "do": ["lead with the concrete detail"], "avoid": ["hype"]},
        "audiences": [{"name": "Curious peers", "cares_about": "How it was made and what was learned"}],
        "positioning": f"{repo['repo']}: a mock positioning line for tests.",
        "readme": {"score": 62, "strengths": ["Explains the idea"], "gaps": ["No screenshots", "No setup section"]},
        "platform_fit": {p: {"score": round(0.8 - i * 0.1, 2), "why": f"Mock fit for {p}."}
                         for i, p in enumerate(P.ALL_PLATFORMS)},
        "theme": {"name": "midnight", "accent": "#7C9CFF", "why": "Mock theme."},
    }


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("’", "'")).strip().lower()


def check(profile: dict, readme: str) -> dict:
    body = _norm(readme)
    v = profile["voice"]
    kept = [p for p in v.get("signature_phrases", []) if p.strip() and _norm(p) in body]
    profile["phrases_dropped"] = [p for p in v.get("signature_phrases", []) if p not in kept]
    v["signature_phrases"] = kept
    if not HEX_RE.match(profile["theme"].get("accent") or ""):
        profile["theme"]["accent"] = None
    fit = profile.get("platform_fit") or {}
    profile["platform_fit"] = {p: fit.get(p) or {"score": 0.5, "why": "not scored"} for p in P.ALL_PLATFORMS}
    return profile


class Profiler(BaseAgent):
    agent_id = "A04"
    name = "profiler"
    title = "Learn the voice"
    requires = ("repo", "analysis", "run_id")
    produces = "profile"
    uses_llm = True

    def run(self, ctx: dict) -> dict:
        repo, mine = ctx["repo"], user_voice()
        raw = llm.call(stage=self.name, tier="mid", system=prompt(__file__),
                       user=build_user_prompt(repo, ctx["analysis"], mine),
                       schema=ProfileOut, mock=mock_output(repo), run_id=ctx["run_id"])
        out = check(raw, repo.get("readme") or "")
        out["voice_source"] = f"the README ({repo['readme_path']})" if repo.get("readme") else "files and commits (no README found)"
        out["user_voice_used"] = bool(mine)
        return out
