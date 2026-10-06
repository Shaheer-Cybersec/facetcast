"""
[A09] critic - static pre-pass + LLM review (mid tier), per platform.

Input : ctx["draft"], ctx["strategy"], ctx["profile"], ctx["run_id"]
Output: ctx["critique"]  {verdict, flags[{platform, severity, quote, issue, suggestion, source}],
                         scores{platform: {hook, clarity, accuracy, voice, native}}, dropped[]}
        verdict "revise" if any block/fix flag exists, else "pass" (the reviser then skips)

Static pre-pass (code, no LLM), runs first and is passed to the model:
  - AI-tell phrases, leftover markdown, emoji against the author's voice
  - links where the platform punishes or breaks them (LinkedIn body, Instagram caption)
  - hook past the fold (LinkedIn ~210, Instagram caption 125), tweet length, hashtag count
  - the writer's notes (slide count, voiceover too long, unbacked wording...)
After the model answers: a flag whose quote is not in that platform's text is dropped
(the model cannot critique words that are not there).
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from agents.common import compact, prompt, voice_block
from core import llm
from core import platforms as P
from core.base_agent import BaseAgent, SkipStage

AI_TELLS = ("delve", "game-changer", "game changer", "in today's", "let's dive", "dive in",
            "unlock the", "leverage", "here's the thing", "in the ever", "landscape of",
            "it's important to note", "seamless", "robust solution", "elevate your", "navigate the",
            "embark on", "a testament to", "tapestry", "revolutionize", "supercharge")
MD_RE = re.compile(r"\*\*|__|```|^#{1,6}\s", re.M)
WHOLE = "(whole post)"


class Flag(BaseModel):
    platform: str = Field(min_length=1, max_length=20)
    severity: Literal["block", "fix", "nit"]
    quote: str = Field(min_length=1, max_length=240)
    issue: str = Field(min_length=5)
    suggestion: str = Field(min_length=3)


class Scores(BaseModel):
    hook: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    accuracy: int = Field(ge=1, le=5)
    voice: int = Field(ge=1, le=5)
    native: int = Field(ge=1, le=5, description="does it feel made for this platform")


class Critique(BaseModel):
    flags: list[Flag] = Field(default_factory=list, max_length=30)
    scores: dict[str, Scores]


def static_flags(platform: str, d: dict, notes: list[str], voice: dict) -> list[dict]:
    flags, spec = [], P.SPECS[platform]
    text = P.draft_text(platform, d)

    def add(sev, quote, issue, suggestion):
        flags.append({"platform": platform, "severity": sev, "quote": quote, "issue": issue,
                      "suggestion": suggestion, "source": "static"})

    low = text.lower()
    for phrase in AI_TELLS:
        i = low.find(phrase)
        if i >= 0:
            add("fix", text[i:i + len(phrase)], f"AI-tell phrase '{phrase}'", "say it plainly, in the author's words")
    emojis = sorted(set(P.EMOJI_RE.findall(text)))
    emoji_pref = (voice or {}).get("emoji", "none")
    if emojis and emoji_pref == "none":
        for e in emojis:
            add("fix", e, "emoji, but the author never uses them", "remove it")
    elif emojis and platform == "linkedin" and P.headline_of(platform, d) and \
            P.EMOJI_RE.search(P.headline_of(platform, d)):
        add("nit", P.headline_of(platform, d)[:80], "emoji in the LinkedIn hook line", "keep the first line plain")
    for m in MD_RE.finditer(text):
        add("fix", m.group(0).strip() or m.group(0), "markdown the platform will not render", "remove it")
    if not spec.get("links_in_body", True):
        for link in P.URL_RE.findall(text):
            where = "first comment" if platform == "linkedin" else "bio / 'link in bio'"
            add("fix", link, f"link in the {spec['label']} text", f"move it to the {where}")
    if platform == "linkedin":
        first = d["text"].split("\n\n")[0]
        if len(first) > spec["fold"]:
            add("fix", first[:120], f"opening is {len(first)} chars, past the ~{spec['fold']} char fold",
                "cut the opening to one or two short lines")
    if platform == "instagram":
        cap = d.get("caption", "")
        first = cap.split("\n")[0]
        if len(first) > spec["fold"] + 60:
            add("nit", first[:100], f"caption opening runs past the {spec['fold']}-char preview", "front-load the hook")
    if platform == "x":
        for i, t in enumerate(d.get("tweets") or [], 1):
            if P.x_len(t) > spec["tweet_max"]:
                add("fix", t[:120], f"tweet {i} is {P.x_len(t)} chars (max {spec['tweet_max']})", "split or cut it")
    tags = P.HASHTAG_RE.findall(text)
    if len(tags) > spec["hashtags"][1]:
        add("nit", " ".join(tags[:8]), f"{len(tags)} hashtags on {spec['label']}", f"keep {spec['hashtags'][1]} or fewer")
    for n in notes:
        if n.startswith("absolute wording"):
            q = re.search(r'"([^"]+)"', n)
            add("nit", q.group(1) if q else WHOLE, f"writer note: {n}", "keep it only if the evidence supports it")
        elif n.startswith("tweet ") and "over" in n:
            continue                                   # already flagged above with a quote
        else:
            q = re.search(r'"([^"]+)"', n)
            add("fix", q.group(1) if q and q.group(1).lower() in low else WHOLE, f"writer note: {n}",
                "address it in the revision")
    return flags


def build_user_prompt(draft: dict, strategy: dict, profile: dict, sflags: list[dict]) -> str:
    posts = []
    for p, d in draft["platforms"].items():
        posts += [f"=== {p.upper()} ===", "<<<", P.draft_text(p, d), ">>>"]
        if p == "tiktok":
            posts.append("scene visuals: " + " | ".join(f"{s['seconds']}s {s['visual']}" for s in d["scenes"]))
    return "\n".join([
        *posts, "",
        "PLANS:", compact({p: {k: v for k, v in pl.items() if k in ("format", "hook", "beats", "cta")}
                           for p, pl in strategy["plans"].items()}),
        "",
        "AUTHOR VOICE (the content must sound like this):", voice_block(profile),
        "",
        "CLAIMS (all the content may state about the project):",
        *[f"- {c['claim']}  [{c['source_path']} @ {c['source_ref']}]" for c in draft["claims"]],
        "",
        "STATIC FLAGS (already found by code, do not repeat):",
        *([f"- [{f['platform']}] {f['severity']}: {f['issue']}" for f in sflags] or ["(none)"]),
        "",
        f"Score every platform present: {', '.join(draft['platforms'])}.",
        "Return the critique as JSON matching the schema.",
    ])


def mock_output(draft: dict) -> dict:
    p = next(iter(draft["platforms"]))
    first = P.headline_of(p, draft["platforms"][p])[:60] or "x"
    return {"flags": [{"platform": p, "severity": "nit", "quote": first, "issue": "Mock: hook could be sharper.",
                       "suggestion": "Mock: lead with the result."}],
            "scores": {q: {"hook": 4, "clarity": 4, "accuracy": 5, "voice": 4, "native": 4} for q in draft["platforms"]}}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("’", "'").replace("“", '"').replace("”", '"')).strip()


def quote_in(platform: str, quote: str, draft: dict) -> bool:
    return quote == WHOLE or _norm(quote) in _norm(P.draft_text(platform, draft["platforms"].get(platform)))


class Critic(BaseAgent):
    agent_id = "A09"
    name = "critic"
    title = "Critique it"
    requires = ("profile", "run_id")
    produces = "critique"
    uses_llm = True

    def run(self, ctx: dict) -> dict:
        draft = ctx.get("draft")
        if not draft:
            raise SkipStage("nothing written to critique")
        voice = (ctx["profile"] or {}).get("voice") or {}
        notes = draft.get("notes") or {}
        sflags = [f for p, d in draft["platforms"].items()
                  for f in static_flags(p, d, notes.get(p, []), voice)]
        c = llm.call(stage=self.name, tier="mid", system=prompt(__file__),
                     user=build_user_prompt(draft, ctx["strategy"], ctx["profile"], sflags),
                     schema=Critique, mock=mock_output(draft), run_id=ctx["run_id"])
        kept, dropped = [], []
        for f in c["flags"]:
            f["platform"] = (P.normalize([f["platform"]]) or [f["platform"]])[0]
            if f["platform"] in draft["platforms"] and quote_in(f["platform"], f["quote"], draft):
                kept.append({**f, "source": "model"})
            else:
                dropped.append({"platform": f["platform"], "quote": f["quote"], "reason": "quote not found in that platform's text"})
        order = {"block": 0, "fix": 1, "nit": 2}
        flags = sorted(sflags + kept, key=lambda f: (order[f["severity"]], f["platform"]))
        verdict = "revise" if any(f["severity"] in ("block", "fix") for f in flags) else "pass"
        scores = {p: s for p, s in c["scores"].items() if p in draft["platforms"]}
        return {"verdict": verdict, "flags": flags, "scores": scores, "dropped": dropped}
