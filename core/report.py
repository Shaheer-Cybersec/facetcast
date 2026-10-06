"""
report - the finished kit for one run. Pure code, no LLM.

    outputs/<project>/<date>_<run>/
        00_START_HERE.md       what is here + how to post, per platform
        00_REPORT.pdf          everything in one visual PDF (previews, kits, evidence, how it was made)
        index.html             offline studio page: every platform, Copy buttons, all images
        linkedin/   post.md  first_comment.md  alt_text.md  graphic.png
        x/          thread.md  alt_text.md  card.png
        instagram/  caption.md  slides.md  alt_text.md  slide-01.png ... slide-NN.png
        tiktok/     script.md  caption.md  cover.png
        github/     README.suggested.md  repo-settings.md  checklist.md  case-study.md  pitch.md  social-preview.png
        visuals.md  evidence.md  voice-profile.md  run-summary.md  manifest.json

Only the platforms picked at G1 get a folder. Images need Pillow, the PDF needs reportlab;
without them everything else is still written and manifest.json says what was skipped.
"""
from __future__ import annotations

import io
import json
import re
from datetime import datetime
from html import escape as hesc
from pathlib import Path
from xml.sax.saxutils import escape as xesc

from config import settings
from core import graphics as G
from core import platforms as P

STAGES = [  # (tag, name, title, who)
    ("A01", "ingest", "Read the project", "code"), ("A02", "recall", "Check past posts", "code"),
    ("A03", "analyzer", "Understand it", "ai"), ("A04", "profiler", "Learn the voice", "ai"),
    ("A05", "angles", "Find the angles", "ai"), ("G1", "pick", "You pick", "you"),
    ("A06", "strategist", "Plan each platform", "ai"), ("A07", "visuals", "Plan the visuals", "ai"),
    ("A08", "writer", "Write every platform", "ai"), ("A09", "critic", "Critique it", "ai"),
    ("A10", "reviser", "Fix what was flagged", "ai"), ("A11", "showcase", "GitHub & portfolio kit", "ai"),
    ("A12", "packager", "Package the kit", "code"), ("G2", "approve", "You approve", "you"),
    ("A13", "archive", "Remember it", "code"),
]


# ---------------------------------------------------------------- names

def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name or "").strip("-.") or "project"


def run_folder(outputs_dir, repo: dict, run_id: str, date: str | None = None) -> Path:
    date = date or f"{datetime.now():%Y-%m-%d}"
    return Path(outputs_dir) / safe(repo.get("repo", "")) / f"{date}_{safe(run_id)}"


def brand_for(repo: dict) -> dict:
    owner = repo.get("owner") or ""
    hosted = owner not in ("local", "remote", "") and (repo.get("url") or "").startswith("https://")
    host = repo.get("host") or "github.com"
    handle = settings.AUTHOR_HANDLE or (f"@{owner}" if hosted else "")
    return {"project": repo.get("repo") or "", "handle": handle, "name": settings.AUTHOR_NAME or (owner if hosted else ""),
            "headline": settings.AUTHOR_HEADLINE,
            "url": (repo.get("url") or "") if hosted else "",
            "url_short": f"{host}/{owner}/{repo.get('repo')}" if hosted else "",
            "owner_label": f"{owner} /" if hosted else ""}


# ---------------------------------------------------------------- model

def final_platforms(ctx: dict) -> dict:
    return ((ctx.get("final_draft") or ctx.get("draft") or {}).get("platforms")) or {}


def collect(ctx: dict, records: dict | None = None, date: str | None = None, theme: str | None = None) -> dict:
    repo = ctx["repo"]
    profile = ctx.get("profile") or {}
    drafts = final_platforms(ctx)
    fd = ctx.get("final_draft") or ctx.get("draft") or {}
    showcase = ctx.get("showcase")
    chosen = P.normalize(ctx.get("platforms") or list(drafts))
    platforms = [p for p in chosen if p in drafts or (p == "github" and showcase)]
    vp = ctx.get("visual_plan") or {}
    strategy = ctx.get("strategy") or {}
    th = (profile.get("theme") or {})
    theme_name = theme or ctx.get("theme_override") or th.get("name") or "midnight"
    accent = th.get("accent") if theme_name == th.get("name") else None
    claims = list(fd.get("claims") or [])
    if showcase:
        claims += [c for c in showcase.get("claims", []) if c not in claims]
    angle = ctx.get("chosen_angle") or {}
    graphic = vp.get("graphic") or {"style": "headline",
                                    "headline": (strategy.get("core_message") or angle.get("title") or repo.get("repo", ""))[:100],
                                    "subline": None, "stat": None}
    recs = records or ctx.get("_records") or {}
    pipeline = []
    for tag, _name, title, who in STAGES:
        r = recs.get(tag) or {}
        if tag.startswith("G"):
            done = (tag == "G1" and "chosen_angle" in ctx) or (tag == "G2" and "approved" in ctx)
            pipeline.append({"tag": tag, "name": title, "who": who, "status": "you" if done else "pending", "secs": None})
        else:
            st = r.get("status") or ("success" if tag == "A12" else "pending")
            pipeline.append({"tag": tag, "name": title, "who": who, "status": st,
                             "secs": (r["duration_ms"] / 1000) if r.get("duration_ms") is not None else None})
    crit = ctx.get("critique") or {}
    return {
        "repo": repo, "project": repo.get("repo", ""), "run_id": ctx["run_id"],
        "date": date or f"{datetime.now():%Y-%m-%d}", "brand": brand_for(repo),
        "title": angle.get("title") or "GitHub & portfolio kit", "angle": angle,
        "angles": (ctx.get("angle_set") or {}).get("angles") or [],
        "recommendation": (ctx.get("angle_set") or {}).get("recommendation"),
        "analysis": ctx.get("analysis") or {}, "profile": profile, "strategy": strategy,
        "platforms": platforms, "drafts": drafts, "showcase": showcase, "claims": claims,
        "visual_plan": vp, "graphic": graphic, "theme": theme_name, "accent": accent,
        "scores": crit.get("scores") or {}, "flags": crit.get("flags") or [],
        "changes": (ctx.get("final_draft") or {}).get("changes") or [],
        "unresolved": (ctx.get("final_draft") or {}).get("unresolved") or [],
        "pipeline": pipeline, "total_secs": sum(p["secs"] for p in pipeline if p["secs"]),
        "warnings": (ctx.get("package") or {}).get("warnings") or [],
        "revised": (ctx.get("final_draft") or {}).get("revised") or [],
    }


