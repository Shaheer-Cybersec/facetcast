"""
[A03] analyzer - LLM agent (heavy tier). Understands what the project IS.

Input : ctx["repo"], ctx["run_id"]
Output: ctx["analysis"]  {summary, purpose, project_kind, field, components[], decisions[],
                          highlights[], limitations[], dropped[]}
        Each finding = {title, detail, evidence: [Evidence]}

Works for any project: software, research, a thesis, a design or art portfolio, a
dataset, hardware, writing. The README leads; files back it up.

After the model answers, EVERY evidence item is checked against the real file tree and
commits (core/evidence.py):
  - invalid evidence items are removed (listed in "dropped" with the reason)
  - a finding left with no valid evidence is removed entirely
  - fewer than 2 grounded findings left -> the stage fails (fail-closed)
So nothing ungrounded reaches the angle, strategy or writing stages.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agents.common import allowed_refs, prompt
from core import llm
from core.base_agent import AgentError, BaseAgent
from core.evidence import validate
from core.schemas import Evidence

MIN_FINDINGS = 2
SECTIONS = ("components", "decisions", "highlights", "limitations")
KINDS = ("software", "library", "research", "thesis", "creative", "design", "data", "hardware",
         "writing", "education", "other")


class Finding(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    detail: str = Field(min_length=10)
    evidence: list[Evidence] = Field(min_length=1)


class AnalysisOut(BaseModel):
    summary: str = Field(min_length=20, description="2-3 sentences: what this project is")
    purpose: str = Field(min_length=10, description="the problem or question it exists for")
    project_kind: Literal[KINDS] = Field(description="closest category")
    field: str = Field(min_length=2, max_length=80, description="domain, e.g. 'urban photography', 'web security'")
    components: list[Finding] = Field(min_length=1, description="main parts / chapters / modules and what each does")
    decisions: list[Finding] = Field(default_factory=list, description="notable choices: methods, tools, materials, trade-offs")
    highlights: list[Finding] = Field(default_factory=list, description="the most interesting facts: results, surprises, numbers stated in the files")
    limitations: list[Finding] = Field(default_factory=list, description="what it does not do or does not claim")


def build_user_prompt(repo: dict) -> str:
    parts = [
        f"PROJECT: {repo['owner']}/{repo['repo']}  ({repo['url']})",
        f"SOURCE: {repo.get('source_type')}   REF: {repo['head_sha'][:12]} ({repo.get('source_ref_kind')})",
        f"FIRST GUESS OF KIND (from file types, may be wrong): {repo.get('kind_hint')}",
        "",
        "ALLOWED REFS (use one of these as source_ref):",
        *[f"- {r}" for r in allowed_refs(repo)],
        "",
        "RECENT COMMITS:",
        *([f"- {c['sha'][:7]} {c['date']} {c['subject']}" for c in repo.get("commits", [])[:15]] or ["- (no history)"]),
        "",
        f"FILE TREE ({repo['file_count']} files{', truncated' if repo.get('tree_truncated') else ''}):",
        *[f"- {f['path']}" for f in repo.get("tree", [])],
        "",
        f"README ({repo.get('readme_path') or 'none found'}):",
        repo.get("readme") or "(no README in this project)",
        "",
        "DEPENDENCY FILES:",
    ]
    for path, text in (repo.get("dependencies") or {}).items():
        parts += [f"--- {path}", text]
    parts += ["", "KEY FILES (writing and entry points first):"]
    for path, text in (repo.get("key_files") or {}).items():
        parts += [f"=== FILE: {path} ===", text]
    parts += ["", "Produce the analysis as JSON matching the schema."]
    return "\n".join(parts)


def mock_output(repo: dict) -> dict:
    paths = ([repo["readme_path"]] if repo.get("readme_path") else []) + list((repo.get("key_files") or {}).keys())
    paths = paths or [f["path"] for f in repo["tree"]]
    ref = allowed_refs(repo)[0]
    ev = lambda i, claim: [{"claim": claim, "source_path": paths[i % len(paths)], "source_ref": ref}]
    return {
        "summary": f"{repo['repo']} analysed in mock mode. This text is a placeholder produced without any model.",
        "purpose": "Mock purpose used to test the pipeline wiring.",
        "project_kind": "other", "field": "mock field",
        "components": [{"title": "Main document", "detail": "Mock: the main description of the project.",
                        "evidence": ev(0, "This file describes the project")}],
        "decisions": [{"title": "Structure", "detail": "Mock: files are split by concern.",
                       "evidence": ev(1, "This file exists in the project")}],
        "highlights": [{"title": "Key idea", "detail": "Mock: the most interesting fact.",
                        "evidence": ev(0, "The README states the key idea")}],
        "limitations": [],
    }


def ground(analysis: dict, repo: dict) -> tuple[dict, int]:
    """Drop invalid evidence and unsupported findings. Returns (grounded, kept_count)."""
    dropped, kept = [], 0
    for section in SECTIONS:
        good = []
        for f in analysis.get(section, []):
            check = validate(f["evidence"], repo)
            for bad in check["invalid"]:
                dropped.append({"section": section, "finding": f["title"], "reason": bad["reason"]})
            if check["valid"]:
                good.append({**f, "evidence": check["valid"]})
                kept += 1
            else:
                dropped.append({"section": section, "finding": f["title"],
                                "reason": "no valid evidence left, finding removed"})
        analysis[section] = good
    analysis["dropped"] = dropped
    return analysis, kept


class Analyzer(BaseAgent):
    agent_id = "A03"
    name = "analyzer"
    title = "Understand it"
    requires = ("repo", "run_id")
    produces = "analysis"
    uses_llm = True

    def run(self, ctx: dict) -> dict:
        repo = ctx["repo"]
        raw = llm.call(stage=self.name, tier="heavy", system=prompt(__file__),
                       user=build_user_prompt(repo), schema=AnalysisOut,
                       mock=mock_output(repo), run_id=ctx["run_id"])
        analysis, kept = ground(raw, repo)
        if kept < MIN_FINDINGS:
            reasons = "; ".join(d["reason"] for d in analysis["dropped"][:5])
            raise AgentError(f"only {kept} grounded finding(s) after the evidence check "
                             f"(need {MIN_FINDINGS}). Dropped: {reasons or 'none'}")
        return analysis
