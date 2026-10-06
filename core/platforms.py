"""
platforms - the rules of every platform Facetcast writes for, in one place.

Agents, the critic's static checks, the packager's hard stops and the dashboard all
read these specs, so a limit is changed once, here.

Content platforms (written by the writer, checked by the critic):
  linkedin   one text post + graphic, link in the first comment
  x          a thread (or a single post) + card image
  instagram  a carousel (slides rendered as images) + caption
  tiktok     a 15-90 s faceless-friendly video script + cover (also fits Reels / Shorts)
Project platform (built by the showcase agent):
  github     README audit + improved README draft, description, topics,
             social preview, portfolio case study and a freelance pitch
"""
from __future__ import annotations

import re

CONTENT_PLATFORMS = ("linkedin", "x", "instagram", "tiktok")
ALL_PLATFORMS = CONTENT_PLATFORMS + ("github",)

SPECS: dict[str, dict] = {
    "linkedin": {
        "label": "LinkedIn", "kind": "post",
        "max_chars": 3000, "fold": 210, "length": (600, 2200), "default_length": 1300,
        "hashtags": (0, 4), "links_in_body": False, "image": (1200, 627),
        "emoji_ok": False,
        "tips": ["Hook must land before the ~210 char 'see more' fold.",
                 "Links in the body cut reach: put them in the first comment.",
                 "Short paragraphs, plain text, no markdown."],
        "steps": ["Start a post and paste post.md.",
                  "Add graphic.png and paste alt_text.md as its alt text.",
                  "Publish, then immediately comment first_comment.md (it carries the link).",
                  "Reply to every comment in the first hour."],
    },
    "x": {
        "label": "X", "kind": "thread",
        "tweet_max": 280, "tweets": (1, 10), "default_length": 5,
        "hashtags": (0, 2), "links_in_body": True, "image": (1600, 900),
        "emoji_ok": True,
        "tips": ["Tweet 1 carries the whole hook; it must work alone.",
                 "One idea per tweet. Link in the last tweet, not the first.",
                 "0-2 hashtags; they rarely help on X."],
        "steps": ["Post tweet 1 with card.png attached.",
                  "Reply to it with each following tweet, in order (or paste all into the thread composer).",
                  "Pin the thread to your profile if it is your best work this week."],
    },
    "instagram": {
        "label": "Instagram", "kind": "carousel",
        "max_chars": 2200, "fold": 125, "slides": (3, 10), "default_length": 7,
        "slide_title_max": 60, "slide_body_words": 40,
        "hashtags": (0, 12), "links_in_body": False, "image": (1080, 1350),
        "emoji_ok": True,
        "tips": ["Slide 1 is the hook; slide 2 must reward the swipe.",
                 "First 125 caption characters show before 'more'.",
                 "Links are not clickable in captions: say 'link in bio'."],
        "steps": ["New post, select every slide-NN.png in order (4:5).",
                  "Paste caption.md. Add alt text per slide from alt_text.md.",
                  "Put the project link in your bio before posting."],
    },
    "tiktok": {
        "label": "TikTok / Reels / Shorts", "kind": "video",
        "max_chars": 2200, "duration": (15, 90), "default_length": 45,
        "words_per_second": 2.6, "scenes": (3, 10),
        "hashtags": (0, 5), "links_in_body": False, "image": (1080, 1920),
        "emoji_ok": True,
        "tips": ["The first 2 seconds decide everything: on-screen hook text + motion.",
                 "Faceless works: screen recording, b-roll or slides + voiceover.",
                 "Add captions; most people watch muted."],
        "steps": ["Record the voiceover from script.md (about 2.5 words per second).",
                  "Capture each scene's visual (screen recording, photos or slides).",
                  "Edit in CapCut / the TikTok editor, add on-screen text, set cover.png.",
                  "Paste caption.md. The same video fits Instagram Reels and YouTube Shorts."],
    },
    "github": {
        "label": "GitHub & Portfolio", "kind": "showcase",
        "description_max": 350, "topics_max": 20, "image": (1280, 640),
        "tips": ["A clear README is your best portfolio piece.",
                 "Description + topics make the repo findable in GitHub search.",
                 "Upload social-preview.png in Settings -> Social preview."],
        "steps": ["Review README.suggested.md and merge what fits into your README.",
                  "Repo page -> About (gear icon): paste the description and topics.",
                  "Settings -> General -> Social preview: upload social-preview.png.",
                  "Pin the repo on your profile; reuse case-study.md on your portfolio / Upwork / Fiverr."],
    },
}