# ---------------------------------------------------------------- text kits

def first_comment(m: dict) -> str:
    d = m["drafts"].get("linkedin") or {}
    if d.get("first_comment"):
        return d["first_comment"].strip()
    url = m["brand"]["url"]
    lines = [f"The project: {url}"] if url else []
    files = list(dict.fromkeys(c["source_path"] for c in m["claims"]))[:3]
    if files:
        lines.append("Details are in " + ", ".join(files) + ".")
    return "\n".join(lines) or "Questions welcome - happy to share more about how this was made."


def alt_text(m: dict) -> str:
    g = m["graphic"]
    return (f"Graphic with the text: {g.get('headline', '')}" + (f". {g['subline']}" if g.get("subline") else ""))[:1000]


def kits(m: dict) -> dict:
    """Every paste-ready block, per platform."""
    out = {}
    d = m["drafts"]
    if "linkedin" in d:
        out["linkedin"] = {"post": d["linkedin"]["text"], "first_comment": first_comment(m), "alt_text": alt_text(m)}
    if "x" in d:
        tw = d["x"]["tweets"]
        out["x"] = {"tweets": tw, "thread": "\n\n---\n\n".join(tw), "alt_text": alt_text(m)}
    if "instagram" in d:
        ig = d["instagram"]
        out["instagram"] = {"caption": ig["caption"], "slides": ig["slides"],
                            "alt_texts": [f"Slide {i}: {s['title']}" + (f". {s['body']}" if s.get("body") else "")
                                          for i, s in enumerate(ig["slides"], 1)]}
    if "tiktok" in d:
        t = d["tiktok"]
        out["tiktok"] = {"hook": t["hook"], "caption": t["caption"], "scenes": t["scenes"], "title": t["title"],
                         "duration_s": t["duration_s"],
                         "voiceover": "\n".join(s["voiceover"] for s in t["scenes"] if s.get("voiceover"))}
    if m["showcase"]:
        s = m["showcase"]
        out["github"] = {"description": s["description"], "topics": s["topics"], "tagline": s["tagline"],
                         "readme": s["readme_draft"], "pitch": s["freelance_pitch"], "pinned": s["pinned_blurb"],
                         "case_study": case_study_md(s), "checklist": s["checklist"]}
    return out


def case_study_md(s: dict) -> str:
    c = s["case_study"]
    stack = ", ".join(c.get("stack") or [])
    return (f"# {c['title']}\n\n**Role:** {c.get('role') or 'Author'}" + (f"  \n**Stack:** {stack}" if stack else "")
            + f"\n\n## The problem\n\n{c['problem']}\n\n## The approach\n\n{c['approach']}\n\n## The outcome\n\n{c['outcome']}\n")


def script_md(t: dict) -> str:
    rows = "\n".join(f"| {i} | {s['seconds']:g}s | {s['visual']} | {s.get('voiceover', '')} | {s.get('on_screen', '')} |"
                     for i, s in enumerate(t["scenes"], 1))
    return (f"# {t['title']}\n\nDuration: about {t['duration_s']}s. Works as TikTok, Instagram Reels and YouTube Shorts.\n\n"
            f"**Hook (on screen, first 2 seconds):** {t['hook']}\n\n"
            f"| # | Time | Visual | Voiceover | On-screen text |\n|---|---|---|---|---|\n{rows}\n\n"
            f"## Voiceover only (read this aloud)\n\n" + "\n\n".join(s["voiceover"] for s in t["scenes"] if s.get("voiceover")) + "\n")


# ---------------------------------------------------------------- images

def images(m: dict) -> tuple[dict[str, bytes], list[str]]:
    """Every PNG for the kit. Returns ({relative path: bytes}, notes)."""
    out, notes = {}, []
    try:
        pal = G.palette(m["theme"], m["accent"])
        b, g = m["brand"], m["graphic"]
        if "linkedin" in m["drafts"]:
            out["linkedin/graphic.png"] = G.card(g, pal, b, G.SIZES["linkedin"])
        if "x" in m["drafts"]:
            out["x/card.png"] = G.card(g, pal, b, G.SIZES["x"])
        if "instagram" in m["drafts"]:
            slides = m["drafts"]["instagram"]["slides"]
            for i, s in enumerate(slides, 1):
                out[f"instagram/slide-{i:02d}.png"] = G.slide(i, len(slides), s, pal, b, G.SIZES["instagram"])
        if "tiktok" in m["drafts"]:
            t = m["drafts"]["tiktok"]
            out["tiktok/cover.png"] = G.cover(t["hook"], t.get("title", ""), pal, b, G.SIZES["tiktok"])
        if m["showcase"]:
            sp = m["showcase"]["social_preview"]
            out["github/social-preview.png"] = G.preview(m["project"], sp["headline"], sp.get("subline") or m["showcase"]["tagline"],
                                                         m["showcase"]["topics"], pal, b, G.SIZES["github"])
    except Exception as e:                                   # Pillow missing or font trouble
        notes.append(f"images skipped ({type(e).__name__}: {e}). Run: pip install pillow")
    return out, notes


# ---------------------------------------------------------------- markdown files

