"""
Pre-push safety check. Run it before every `git push`:

    python scripts/prepush_check.py
    python scripts/prepush_check.py --files-only     (CI: skip commit e-mail / trailer checks)

It looks at exactly what git would publish (tracked files plus the commit history) and fails
loudly if it finds a secret, a private file, a local database, or your personal e-mail in a commit.
Standard library only.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that must never be published.
BAD_PATHS = re.compile(
    r"(^|/)(\.env(\..*)?|.*\.(db|sqlite3?|pem|key|p12|pfx|zip|7z|rar|log)|id_rsa.*|data/(?!\.gitkeep)|"
    r"outputs/(?!\.gitkeep)|memory/voice/(?!README\.md))$",
    re.I,
)
ALLOWED_PATHS = {".env.example"}

# Things that look like credentials.
SECRETS = [
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("OpenRouter key", re.compile(r"sk-or-v1-[A-Za-z0-9]{32,}")),
    ("Groq key", re.compile(r"\bgsk_[A-Za-z0-9]{30,}")),
    ("Google key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}")),
    ("AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
# Local machine paths (a real user name, not a placeholder like C:\Users\me).
LOCAL_PATH = re.compile(r"[A-Za-z]:\\+Users\\+(?!me\b|you\b|name\b|user\b|<)[A-Za-z0-9._-]+|/home/(?!you\b|user\b|me\b)[a-z0-9_-]+/")

MAX_BYTES = 3_000_000


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def main() -> int:
    problems: list[str] = []
    warnings: list[str] = []
    try:
        files = [f for f in git("ls-files").splitlines() if f]
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("This folder is not a git repository (or git is missing).")
        return 2

    for name in files:
        path = ROOT / name
        if name not in ALLOWED_PATHS and BAD_PATHS.search(name):
            problems.append(f"private/local file is tracked: {name}")
            continue
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_BYTES:
            warnings.append(f"large file ({path.stat().st_size // 1024} KB): {name}")
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ttf", ".pdf", ".ico", ".woff", ".woff2"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, rx in SECRETS:
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                # Fake keys used by the test-suite are fine.
                if name.startswith("tests/"):
                    continue
                problems.append(f"{label} in {name}:{line}")
        for m in LOCAL_PATH.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            warnings.append(f"local path '{m.group(0)}' in {name}:{line}")

    # Commit history: author and committer e-mails and message trailers are public once pushed.
    if "--files-only" in sys.argv:
        commits, emails, messages = [], set(), ""
    else:
        commits, emails, messages = history(warnings)
    for e in sorted(emails):
        if not e.endswith("@users.noreply.github.com"):
            warnings.append(f"commit e-mail will be public: {e}  (use your GitHub noreply address, see docs/GITHUB_SETUP.md)")
    if re.search(r"^(Co-Authored-By|Claude-Session):", messages, re.I | re.M):
        problems.append("a commit message has a Co-Authored-By / Claude-Session trailer (it adds a contributor on GitHub); recreate the commit, see docs/GITHUB_SETUP.md")

    print(f"Checked {len(files)} tracked files" + ("" if "--files-only" in sys.argv else f" and {len(commits)} commit(s)") + ".\n")
    for w in warnings:
        print(f"  WARN  {w}")
    for p in problems:
        print(f"  FAIL  {p}")
    if problems:
        print("\nDo NOT push yet. Fix the FAIL lines above.")
        return 1
    print("\nNo secrets or private files found." + ("  Review the WARN lines." if warnings else "  Safe to push."))
    return 0


def history(warnings: list[str]) -> tuple[list[str], set[str], str]:
    try:
        commits = git("rev-list", "HEAD").split()
        emails = {e for e in git("log", "--format=%ae%n%ce").split() if e}
        messages = git("log", "--format=%B")
    except subprocess.CalledProcessError:  # no commit yet: check the e-mail the next commit will use
        commits, messages = [], ""
        try:
            emails = {git("config", "user.email").strip()} - {""}
        except subprocess.CalledProcessError:
            emails = set()
            warnings.append("no git user.email set yet (see docs/GITHUB_SETUP.md)")
    return commits, emails, messages


if __name__ == "__main__":
    sys.exit(main())
