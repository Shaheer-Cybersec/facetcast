"""
[A11] showcase - LLM agent (heavy tier). NEW. Makes the project itself portfolio-ready.

For freelancers, students and job seekers the repository IS the portfolio. This agent
audits it and writes what makes it land with a stranger, a client or a recruiter:

Input : ctx["repo"], ctx["analysis"], ctx["profile"], ctx["run_id"]; runs only when
        "github" was picked at G1 (skips otherwise).
Output: ctx["showcase"] {description, topics[], tagline, checklist[{item, status, fix}],
                         readme_draft, case_study{title, problem, approach, outcome, stack[], role},
                         freelance_pitch, pinned_blurb, social_preview{headline, subline},
                         claims[], readme_score, notes[]}

Static checks after the model answers:
  - description cut to GitHub's 350 characters at a word boundary (noted)
  - topics normalised to GitHub's format (lowercase, a-z0-9 and hyphens, max 50 chars, max 20)
  - claims re-checked against the real files; at least 1 valid claim must remain
  - the README draft must not invent links to files that do not exist (noted, not failed)
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from agents.common import compact, prompt, voice_block
from core import llm
from core import platforms as P
from core.base_agent import AgentError, BaseAgent, SkipStage
from core.evidence import validate
from core.schemas import Evidence

TOPIC_RE = re.compile(r"[^a-z0-9-]+")
MD_LINK_RE = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)")


class CheckItem(BaseModel):
    item: str = Field(min_length=3, max_length=80)
    status: Literal["ok", "weak", "missing"]
    fix: str = Field(default="", max_length=300)


class CaseStudy(BaseModel):
    title: str = Field(min_length=4, max_length=100)
    problem: str = Field(min_length=10, max_length=600)
    approach: str = Field(min_length=10, max_length=900)
    outcome: str = Field(min_length=10, max_length=600)
    stack: list[str] = Field(default_factory=list, max_length=12)
    role: str = Field(default="", max_length=160)


class Preview(BaseModel):
    headline: str = Field(min_length=3, max_length=80)
    subline: Optional[str] = Field(default=None, max_length=140)


class ShowcaseOut(BaseModel):
    description: str = Field(min_length=10, max_length=500)
    topics: list[str] = Field(default_factory=list, max_length=25)
    tagline: str = Field(min_length=5, max_length=120)
    checklist: list[CheckItem] = Field(min_length=3, max_length=14)
    readme_draft: str = Field(min_length=200, max_length=20000)
    case_study: CaseStudy
    freelance_pitch: str = Field(min_length=20, max_length=700)
    pinned_blurb: str = Field(min_length=5, max_length=160)
    social_preview: Preview
    claims: list[Evidence] = Field(min_length=1)


def build_user_prompt(repo: dict, analysis: dict, profile: dict) -> str:
    comp = {k: analysis.get(k) for k in ("summary", "purpose", "project_kind", "field",
                                         "components", "decisions", "highlights", "limitations")}
    return "\n".join([
        f"PROJECT: {repo['owner']}/{repo['repo']}   url: {repo.get('url')}   source: {repo.get('source_type')}",
        f"LANGUAGES / FILE TYPES: {compact(repo.get('languages'), None)}",
        f"IMAGES IN THE PROJECT: {', '.join(repo.get('images') or []) or '(none)'}",
        f"DEPENDENCY FILES: {', '.join(repo.get('dependencies') or {}) or '(none)'}",
        f"HAS LICENSE FILE: {any(f['path'].lower().startswith('license') for f in repo.get('tree', []))}",
        "",
        "PROFILER'S README REVIEW:", compact(profile.get("readme")),
        "",
        "AUTHOR VOICE:", voice_block(profile),
        "",
        f"CURRENT README ({repo.get('readme_path') or 'none'}):",
        "<<<", repo.get("readme") or "(no README)", ">>>",
        "",
        "GROUNDED ANALYSIS (evidence you may cite in claims):", compact(comp),
        "",
        "FILE TREE:", *[f"- {f['path']}" for f in repo.get("tree", [])[:300]],
        "",
        "Return the showcase kit as JSON matching the schema.",
    ])


def mock_output(repo: dict, analysis: dict) -> dict:
    ev = next((f["evidence"][0] for s in ("components", "highlights", "decisions")
               for f in analysis.get(s, [])), None)
    return {
        "description": f"Mock description of {repo['repo']} for tests.",
        "topics": ["Mock Topic", "facetcast_demo", "portfolio"],
        "tagline": "Mock tagline.",
        "checklist": [{"item": "Clear one-line purpose", "status": "ok", "fix": ""},
                      {"item": "Screenshots or demo", "status": "missing", "fix": "Add one image near the top."},
                      {"item": "How to run / view it", "status": "weak", "fix": "Add a 3-step quick start."}],
        "readme_draft": f"# {repo['repo']}\n\nMock README draft. " + "It explains the project plainly. " * 10,
        "case_study": {"title": f"{repo['repo']} case study", "problem": "Mock problem statement.",
                       "approach": "Mock approach description.", "outcome": "Mock outcome, no invented numbers.",
                       "stack": ["Mock"], "role": "Solo"},
        "freelance_pitch": "Mock pitch: I built this; I can build something like it for you.",
        "pinned_blurb": "Mock pinned blurb.",
        "social_preview": {"headline": repo["repo"], "subline": "Mock subline"},
        "claims": [ev] if ev else [],
    }


def clean_topics(topics: list[str]) -> list[str]:
    out = []
    for t in topics:
        t = TOPIC_RE.sub("-", str(t).lower().replace("_", "-").replace(" ", "-")).strip("-")[:50]
        t = re.sub(r"-{2,}", "-", t)
        if t and t not in out:
            out.append(t)
    return out[:P.SPECS["github"]["topics_max"]]


def cut(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"


class Showcase(BaseAgent):
    agent_id = "A11"
    name = "showcase"
    title = "GitHub & portfolio kit"
    requires = ("repo", "analysis", "profile", "run_id")
    produces = "showcase"
    uses_llm = True

    def run(self, ctx: dict) -> dict:
        if "github" not in P.normalize(ctx.get("platforms") or []):
            raise SkipStage("GitHub & portfolio kit not selected")
        repo = ctx["repo"]
        s = llm.call(stage=self.name, tier="heavy", system=prompt(__file__),
                     user=build_user_prompt(repo, ctx["analysis"], ctx["profile"]),
                     schema=ShowcaseOut, mock=mock_output(repo, ctx["analysis"]), run_id=ctx["run_id"])
        check = validate(s["claims"], repo)
        if not check["valid"]:
            raise AgentError("showcase has no valid claims: " +
                             (check["invalid"][0]["reason"] if check["invalid"] else "none given"))
        notes = [f"claim dropped: {i['reason']}" for i in check["invalid"]]
        lim = P.SPECS["github"]["description_max"]
        if len(s["description"]) > lim:
            notes.append(f"description cut from {len(s['description'])} to {lim} chars")
            s["description"] = cut(s["description"], lim)
        s["topics"] = clean_topics(s["topics"])
        paths = {f["path"] for f in repo.get("tree", [])}
        for link in MD_LINK_RE.findall(s["readme_draft"]):
            target = link.split("#")[0].lstrip("./")
            if target and target not in paths:
                notes.append(f"README draft links to '{target}', which is not in the project yet (add it or remove the link)")
        return {**s, "claims": check["valid"], "notes": notes,
                "readme_score": (ctx["profile"].get("readme") or {}).get("score")}