def md_files(m: dict, k: dict) -> dict[str, str]:
    f: dict[str, str] = {}
    if "linkedin" in k:
        f["linkedin/post.md"] = k["linkedin"]["post"].rstrip() + "\n"
        f["linkedin/first_comment.md"] = k["linkedin"]["first_comment"].rstrip() + "\n"
        f["linkedin/alt_text.md"] = k["linkedin"]["alt_text"] + "\n"
    if "x" in k:
        f["x/thread.md"] = "\n\n---\n\n".join(f"{t}" for t in k["x"]["tweets"]) + "\n"
        f["x/alt_text.md"] = k["x"]["alt_text"] + "\n"
    if "instagram" in k:
        ig = k["instagram"]
        f["instagram/caption.md"] = ig["caption"].rstrip() + "\n"
        f["instagram/slides.md"] = "\n\n".join(f"## Slide {i}\n\n**{s['title']}**\n\n{s.get('body', '')}"
                                              for i, s in enumerate(ig["slides"], 1)) + "\n"
        f["instagram/alt_text.md"] = "\n".join(ig["alt_texts"]) + "\n"
    if "tiktok" in k:
        f["tiktok/script.md"] = script_md(m["drafts"]["tiktok"])
        f["tiktok/caption.md"] = k["tiktok"]["caption"].rstrip() + "\n"
    if "github" in k:
        g, s = k["github"], m["showcase"]
        f["github/README.suggested.md"] = g["readme"].rstrip() + "\n"
        f["github/repo-settings.md"] = (
            f"# Repository settings\n\n## About -> Description\n\n```text\n{g['description']}\n```\n\n"
            f"## About -> Topics\n\n```text\n{' '.join(g['topics'])}\n```\n\n## Tagline (top of the README)\n\n{g['tagline']}\n\n"
            f"## Pinned / portfolio grid blurb\n\n{g['pinned']}\n\n## Social preview\n\nSettings -> General -> Social preview -> upload `social-preview.png`.\n"
            + ("\n## Notes\n\n" + "\n".join(f"- {n}" for n in s.get("notes", [])) + "\n" if s.get("notes") else ""))
        f["github/checklist.md"] = (f"# README checklist (score {s.get('readme_score', '-')}/100)\n\n" + "\n".join(
            f"- [{'x' if c['status'] == 'ok' else ' '}] **{c['item']}** ({c['status']})" + (f": {c['fix']}" if c.get("fix") else "")
            for c in g["checklist"]) + "\n")
        f["github/case-study.md"] = g["case_study"]
        f["github/pitch.md"] = g["pitch"].rstrip() + "\n"

    vp = m["visual_plan"]
    shots = "\n".join(f"- [ ] **{x['shot']}** ({x['kind']}, ~{x['minutes']} min"
                      + (f", {', '.join(P.label(p) for p in x['platforms'])}" if x.get("platforms") else "") + ")"
                      + (f" `{x['file_path']}{' ' + x['lines'] if x.get('lines') else ''}`" if x.get("file_path") else "")
                      + f"\n  {x['how']}" for x in vp.get("shots") or []) or "- (none planned)"
    reuse = "\n".join(f"- `{r['file_path']}`: {r['use']}" for r in vp.get("reuse") or []) or "- (none)"
    prompts = "\n\n".join(f"### {P.label(p.get('platform', ''))} - {p['tool']}\n\n```text\n{p['prompt']}\n```"
                          for p in vp.get("image_prompts") or []) or "(none)"
    f["visuals.md"] = (f"# Visuals\n\nTheme: **{m['theme']}**. Every graphic in this folder was drawn from it; "
                       f"switch themes in the dashboard to redraw them.\n\n## Capture these\n\n{shots}\n\n"
                       f"## Reuse images already in the project\n\n{reuse}\n\n## Prompts for image tools\n\n{prompts}\n"
                       + (f"\nWhy: {vp['rationale']}\n" if vp.get("rationale") else ""))
    ref = (m["repo"].get("head_sha") or "")[:12]
    rows = "\n".join(f"| {c['claim']} | `{c['source_path']}` | `{c['source_ref']}` |" for c in m["claims"]) or "| (none) | | |"
    f["evidence.md"] = (f"# Evidence\n\nEvery factual claim in this kit is bound to a file in the project at `{ref}`. "
                        f"Facetcast refuses to package content that cites a file or commit that does not exist.\n\n"
                        f"| Claim | File | Ref |\n|---|---|---|\n{rows}\n")
    pr = m["profile"]
    v = pr.get("voice") or {}
    f["voice-profile.md"] = (
        f"# Voice profile\n\nRead from: {pr.get('voice_source', 'README')}"
        + (" + your own past posts" if pr.get("user_voice_used") else "") + "\n\n"
        f"- Person: {v.get('person')}\n- Tone: {', '.join(v.get('tone') or [])}\n- Formality {v.get('formality')}/5, "
        f"energy {v.get('energy')}/5, humor {v.get('humor')}, emoji {v.get('emoji')}\n- Sentences: {v.get('sentence_style')}\n"
        f"- Vocabulary: {v.get('vocabulary')}\n"
        + (f"- Signature phrases: {' | '.join(v.get('signature_phrases') or [])}\n" if v.get("signature_phrases") else "")
        + f"\n**Positioning:** {pr.get('positioning', '')}\n\n## Audiences\n\n"
        + "\n".join(f"- **{a['name']}**: {a['cares_about']}" for a in pr.get("audiences") or [])
        + "\n\n## Where this project lands\n\n| Platform | Fit | Why |\n|---|---|---|\n"
        + "\n".join(f"| {P.label(p)} | {round((x or {}).get('score', 0) * 100)}% | {(x or {}).get('why', '')} |"
                    for p, x in (pr.get("platform_fit") or {}).items()) + "\n")
    ang = "\n".join(f"| {'**' + a['title'] + '**' if a['title'] == m['title'] else a['title']} | {round(a.get('score', 0) * 100)}% | "
                    f"{', '.join(P.label(p) for p in a.get('best_platforms') or [])} | {a.get('dedup_status', '')} |"
                    for a in m["angles"]) or "| | | | |"
    sc = "\n".join(f"| {P.label(p)} | " + " | ".join(str(s.get(k, '-')) for k in ("hook", "clarity", "accuracy", "voice", "native")) + " |"
                   for p, s in m["scores"].items()) or "| - | | | | | |"
    pl = "\n".join(f"| {p['tag']} | {p['name']} | {p['status']} | " + ("" if p["secs"] is None else f"{p['secs']:.1f}s") + " |"
                   for p in m["pipeline"])
    f["run-summary.md"] = (
        f"# Run summary\n\n## Angles considered\n\n| Angle | Confidence | Best on | Dedup |\n|---|---|---|---|\n{ang}\n\n"
        + (f"Recommended: {m['recommendation']['title']}. {m['recommendation'].get('reason') or ''}\n\n" if m.get("recommendation") else "")
        + f"## Critic scores (1-5)\n\n| Platform | Hook | Clarity | Accuracy | Voice | Native |\n|---|---|---|---|---|---|\n{sc}\n\n"
        + f"## Pipeline\n\n| Stage | Agent | Status | Time |\n|---|---|---|---|\n{pl}\n")

    lines = [f"# {m['title']}", "", f"- Project: {m['repo'].get('url', '')} @ `{ref}`",
             f"- Run `{m['run_id']}` on {m['date']} - theme **{m['theme']}**",
             f"- Core message: {m['strategy'].get('core_message', '-')}", ""]
    if m["warnings"]:
        lines += ["## Warnings", "", *[f"- {w}" for w in m["warnings"]], ""]
    lines += ["Open `index.html` for a one-page studio with Copy buttons, or `00_REPORT.pdf` for everything at a glance.", ""]
    for p in m["platforms"]:
        lines += [f"## {P.label(p)}", "", *[f"{i}. {s}" for i, s in enumerate(P.SPECS[p]["steps"], 1)],
                  "", "Files: " + ", ".join(f"`{x}`" for x in sorted(f) if x.startswith(p + "/")), ""]
    f["00_START_HERE.md"] = "\n".join(lines)
    return f


