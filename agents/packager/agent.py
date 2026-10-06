"""
[A12] packager - static agent (no LLM). Last check, then the kit. Runs before your approval.

Input : ctx["repo"], ctx["run_id"], ctx["platforms"], ctx["final_draft"] or ctx["draft"],
        ctx["showcase"], ctx["visual_plan"], ctx["profile"]
Output: ctx["package"]  {folder, pdf, files[], images[], platforms[], warnings[], stats{}, evidence_checked}
        and the kit folder outputs/<project>/<date>_<run>/ (built by core/report.py)

Hard stops (the run fails, no kit is written):
  - ANY evidence item that fails the check (fail-closed: content citing an invented file
    or commit is never packaged, even if the critic missed it)
  - LinkedIn over 3,000 chars, any tweet over 280, Instagram caption over 2,200
  - nothing to package
Soft warnings (packaged, shown at the top of the kit and in the dashboard):
  - links where the platform punishes them, too many hashtags, unresolved critic flags,
    slide or duration outside the sweet spot
"""
from __future__ import annotations

from config.settings import OUTPUTS_DIR
from core import platforms as P
from core.base_agent import AgentError, BaseAgent
from core.evidence import validate
from core.report import build_kit, final_platforms, run_folder


def stats(platform: str, d: dict) -> dict:
    text = P.draft_text(platform, d)
    out = {"chars": len(text), "words": len(text.split()), "hashtags": len(P.HASHTAG_RE.findall(text)),
           "links": len(P.URL_RE.findall(text))}
    if platform == "x":
        out["tweets"] = len(d["tweets"])
        out["longest_tweet"] = max(P.x_len(t) for t in d["tweets"])
    if platform == "instagram":
        out["slides"] = len(d["slides"])
        out["caption_chars"] = len(d["caption"])
    if platform == "tiktok":
        out["seconds"] = d["duration_s"]
        out["voiceover_words"] = P.voiceover_words(d)
    if platform == "linkedin":
        out["chars"] = len(d["text"])
    return out


def hard_checks(platform: str, d: dict) -> list[str]:
    s, errs = P.SPECS[platform], []
    if platform == "linkedin" and len(d["text"]) > s["max_chars"]:
        errs.append(f"LinkedIn post is {len(d['text'])} chars (max {s['max_chars']})")
    if platform == "x":
        errs += [f"tweet {i} is {P.x_len(t)} chars (max {s['tweet_max']})"
                 for i, t in enumerate(d["tweets"], 1) if P.x_len(t) > s["tweet_max"]]
    if platform == "instagram" and len(d["caption"]) > s["max_chars"]:
        errs.append(f"Instagram caption is {len(d['caption'])} chars (max {s['max_chars']})")
    if platform == "tiktok" and len(d["caption"]) > s["max_chars"]:
        errs.append(f"TikTok caption is {len(d['caption'])} chars (max {s['max_chars']})")
    return errs


def soft_checks(platform: str, d: dict, st: dict) -> list[str]:
    s, w = P.SPECS[platform], []
    label = s["label"]
    if st["links"] and not s.get("links_in_body", True):
        w.append(f"{label}: {st['links']} link(s) in the text. Move them to the first comment / bio.")
    if st["hashtags"] > s["hashtags"][1]:
        w.append(f"{label}: {st['hashtags']} hashtags (keep {s['hashtags'][1]} or fewer).")
    if platform == "instagram" and not s["slides"][0] <= st["slides"] <= s["slides"][1]:
        w.append(f"{label}: {st['slides']} slides (sweet spot {s['slides'][0]}-{s['slides'][1]}).")
    if platform == "tiktok" and not s["duration"][0] <= st["seconds"] <= s["duration"][1]:
        w.append(f"{label}: {st['seconds']}s video (sweet spot {s['duration'][0]}-{s['duration'][1]}s).")
    return w


class Packager(BaseAgent):
    agent_id = "A12"
    name = "packager"
    title = "Package the kit"
    requires = ("repo", "run_id")
    produces = "package"
    uses_llm = False

    def run(self, ctx: dict) -> dict:
        drafts = final_platforms(ctx)
        showcase = ctx.get("showcase")
        if not drafts and not showcase:
            raise AgentError("nothing to package: no platform content and no GitHub kit")
        errs, warnings, st = [], [], {}
        for p, d in drafts.items():
            errs += hard_checks(p, d)
            st[p] = stats(p, d)
            warnings += soft_checks(p, d, st[p])
        if errs:
            raise AgentError("; ".join(errs))
        claims = list((ctx.get("final_draft") or ctx.get("draft") or {}).get("claims") or [])
        claims += list((showcase or {}).get("claims") or [])
        check = validate(claims, ctx["repo"])
        if not check["ok"]:
            raise AgentError(f"{len(check['invalid'])} evidence item(s) failed: "
                             + "; ".join(i["reason"] for i in check["invalid"][:4]))
        for u in (ctx.get("final_draft") or {}).get("unresolved") or []:
            warnings.append(f"{P.label(u['platform'])}: unresolved critic flag on \"{u['quote'][:60]}\" - {u['issue']}")
        folder = run_folder(OUTPUTS_DIR, ctx["repo"], ctx["run_id"])
        built = build_kit(dict(ctx, package={"warnings": warnings}), folder, records=ctx.get("_records"))
        warnings += built["skipped"]
        return {"folder": built["folder"], "pdf": built["pdf"], "files": built["files"], "images": built["images"],
                "platforms": [p for p in P.normalize(ctx.get("platforms") or []) if p in drafts or (p == "github" and showcase)],
                "theme": built["theme"], "warnings": warnings, "stats": st, "evidence_checked": len(claims)}