GENERIC_TAGS = {"#tech", "#technology", "#motivation", "#success", "#linkedin", "#innovation",
                "#growth", "#mindset", "#viral", "#fyp", "#foryou", "#trending", "#explore",
                "#instagood", "#follow", "#like4like"}

HASHTAG_RE = re.compile(r"(?<!\w)#\w+")
URL_RE = re.compile(r"https?://\S+")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F000-\U0001F2FF]")


def label(p: str) -> str:
    return SPECS.get(p, {}).get("label", p)


def normalize(platforms) -> list[str]:
    """Accept 'linkedin,x' or a list; return known platforms in canonical order."""
    if isinstance(platforms, str):
        platforms = [p for p in re.split(r"[,\s]+", platforms) if p]
    want = {str(p).strip().lower().replace("twitter", "x") for p in (platforms or [])}
    want |= {"tiktok"} if want & {"reels", "shorts", "youtube"} else set()
    return [p for p in ALL_PLATFORMS if p in want]


def x_len(text: str) -> int:
    """Approximate X's weighted length: URLs count 23, emoji count 2."""
    t = URL_RE.sub("x" * 23, text or "")
    return len(t) + len(EMOJI_RE.findall(t))


def clean_hashtags(tags: list[str], platform: str) -> list[str]:
    out: list[str] = []
    for t in tags or []:
        word = re.sub(r"[^A-Za-z0-9_]", "", str(t))
        tag = f"#{word}"
        if word and not word.isdigit() and tag.lower() not in GENERIC_TAGS \
                and tag.lower() not in {x.lower() for x in out}:
            out.append(tag)
    return out[:SPECS.get(platform, {}).get("hashtags", (0, 5))[1]]


def ensure_hashtags(text: str, tags: list[str]) -> str:
    missing = [t for t in tags if t.lower() not in (text or "").lower()]
    return f"{text.rstrip()}\n\n{' '.join(missing)}" if missing else text


# ---------- text views of a platform draft (critic quotes, memory, dedup) ----------

def draft_text(platform: str, d: dict | None) -> str:
    """Every word a platform draft would publish, as one string."""
    if not d:
        return ""
    if platform == "linkedin":
        return d.get("text", "")
    if platform == "x":
        return "\n\n".join(d.get("tweets") or [])
    if platform == "instagram":
        slides = "\n\n".join(f"{s.get('title', '')}\n{s.get('body', '')}" for s in d.get("slides") or [])
        return f"{slides}\n\n{d.get('caption', '')}"
    if platform == "tiktok":
        scenes = "\n".join(f"{s.get('on_screen', '')}\n{s.get('voiceover', '')}" for s in d.get("scenes") or [])
        return f"{d.get('hook', '')}\n{scenes}\n\n{d.get('caption', '')}"
    return ""


def voiceover_words(d: dict) -> int:
    return sum(len((s.get("voiceover") or "").split()) for s in d.get("scenes") or [])


def headline_of(platform: str, d: dict | None) -> str:
    """The first thing a reader sees on that platform."""
    if not d:
        return ""
    if platform == "linkedin":
        return (d.get("text") or "").strip().split("\n")[0]
    if platform == "x":
        return ((d.get("tweets") or [""])[0]).split("\n")[0]
    if platform == "instagram":
        return ((d.get("slides") or [{}])[0]).get("title", "")
    if platform == "tiktok":
        return d.get("hook") or ""
    return ""
