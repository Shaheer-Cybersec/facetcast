"""
settings - every path and setting in one place.

Rules:
  - No other module hardcodes a path. Everything imports from here.
  - Priority: real environment variable > .env file > default below.
  - API keys are optional. Facetcast runs with no key at all (Claude Code CLI or
    manual copy-paste). Keys pasted in the dashboard's Engines panel land in .env,
    which is gitignored.
"""
from __future__ import annotations

import os
from pathlib import Path

# Project root = the folder that contains config/
ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
APP_NAME = "Facetcast"
VERSION = "1.0.0"


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader: KEY=VALUE lines, '#' comments.
    setdefault() means a real environment variable always wins."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ENV_FILE)

# ---------- paths ----------
DATA_DIR = Path(os.getenv("FACETCAST_DATA_DIR", ROOT / "data"))   # runtime state, gitignored
CACHE_DIR = DATA_DIR / "repo_cache"       # ingest output, one JSON per commit / content hash
RUNS_DIR = DATA_DIR / "runs"              # run state + handoff prompt/response files
UPLOADS_DIR = DATA_DIR / "uploads"        # zips and folders dropped in the dashboard
NOTES_DIR = DATA_DIR / "notes"            # read-only markdown mirror (Obsidian friendly)
DB_PATH = DATA_DIR / "facetcast.db"       # SQLite memory
ENGINE_FILE = DATA_DIR / "engine.json"    # which engine the dashboard / CLI uses
OUTPUTS_DIR = Path(os.getenv("FACETCAST_OUTPUTS_DIR", ROOT / "outputs"))
VOICE_DIR = ROOT / "memory" / "voice"     # optional: your own past posts, gitignored
FONTS_DIR = ROOT / "assets" / "fonts"

# ---------- LLM engine ----------
# claude_cli = Claude Code on this machine ("claude -p"), logged in with your Claude plan. No key.
# claude     = manual: Facetcast writes the prompt, you paste Claude's JSON answer back. No key.
# anthropic / openai / openrouter / groq / gemini / ollama / lmstudio / custom = API engines
#              (see core/engines.py). Paste a key in the dashboard's Engines panel.
# mock       = fake outputs for tests and demos.
ENGINE_ENV = os.getenv("FACETCAST_ENGINE", "").strip().lower()

CLAUDE_BIN = os.getenv("FACETCAST_CLAUDE_BIN", "claude").strip()   # path or name of Claude Code
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip().rstrip("/")
LMSTUDIO_HOST = os.getenv("LMSTUDIO_HOST", "http://localhost:1234").strip().rstrip("/")

# ---------- author (optional, only used on graphics and previews) ----------
AUTHOR_NAME = os.getenv("FACETCAST_AUTHOR_NAME", "").strip()       # "Jane Doe"
AUTHOR_HANDLE = os.getenv("FACETCAST_AUTHOR_HANDLE", "").strip()   # "@janedoe"
AUTHOR_HEADLINE = os.getenv("FACETCAST_AUTHOR_HEADLINE", "").strip()

# ---------- dedup ----------
EMBEDDINGS_ENABLED = os.getenv("FACETCAST_EMBEDDINGS", "on").strip().lower() != "off"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEDUP_THRESHOLD = 0.82   # angle vs past post similarity above this = duplicate

# ---------- dashboard ----------
DASHBOARD_PORT = int(os.getenv("FACETCAST_PORT", "8765"))

# Create runtime folders on import so no module has to check first
for _d in (DATA_DIR, CACHE_DIR, RUNS_DIR, UPLOADS_DIR, NOTES_DIR, OUTPUTS_DIR, VOICE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    print(f"{APP_NAME} {VERSION}")
    print(f"ROOT         {ROOT}")
    print(f"ENGINE env   {ENGINE_ENV or '(auto)'}")
    print(f"DB_PATH      {DB_PATH}")
    for d in (DATA_DIR, CACHE_DIR, RUNS_DIR, NOTES_DIR, OUTPUTS_DIR, VOICE_DIR):
        print(f"{'ok' if d.is_dir() else 'MISSING':<12} {d}")
