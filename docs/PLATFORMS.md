# Platforms

All limits live in `core/platforms.py`, so the writer, the critic, the packager and the dashboard
always agree.

| Platform | What Facetcast writes | Hard limits (packaging fails) | Soft checks (critic / warnings) | Image |
|---|---|---|---|---|
| LinkedIn | a post + first comment (the link goes there) + alt text | 3,000 chars | hook within the ~210-char fold, no links in the body, ≤4 hashtags, no markdown | 1200×627 card |
| X | a thread (1-10 tweets) | 280 per tweet (URLs count 23) | tweet 1 works alone, ≤2 hashtags | 1600×900 card |
| Instagram | a carousel (3-10 slides, rendered as images) + caption + alt text per slide | 2,200-char caption | first 125 chars hook, ≤40 words per slide, "link in bio" not URLs | 1080×1350 slides |
| TikTok / Reels / Shorts | a faceless-friendly video script: scenes with timing, visual, voiceover, on-screen text + caption | 2,200-char caption | voiceover fits ~2.6 words/s, 15-90 s | 1080×1920 cover |
| GitHub & portfolio | README audit + improved README draft, description, topics, social preview, case study, freelance pitch, pinned blurb | description cut to 350 | topics normalised, README draft may only link files that exist | 1280×640 preview |

## Adding a platform

1. Add its spec to `SPECS` and its id to `CONTENT_PLATFORMS` in `core/platforms.py`, plus
   `draft_text()` / `headline_of()`.
2. Add a Pydantic model and a branch in `tidy()` in `agents/writer/agent.py`; add it to `Drafts`
   and to `Revision` in the reviser.
3. Add `RANGES` in the strategist, renderers in `core/report.py` (`kits`, `images`, `md_files`,
   `html_page`, `pdf`) and a preview in `dashboard/static/app.js`.
4. Add a test in `tests/test_pipeline.py`.
