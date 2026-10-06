"""
[A10] reviser - LLM agent (heavy tier). Conditional: skips when the critic says "pass".

Input : ctx["draft"], ctx["critique"], ctx["strategy"], ctx["profile"], ctx["repo"], ctx["run_id"]
Output: ctx["final_draft"]  {platforms{...}, claims[], changes[], unresolved[], revised[]}
        Only the platforms with block/fix flags are sent back to the model; the others are
        carried over untouched. The packager uses final_draft when present, else draft.

Static checks after the model answers:
  - claims re-checked; at least 1 valid claim must remain
  - the same clean-up and hard limits as the writer
  - a "block" flag whose quote is still in the text, and was not declined with a reason,
    fails the stage (fail-closed: known-wrong text never reaches your review)
  - a "fix" flag still present and not declined goes to unresolved[] for you to see at G2
"""
from __future__ import annotations

import copy
from typing import Literal, Optional

from pydantic import BaseModel, Field

from agents.common import compact, prompt, voice_block
from agents.critic.agent import WHOLE, _norm
from agents.writer.agent import IGCarousel, LinkedInPost, TikTokScript, XThread, tidy
from core import llm
from core import platforms as P
from core.base_agent import AgentError, BaseAgent, SkipStage
from core.evidence import validate
from core.schemas import Evidence


class Change(BaseModel):
    platform: str
    quote: str
    action: Literal["applied", "declined"]
    note: str = Field(min_length=3)


class Revision(BaseModel):
    linkedin: Optional[LinkedInPost] = None
    x: Optional[XThread] = None
    instagram: Optional[IGCarousel] = None
    tiktok: Optional[TikTokScript] = None
    claims: list[Evidence] = Field(min_length=1)
    changes: list[Change] = Field(default_factory=list)


def build_user_prompt(draft: dict, flags: list[dict], targets: list[str], profile: dict) -> str:
    return "\n".join([
        f"REVISE THESE PLATFORMS (return each one complete): {', '.join(targets)}",
        "",
        "CURRENT DRAFTS (JSON):",
        compact({p: draft["platforms"][p] for p in targets}),
        "",
        "FLAGS (fix every block and fix; nits are optional):",
        *[f"{i}. [{f['platform']}] [{f['severity']}] \"{f['quote']}\" - {f['issue']} -> {f['suggestion']}"
          for i, f in enumerate(flags, 1)],
        "",
        "AUTHOR VOICE (keep it):", voice_block(profile),
        "",
        "CLAIMS (the only evidence you may cite):",
        compact(draft["claims"]),
        "",
        "Return the revision as JSON matching the schema.",
    ])


def mock_output(draft: dict, flags: list[dict], targets: list[str]) -> dict:
    out = {"claims": draft["claims"], "changes": []}
    for p in targets:
        d = copy.deepcopy(draft["platforms"][p])
        for f in flags:
            if f["platform"] != p or f["severity"] == "nit" or f["quote"] == WHOLE:
                continue
            if p == "linkedin":
                d["text"] = d["text"].replace(f["quote"], "Mock revised line.")
            elif p == "x":
                d["tweets"] = [t.replace(f["quote"], "Mock revised.") for t in d["tweets"]]
            elif p == "instagram":
                d["caption"] = d["caption"].replace(f["quote"], "Mock revised.")
                for s in d["slides"]:
                    s["title"], s["body"] = s["title"].replace(f["quote"], "Mock"), s["body"].replace(f["quote"], "Mock")
            elif p == "tiktok":
                d["caption"] = d["caption"].replace(f["quote"], "Mock revised.")
                for s in d["scenes"]:
                    s["voiceover"] = s["voiceover"].replace(f["quote"], "Mock revised.")
                    s["on_screen"] = s["on_screen"].replace(f["quote"], "Mock")
            out["changes"].append({"platform": p, "quote": f["quote"], "action": "applied", "note": "Mock: applied."})
        out[p] = d
    return out


def unresolved_flags(platforms: dict, flags: list[dict], changes: list[dict]) -> tuple[list[dict], list[dict]]:
    declined = {(c["platform"], _norm(c["quote"])) for c in changes if c["action"] == "declined"}
    blocking, unresolved = [], []
    for f in flags:
        p, q = f["platform"], _norm(f["quote"])
        body = _norm(P.draft_text(p, platforms.get(p)))
        if f["severity"] == "nit" or f["quote"] == WHOLE or (p, q) in declined or q not in body:
            continue
        (blocking if f["severity"] == "block" else unresolved).append(
            {"platform": p, "severity": f["severity"], "quote": f["quote"], "issue": f["issue"]})
    return blocking, unresolved


class Reviser(BaseAgent):
    agent_id = "A10"
    name = "reviser"
    title = "Fix what was flagged"
    requires = ("profile", "repo", "run_id")
    produces = "final_draft"
    uses_llm = True

    def run(self, ctx: dict) -> dict:
        critique, draft = ctx.get("critique"), ctx.get("draft")
        if not draft or not critique:
            raise SkipStage("nothing written")
        if critique["verdict"] == "pass":
            raise SkipStage("critic verdict is pass, nothing to revise")
        flags = [f for f in critique["flags"] if f["platform"] in draft["platforms"]]
        targets = [p for p in draft["platforms"] if any(f["platform"] == p and f["severity"] != "nit" for f in flags)]
        r = llm.call(stage=self.name, tier="heavy", system=prompt(__file__),
                     user=build_user_prompt(draft, [f for f in flags if f["platform"] in targets], targets, ctx["profile"]),
                     schema=Revision, mock=mock_output(draft, flags, targets), run_id=ctx["run_id"])
        check = validate(r["claims"], ctx["repo"])
        if not check["valid"]:
            raise AgentError("revision has no valid claims: " + check["invalid"][0]["reason"])
        platforms = copy.deepcopy(draft["platforms"])
        revised = []
        for p in targets:
            if r.get(p):
                platforms[p], _ = tidy(p, r[p], ctx["strategy"]["plans"][p])
                revised.append(p)
        blocking, unresolved = unresolved_flags(platforms, flags, r["changes"])
        if blocking:
            raise AgentError(f"{len(blocking)} block flag(s) still in the text: "
                             + "; ".join(f'[{b["platform"]}] "{b["quote"][:50]}"' for b in blocking))
        return {"platforms": platforms, "claims": check["valid"], "changes": r["changes"],
                "unresolved": unresolved, "revised": revised,
                "claims_dropped": [i["reason"] for i in check["invalid"]]}