# ---------------------------------------------------------------- index.html (offline studio)

def _copy_block(i: int, title: str, sub: str, body: str) -> str:
    return (f'<section class="blk"><div class="h"><div><h3>{hesc(title)}</h3><span>{hesc(sub)}</span></div>'
            f'<button onclick="cp({i},this)">Copy</button></div><pre id="b{i}">{hesc(body)}</pre></section>')


def html_page(m: dict, k: dict, imgs: dict) -> str:
    pal = G.palette(m["theme"], m["accent"])
    tabs, panes, n = [], [], 0
    for p in m["platforms"]:
        blocks = []
        if p == "linkedin":
            blocks = [("Post", "paste as the post text", k[p]["post"]), ("First comment", "post it right after publishing", k[p]["first_comment"]),
                      ("Image alt text", "paste into the image's alt text", k[p]["alt_text"])]
            media = '<img src="linkedin/graphic.png" alt="">' if "linkedin/graphic.png" in imgs else ""
        elif p == "x":
            blocks = [(f"Tweet {i}", f"{P.x_len(t)}/280", t) for i, t in enumerate(k[p]["tweets"], 1)]
            media = '<img src="x/card.png" alt="">' if "x/card.png" in imgs else ""
        elif p == "instagram":
            blocks = [("Caption", "paste as the caption", k[p]["caption"]), ("Alt text", "one line per slide", "\n".join(k[p]["alt_texts"]))]
            media = '<div class="grid">' + "".join(f'<img src="{x}" alt="">' for x in sorted(imgs) if x.startswith("instagram/")) + "</div>"
        elif p == "tiktok":
            blocks = [("Voiceover", "read this aloud", k[p]["voiceover"]), ("Caption", "paste as the caption", k[p]["caption"])]
            rows = "".join(f"<tr><td>{s['seconds']:g}s</td><td>{hesc(s['visual'])}</td><td>{hesc(s.get('voiceover', ''))}</td><td>{hesc(s.get('on_screen', ''))}</td></tr>"
                           for s in k[p]["scenes"])
            media = (('<img class="tall" src="tiktok/cover.png" alt="">' if "tiktok/cover.png" in imgs else "")
                     + f'<table><tr><th>Time</th><th>Visual</th><th>Voiceover</th><th>On screen</th></tr>{rows}</table>')
        else:
            g = k["github"]
            blocks = [("Description", "repo About -> Description", g["description"]), ("Topics", "repo About -> Topics", " ".join(g["topics"])),
                      ("README draft", "merge into your README", g["readme"]), ("Case study", "portfolio / Upwork / Fiverr", g["case_study"]),
                      ("Freelance pitch", "paste into proposals", g["pitch"])]
            media = '<img src="github/social-preview.png" alt="">' if "github/social-preview.png" in imgs else ""
        body = "".join(_copy_block(n + i, *b) for i, b in enumerate(blocks))
        n += len(blocks)
        steps = "".join(f"<li>{hesc(s)}</li>" for s in P.SPECS[p]["steps"])
        tabs.append(f'<button class="tab" data-t="{p}">{hesc(P.label(p))}</button>')
        panes.append(f'<div class="pane" id="p-{p}"><div class="media">{media}</div><section class="blk"><h3>How to post</h3><ol>{steps}</ol></section>{body}</div>')
    dark = pal["dark"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{hesc(m['project'])} · Facetcast kit</title><style>
:root{{--bg:{'#0d1117' if dark else '#f6f7f9'};--card:{'#161b22' if dark else '#ffffff'};--line:{'#2a313c' if dark else '#e3e6ea'};--text:{'#e6edf3' if dark else '#1b1f24'};--muted:{'#8b949e' if dark else '#5d6670'};--acc:{pal['accent']};--on:{pal['on_accent']}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 Inter,"Segoe UI",system-ui,sans-serif}}
main{{max-width:980px;margin:0 auto;padding:28px 16px 70px}}h1{{font-size:24px;margin:0 0 4px}}.meta{{color:var(--muted);font-size:13px}}
.core{{margin:16px 0;padding:14px 16px;border-left:4px solid var(--acc);background:var(--card);border-radius:8px}}
.tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}}.tab{{background:var(--card);color:var(--text);border:1px solid var(--line);border-radius:999px;padding:8px 16px;font:600 14px inherit;cursor:pointer}}
.tab.on{{background:var(--acc);color:var(--on);border-color:var(--acc)}}.pane{{display:none}}.pane.on{{display:block}}
.blk{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:14px}}
.h{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:8px}}h3{{font-size:15px;margin:0}}.h span{{color:var(--muted);font-size:12.5px}}
pre{{white-space:pre-wrap;word-wrap:break-word;margin:0;font:14px/1.55 inherit;background:var(--bg);border-radius:8px;padding:12px}}
button{{background:var(--acc);color:var(--on);border:0;border-radius:8px;padding:7px 14px;font-weight:600;cursor:pointer}}
.media img{{width:100%;border-radius:10px;display:block;margin-bottom:14px;border:1px solid var(--line)}}.media img.tall{{max-width:300px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}}.grid img{{margin:0}}
table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden;margin-bottom:14px;font-size:13.5px}}
td,th{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}}ol{{margin:6px 0 0;padding-left:20px}}
</style></head><body><main><h1>{hesc(m['title'])}</h1><div class="meta">{hesc(m['project'])} · run {hesc(m['run_id'])} · {hesc(m['date'])} · made with Facetcast</div>
{f'<div class="core"><b>Core message.</b> {hesc(m["strategy"].get("core_message", ""))}</div>' if m['strategy'].get('core_message') else ''}
<div class="tabs">{''.join(tabs)}</div>{''.join(panes)}</main><script>
document.querySelectorAll(".tab").forEach(function(b,i){{b.onclick=function(){{document.querySelectorAll(".tab").forEach(function(x){{x.classList.remove("on")}});document.querySelectorAll(".pane").forEach(function(x){{x.classList.remove("on")}});b.classList.add("on");document.getElementById("p-"+b.dataset.t).classList.add("on")}};if(i===0)b.click()}});
function cp(i,b){{var t=document.getElementById("b"+i).textContent;function done(){{var o=b.textContent;b.textContent="Copied";setTimeout(function(){{b.textContent=o}},1200)}}
if(navigator.clipboard&&window.isSecureContext){{navigator.clipboard.writeText(t).then(done,fb)}}else fb();
function fb(){{var a=document.createElement("textarea");a.value=t;document.body.appendChild(a);a.select();try{{document.execCommand("copy");done()}}catch(e){{}}a.remove()}}}}
</script></body></html>"""


# ---------------------------------------------------------------- PDF

def pdf(m: dict, k: dict, imgs: dict, path: Path) -> None:
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate,
                                    Paragraph, Spacer, Table, TableStyle)

    F = {"sans": "Helvetica", "semi": "Helvetica-Bold", "bold": "Helvetica-Bold", "mono": "Courier", "monob": "Courier-Bold"}
    uni = False
    for kind in F:
        p = G.font_path(kind if kind != "semi" else "semi")
        if p and p.lower().endswith(".ttf"):
            try:
                pdfmetrics.registerFont(TTFont(f"FC-{kind}", p))
                F[kind] = f"FC-{kind}"
                uni = uni or kind == "sans"
            except Exception:
                pass

    def T(s) -> str:
        s = str(s if s is not None else "")
        if not uni:
            s = s.encode("cp1252", "replace").decode("cp1252")
        return xesc(s).replace("\n", "<br/>")

    pal = G.palette(m["theme"], m["accent"])
    INK, MUTE, LINE = colors.HexColor("#1b2430"), colors.HexColor("#5f6b78"), colors.HexColor("#dfe3e8")
    PAGE, CARD, SOFT = colors.HexColor("#f4f5f7"), colors.white, colors.HexColor("#f8f9fb")
    acc_hex = pal["accent"]
    for _ in range(8):                                  # accent used as text on white must stay readable
        if G.contrast(acc_hex, "#ffffff") >= 3.2:
            break
        acc_hex = G.mix(acc_hex, "#000000", 0.2)
    ACC = colors.HexColor(acc_hex)
    BARC = colors.HexColor(pal["accent"])
    BAND = colors.HexColor(pal["bg"] if pal["dark"] else "#1b2430")
    OKC, BAD, AMB, VIO = colors.HexColor("#1f9d6b"), colors.HexColor("#d64545"), colors.HexColor("#d99400"), colors.HexColor("#7c5cff")

    def st(name, font="sans", size=10, lead=None, color=INK, **kw):
        return ParagraphStyle(name, fontName=F[font], fontSize=size, leading=lead or size * 1.38, textColor=color, **kw)

    body, small = st("body", size=9.6, lead=13.6), st("small", size=8.3, color=MUTE)
    h1 = st("h1", "bold", 19, 23, colors.white)
    h2 = st("h2", "bold", 13, 17, INK, spaceBefore=10, spaceAfter=6)
    lab = st("lab", "semi", 7.4, 10, MUTE)
    W, H = A4
    M = 34
    CW = W - 2 * M

    def chrome(c, doc):
        c.saveState()
        c.setFillColor(PAGE)
        c.rect(0, 0, W, H, stroke=0, fill=1)
        c.setFillColor(BAND)
        c.rect(0, 0, W, 22, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#c9d1db"))
        c.setFont(F["mono"], 7.2)
        c.drawString(M, 8, f"Facetcast  |  {m['project']}  |  run {m['run_id']}")
        c.drawRightString(W - M, 8, f"page {doc.page}")
        c.restoreState()

    doc = BaseDocTemplate(str(path), pagesize=A4, leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=38,
                          title=f"{m['title']} - Facetcast kit", author="Facetcast")
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(M, 38, CW, H - M - 38, 0, 0, 0, 0)], onPage=chrome)])
    S = []

    def band(title, sub):
        t = Table([[Paragraph(f'<font size="8" color="{pal["accent"] if pal["dark"] else "#9fb3c8"}">{T(sub)}</font>', st("b0", "monob", 8, 10, colors.white))],
                   [Paragraph(T(title), h1)]], colWidths=[CW])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BAND), ("LEFTPADDING", (0, 0), (-1, -1), 16),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 16), ("TOPPADDING", (0, 0), (0, 0), 12),
                               ("BOTTOMPADDING", (0, 1), (0, 1), 14), ("LINEBELOW", (0, -1), (-1, -1), 3, ACC)]))
        return t

    def card(rows, pad=12, bg=CARD):
        t = Table([[r] for r in rows], colWidths=[CW])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LEFTPADDING", (0, 0), (-1, -1), pad),
                               ("RIGHTPADDING", (0, 0), (-1, -1), pad), ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("BOX", (0, 0), (-1, -1), .6, LINE),
                               ("TOPPADDING", (0, 0), (0, 0), 10), ("BOTTOMPADDING", (0, -1), (-1, -1), 10)]))
        return t

    def img(key, width, max_h=None):
        if key not in imgs:
            return Paragraph(T("(image not rendered: pip install pillow)"), small)
        from PIL import Image as PI
        w, h = PI.open(io.BytesIO(imgs[key])).size
        ww, hh = width, width * h / w
        if max_h and hh > max_h:
            ww, hh = max_h * w / h, max_h
        return Image(io.BytesIO(imgs[key]), width=ww, height=hh)

    def bar(pct, w=120, color=None, h=7):
        color = color or BARC
        d = Drawing(w, h + 2)
        d.add(Rect(0, 1, w, h, rx=3.5, ry=3.5, fillColor=colors.HexColor("#e6e9ee"), strokeColor=None))
        if pct > 0:
            d.add(Rect(0, 1, max(w * min(pct, 1), 4), h, rx=3.5, ry=3.5, fillColor=color, strokeColor=None))
        return d

    def text_card(label_, text, bg=SOFT, mono=False):
        return card([Paragraph(f'<font name="{F["semi"]}" size="7.5" color="#5f6b78">{T(label_.upper())}</font>', small),
                     Paragraph(T(text), st("tc", "mono" if mono else "sans", 8.6 if mono else 9.4, 12.2 if mono else 13.4))], bg=bg)

    def steps_table(p):
        rows = [[Paragraph(f'<font name="{F["bold"]}" color="{acc_hex}">{i}</font>', st("n", size=11)),
                 Paragraph(T(t), body), Paragraph("[  ]", st("cb", "mono", 9, color=MUTE))]
                for i, t in enumerate(P.SPECS[p]["steps"], 1)]
        t = Table(rows, colWidths=[22, CW - 60, 30])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CARD), ("BOX", (0, 0), (-1, -1), .6, LINE),
                               ("LINEBELOW", (0, 0), (-1, -2), .4, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                               ("LEFTPADDING", (0, 0), (0, -1), 10)]))
        return t

    # ===== cover
    S.append(band(m["title"], f"FACETCAST KIT  |  {m['project']}  |  {m['date']}"))
    S.append(Spacer(1, 10))
    if m["strategy"].get("core_message"):
        S.append(text_card("Core message", m["strategy"]["core_message"], bg=CARD))
        S.append(Spacer(1, 8))
    tiles = []
    for p in m["platforms"]:
        key = {"linkedin": "linkedin/graphic.png", "x": "x/card.png", "instagram": "instagram/slide-01.png",
               "tiktok": "tiktok/cover.png", "github": "github/social-preview.png"}[p]
        head = P.headline_of(p, m["drafts"].get(p)) if p != "github" else (m["showcase"] or {}).get("description", "")
        tiles.append([img(key, CW / 3 - 24, 92), Paragraph(f"<b>{T(P.label(p))}</b><br/>{T(head[:90])}", st("tl", size=8, lead=10.4))])
    if tiles:
        cells = [[Table([[a], [b]], colWidths=[CW / 3 - 12]) for a, b in tiles[i:i + 3]] for i in range(0, len(tiles), 3)]
        for row in cells:
            while len(row) < 3:
                row.append("")
        tt = Table(cells, colWidths=[CW / 3] * 3)
        tt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
        S.append(Paragraph("In this kit", h2))
        S.append(tt)
    pr = m["profile"]
    v = pr.get("voice") or {}
    if v:
        S.append(Paragraph("The voice it was written in", h2))
        info = (f"<b>{T(', '.join(v.get('tone') or []))}</b>  ·  person: {T(v.get('person'))}  ·  formality {v.get('formality')}/5  ·  "
                f"energy {v.get('energy')}/5  ·  humor {T(v.get('humor'))}  ·  emoji {T(v.get('emoji'))}<br/>"
                f"<font color='#5f6b78'>{T(v.get('sentence_style'))} {T(v.get('vocabulary'))}</font>"
                + (f"<br/><font color='#5f6b78'>Phrases kept: {T(' | '.join(v['signature_phrases']))}</font>" if v.get("signature_phrases") else "")
                + f"<br/><font color='#5f6b78'>Read from {T(pr.get('voice_source', 'the README'))}"
                + (" and your own posts" if pr.get("user_voice_used") else "") + ".</font>")
        S.append(card([Paragraph(info, body)]))
        fit = pr.get("platform_fit") or {}
        if fit:
            rows = [[Paragraph(T(P.label(p)), body), bar((x or {}).get("score", 0)), Paragraph(f"{round((x or {}).get('score', 0) * 100)}%", st("pc", "monob", 8.5)),
                     Paragraph(T((x or {}).get("why", "")), st("w", size=8, lead=10.5, color=MUTE))] for p, x in fit.items()]
            ft = Table(rows, colWidths=[90, 130, 36, CW - 256])
            ft.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
            S.append(Paragraph("Where this project lands", h2))
            S.append(ft)
    if m["warnings"]:
        S.append(Spacer(1, 6))
        S.append(Paragraph("<b>Warnings:</b> " + T("; ".join(m["warnings"])), st("wn", size=9, color=colors.HexColor("#8a5a00"))))

    # ===== one page per platform
    for p in m["platforms"]:
        S.append(PageBreak())
        plan = (m["strategy"].get("plans") or {}).get(p) or {}
        sub = f"{P.label(p).upper()}" + (f"  |  {plan.get('format')}" if plan.get("format") else "")
        sc = m["scores"].get(p)
        if sc:
            sub += "  |  first-draft critic " + " ".join(f"{k} {v}/5" for k, v in sc.items())
            if p in m.get("revised", []):
                sub += "  |  revised after critique"
        S.append(band(P.label(p), sub))
        S.append(Spacer(1, 10))
        kk = k[p]
        if p == "linkedin":
            S.append(img("linkedin/graphic.png", CW * 0.66))
            S.append(Spacer(1, 6))
            S.append(text_card("Post", kk["post"], bg=CARD))
            S.append(Spacer(1, 6))
            S.append(KeepTogether([text_card("First comment", kk["first_comment"]), Spacer(1, 6),
                                   text_card("Image alt text", kk["alt_text"])]))
        elif p == "x":
            S.append(img("x/card.png", CW * 0.66))
            S.append(Spacer(1, 6))
            for i, t in enumerate(kk["tweets"], 1):
                S.append(KeepTogether([text_card(f"Tweet {i}  ·  {P.x_len(t)}/280", t, bg=CARD), Spacer(1, 4)]))
        elif p == "instagram":
            keys = sorted(x for x in imgs if x.startswith("instagram/"))
            grid = [[img(x, CW / 4 - 10) for x in keys[i:i + 4]] for i in range(0, len(keys), 4)]
            for row in grid:
                while len(row) < 4:
                    row.append("")
            if grid:
                gt = Table(grid, colWidths=[CW / 4] * 4)
                gt.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3)]))
                S.append(gt)
            S.append(Spacer(1, 6))
            S.append(text_card("Caption", kk["caption"], bg=CARD))
        elif p == "tiktok":
            rows = [[Paragraph("TIME", lab), Paragraph("VISUAL", lab), Paragraph("VOICEOVER", lab), Paragraph("ON SCREEN", lab)]]
            for s in kk["scenes"]:
                rows.append([Paragraph(f"{s['seconds']:g}s", st("t", "mono", 8)), Paragraph(T(s["visual"]), st("v", size=8, lead=10.6)),
                             Paragraph(T(s.get("voiceover", "")), st("vo", size=8, lead=10.6)), Paragraph(T(s.get("on_screen", "")), st("os", "semi", 8, 10.6))])
            stt = Table(rows, colWidths=[34, (CW - 160) * .33, (CW - 160) * .42, (CW - 160) * .25], repeatRows=1)
            stt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CARD), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f4")),
                                     ("BOX", (0, 0), (-1, -1), .6, LINE), ("LINEBELOW", (0, 0), (-1, -2), .4, LINE),
                                     ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            side = Table([[img("tiktok/cover.png", 110, 196), stt]], colWidths=[126, CW - 126])
            side.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            S.append(Paragraph(f"<b>Hook (first 2 seconds):</b> {T(kk['hook'])}  ·  about {kk['duration_s']}s", body))
            S.append(Spacer(1, 6))
            S.append(side)
            S.append(Spacer(1, 6))
            S.append(text_card("Caption", kk["caption"], bg=CARD))
        else:
            s = m["showcase"]
            S.append(img("github/social-preview.png", CW * 0.66))
            S.append(Spacer(1, 6))
            S.append(text_card("Description (About)", kk["description"], bg=CARD))
            S.append(Spacer(1, 4))
            S.append(text_card("Topics", " ".join(kk["topics"]), mono=True))
            score = s.get("readme_score")
            S.append(Paragraph("README checklist" + (f"  ·  current score {score}/100" if score is not None else ""), h2))
            col = {"ok": OKC, "weak": AMB, "missing": BAD}
            crow = [[Paragraph(f'<font name="{F["monob"]}" size="7.5" color="{col[c["status"]].hexval().replace("0x", "#")}">{c["status"].upper()}</font>', small),
                     Paragraph(f"<b>{T(c['item'])}</b>" + (f"<br/><font color='#5f6b78'>{T(c['fix'])}</font>" if c.get("fix") else ""), st("ci", size=8.6, lead=11.6))]
                    for c in kk["checklist"]]
            ct = Table(crow, colWidths=[56, CW - 56])
            ct.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CARD), ("BOX", (0, 0), (-1, -1), .6, LINE),
                                    ("LINEBELOW", (0, 0), (-1, -2), .4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            S.append(ct)
            S.append(Paragraph("Portfolio case study", h2))
            c = s["case_study"]
            S.append(card([Paragraph(f"<b>{T(c['title'])}</b>  <font color='#5f6b78' size='8'>{T(c.get('role') or '')}"
                                     f"{'  ·  ' + T(', '.join(c.get('stack') or [])) if c.get('stack') else ''}</font>", body),
                           Paragraph(f"<b>Problem.</b> {T(c['problem'])}", body), Paragraph(f"<b>Approach.</b> {T(c['approach'])}", body),
                           Paragraph(f"<b>Outcome.</b> {T(c['outcome'])}", body)]))
            S.append(Spacer(1, 6))
            S.append(text_card("Freelance pitch", kk["pitch"]))
            S.append(Spacer(1, 4))
            S.append(Paragraph(T("The full suggested README is in github/README.suggested.md."), small))
        S.append(KeepTogether([Paragraph("Post it", h2), steps_table(p)]))

    # ===== visuals to capture
    vp = m["visual_plan"]
    if vp.get("shots") or vp.get("image_prompts"):
        S.append(PageBreak())
        S.append(Paragraph("Visuals to capture", h2))
        for x in vp.get("shots") or []:
            chip = f'  <font name="{F["mono"]}" size="7.5" color="{acc_hex}">{T(x["file_path"])}</font>' if x.get("file_path") else ""
            S.append(KeepTogether([card([Paragraph(f'<font name="{F["mono"]}">[  ]</font>  <b>{T(x["shot"])}</b>  '
                                                   f'<font size="7.5" color="#5f6b78">{T(x["kind"])} · ~{x["minutes"]} min · '
                                                   f'{T(", ".join(P.label(q) for q in x.get("platforms") or []))}</font>{chip}', body),
                                         Paragraph(T(x["how"]), st("how", size=8.4, lead=11.5, color=MUTE))]), Spacer(1, 4)]))
        for r in vp.get("reuse") or []:
            S.append(Paragraph(f"<b>Reuse</b> <font name='{F['mono']}'>{T(r['file_path'])}</font>: {T(r['use'])}", body))
        if vp.get("image_prompts"):
            S.append(Paragraph("Prompts for image tools", h2))
            for ip in vp["image_prompts"]:
                S.append(KeepTogether([text_card(f"{P.label(ip['platform'])} · {ip['tool']}", ip["prompt"], mono=True), Spacer(1, 4)]))

    # ===== evidence
    S.append(PageBreak())
    S.append(Paragraph("Evidence: every claim points at a real file", h2))
    S.append(Paragraph(T(f"Checked against the project at {(m['repo'].get('head_sha') or '')[:12]}. "
                         "Facetcast refuses to package content citing a file or commit that does not exist."), small))
    S.append(Spacer(1, 6))
    ev = [[Paragraph("CLAIM", lab), Paragraph("FILE", lab), Paragraph("REF", lab)]]
    for c in m["claims"]:
        ev.append([Paragraph(T(c["claim"]), st("c", size=8.6, lead=11.6)),
                   Paragraph(T(c["source_path"]), st("f", "mono", 7.8, 10.2, colors.HexColor("#1f7a5a"))),
                   Paragraph(T(c["source_ref"]), st("r", "mono", 7.8, 10.2))])
    et = Table(ev, colWidths=[CW * .52, CW * .32, CW * .16], repeatRows=1)
    et.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CARD), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f4")),
                            ("BOX", (0, 0), (-1, -1), .6, LINE), ("LINEBELOW", (0, 0), (-1, -2), .4, LINE),
                            ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    S.append(et)

    # ===== how it was made
    S.append(Paragraph("How this kit was made", h2))
    cols, gap, bh = 5, 8, 38
    bw = (CW - (cols - 1) * gap) / cols
    rows_n = -(-len(m["pipeline"]) // cols)
    dh = rows_n * (bh + 16) + 4
    dr = Drawing(CW, dh)
    col = {"success": OKC, "skipped": colors.HexColor("#9aa7b5"), "you": VIO, "pending": colors.HexColor("#c8d0d9"),
           "failed": BAD, "waiting": AMB}
    for i, p in enumerate(m["pipeline"]):
        r, ci = divmod(i, cols)
        x, y = ci * (bw + gap), dh - (r + 1) * (bh + 16) + 10
        c_ = col.get(p["status"], col["pending"])
        dr.add(Rect(x, y, bw, bh, rx=6, ry=6, fillColor=colors.white, strokeColor=c_, strokeWidth=1.4))
        dr.add(Rect(x, y, 4, bh, fillColor=c_, strokeColor=None))
        dr.add(String(x + 10, y + bh - 14, p["tag"], fontName=F["monob"], fontSize=8.5, fillColor=INK))
        dr.add(String(x + 10, y + bh - 25, p["name"][:24], fontName=F["sans"], fontSize=7.4, fillColor=MUTE))
        tm = "you" if p["status"] == "you" else (f"{p['secs']:.1f}s" if p["secs"] is not None else
                                                  {"success": "done"}.get(p["status"], p["status"]))
        dr.add(String(x + bw - 6, y + 6, tm, fontName=F["mono"], fontSize=7, fillColor=c_, textAnchor="end"))
        if ci < cols - 1 and i < len(m["pipeline"]) - 1:
            dr.add(Line(x + bw + 1, y + bh / 2, x + bw + gap - 1, y + bh / 2, strokeColor=colors.HexColor("#9aa7b5"), strokeWidth=1))
    S.append(dr)
    if m["angles"]:
        S.append(Paragraph("Angles considered", h2))
        arows = []
        for a in m["angles"][:8]:
            ch = a["title"] == m["title"]
            arows.append([Paragraph(("<b>" if ch else "") + T(a["title"]) + ("</b>  <font color='#1f9d6b' size='7'>CHOSEN</font>" if ch else "")
                                    + f"<br/><font size='7.4' color='#5f6b78'>best on {T(', '.join(P.label(q) for q in a.get('best_platforms') or []))}</font>",
                                    st("at", size=8.4, lead=11.2)),
                          bar(a.get("score", 0), 90, ACC if ch else colors.HexColor("#9aa7b5")),
                          Paragraph(f"{round(a.get('score', 0) * 100)}%", st("pc2", "monob", 8.2))])
        at = Table(arows, colWidths=[CW - 140, 100, 40])
        at.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CARD), ("BOX", (0, 0), (-1, -1), .6, LINE),
                                ("LINEBELOW", (0, 0), (-1, -2), .4, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        S.append(at)
    if m["flags"]:
        S.append(Paragraph(T(f"The critic raised {len(m['flags'])} issue(s); the reviser applied "
                             f"{sum(1 for c in m['changes'] if c.get('action') == 'applied')} change(s); "
                             f"{len(m['unresolved'])} left for you."), small))
    doc.build(S)


def contrast_ok(hex_: str) -> bool:
    return G.contrast(hex_, "#ffffff") >= 2.2


# ---------------------------------------------------------------- build

def build_kit(ctx: dict, folder, records: dict | None = None, theme: str | None = None, date: str | None = None) -> dict:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    m = collect(ctx, records, date, theme)
    k = kits(m)
    imgs, notes = images(m)
    for rel, data in imgs.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(data)
    for rel, text in md_files(m, k).items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding="utf-8")
    (folder / "index.html").write_text(html_page(m, k, imgs), encoding="utf-8")
    try:
        pdf(m, k, imgs, folder / "00_REPORT.pdf")
    except Exception as e:
        notes.append(f"00_REPORT.pdf skipped ({type(e).__name__}: {e}). Run: pip install reportlab")
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p.name != "manifest.json")
    manifest = {"project": m["project"], "run_id": m["run_id"], "date": m["date"], "title": m["title"],
                "platforms": m["platforms"], "theme": m["theme"], "written": datetime.now().isoformat(timespec="seconds"),
                "files": files, "skipped": notes}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"folder": folder.as_posix(), "pdf": (folder / "00_REPORT.pdf").as_posix(), "files": files,
            "images": sorted(imgs), "skipped": notes, "kits": k, "theme": m["theme"]}
