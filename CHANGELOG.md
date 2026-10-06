# Changelog

## 1.0.0 - 2026-10-05

First public release. Facetcast grew out of a private, single-author LinkedIn pipeline
("Content OS") and was rebuilt for anyone, any project and every platform.

### New
- **Any project:** GitHub, GitLab, Bitbucket, Codeberg and any https `.git` URL, zip URLs, local
  zips, local folders (git or not), and folder drag-and-drop in the dashboard. Non-code projects
  (theses, design and photo work, research, writing) are first-class.
- **Profiler agent (A04):** reads the author's voice from the README (plus optional past posts),
  audiences, README quality, per-platform fit and a visual theme. Signature phrases verified verbatim.
- **Multi-platform:** LinkedIn post, X thread, Instagram carousel (rendered slides), TikTok / Reels /
  Shorts script with cover. Angles are scored per platform; you choose the platforms at G1.
- **Showcase agent (A11):** GitHub & portfolio kit: README audit and improved draft, description,
  topics, social preview, case study, freelance pitch.
- **Graphics engine:** five themes with an accent colour per project, bundled fonts, automatic contrast.
- **Engines:** Claude Code and manual copy-paste (no key), plus Anthropic, OpenAI, OpenRouter, Groq,
  Gemini, Ollama, LM Studio and any OpenAI-compatible endpoint. Paste a key (or drop a `.env`) and
  the provider is detected and tested.
- **Dashboard:** redesigned. Live pipeline, angle picker with per-platform fit, native previews per
  platform, edit at review, one-click theme redraw, memory view, light/dark mode.
- **Demo mode:** `python facetcast.py demo` runs the whole pipeline on a bundled example with no engine.
- **Security:** localhost-only server with Host, CSRF and CSP protection; hardened uploads.

### Kept from Content OS
- Evidence-bound claims checked by code, fail-closed stages, resumable runs, critic + reviser
  loop, memory with dedup, the PDF report.
