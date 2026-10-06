"""
[A01] ingest - static agent (no LLM). Reads a project, whatever shape it is in.

Input : ctx["source"], any of:
          https://github.com/owner/repo  (also GitLab, Bitbucket, Codeberg, any https .git URL)
          https://github.com/owner/repo/archive/main.zip       (zip download)
          C:\\Users\\me\\Downloads\\project.zip                 (local zip)
          C:\\Users\\me\\Projects\\my-thesis                    (local folder, git or not)
Output: ctx["repo"]   structured JSON every later agent reads

The README is the most important input: the profiler reads the author's voice from it
and the analyzer reads what the project is. Non-code projects (a thesis, a design
portfolio, research notes) work as long as their writing is in text files
(.md .txt .rst .tex .html ...).

Every path in "tree" is a valid evidence source_path. head_sha (and each SHA in
"commits") is a valid source_ref. Without git history, head_sha is a SHA-256 content
hash (source_ref_kind = "content-hash"), so claims still bind to an exact snapshot.

Zip extraction is hardened: no path traversal (zip slip), no symlinks, capped file
count and uncompressed size (zip bomb). Local folders are read in place, never written.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from config.settings import CACHE_DIR
from core.base_agent import AgentError, BaseAgent

GIT_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org")
GIT_URL_RE = re.compile(r"^https://([\w.-]+)/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
ZIP_URL_RE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/(?:archive|zipball)/")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build",
             ".mypy_cache", ".pytest_cache", ".idea", ".vscode", ".next", ".nuxt", "target",
             ".gradle", ".tox", "site-packages", ".cache", "coverage", ".DS_Store", "__MACOSX"}
DEP_FILES = {"requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "package.json", "go.mod",
             "Cargo.toml", "docker-compose.yml", "docker-compose.yaml", "Dockerfile", "Gemfile",
             "composer.json", "pom.xml", "build.gradle", "pubspec.yaml", "environment.yml", "DESCRIPTION"}
CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cc",
            ".cpp", ".h", ".cs", ".rb", ".php", ".sh", ".ps1", ".r", ".R", ".jl", ".scala", ".dart",
            ".lua", ".sql", ".vue", ".svelte", ".m", ".ino", ".sol"}
DOC_EXT = {".md", ".markdown", ".txt", ".rst", ".tex", ".org", ".adoc", ".html", ".htm"}
DATA_EXT = {".yaml", ".yml", ".toml", ".json", ".csv", ".ipynb", ".css", ".scss"}
TEXT_EXT = CODE_EXT | DOC_EXT | DATA_EXT
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
ENTRY_HINTS = ("main", "app", "index", "server", "cli", "run", "api", "config", "abstract",
               "thesis", "paper", "report", "overview", "about", "intro", "summary", "chapter")
LOW_VALUE_DIRS = ("examples/", "benchmarks/", "vendor/", "third_party/", "fixtures/")

MAX_FILES = 800              # tree entries kept (tree_truncated=True beyond this)
MAX_COMMITS = 30
README_CHARS = 20_000
DEP_CHARS = 4_000
KEY_FILE_CHARS = 12_000      # per file
KEY_FILES_BUDGET = 80_000    # total chars handed to the analyzer
LOCAL_MAX_BYTES = 400 * 1024 * 1024
HASH_FILE_CAP = 2 * 1024 * 1024

ZIP_MAX_DOWNLOAD = 100 * 1024 * 1024
ZIP_MAX_UNCOMPRESSED = 300 * 1024 * 1024
ZIP_MAX_MEMBERS = 20_000
CACHE_VERSION = 1


# ---------- helpers ----------

def git(args: list[str], cwd: Path | None = None) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
    except FileNotFoundError:
        raise AgentError("git is not installed or not on PATH (needed for git URLs; zips and folders work without it)")
    except subprocess.TimeoutExpired:
        raise AgentError(f"git {args[0]} timed out after 180 s")
    if r.returncode != 0:
        err = r.stderr.strip()
        if "could not read Username" in err or "not found" in err.lower() or "Authentication" in err:
            raise AgentError("repo not found or private - check the URL (private repo: download it as a zip and drop it in)")
        raise AgentError(f"git {args[0]} failed: {err[:300]}")
    return r.stdout


def _has_git() -> bool:
    return shutil.which("git") is not None


def _force_remove(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)        # Windows: files inside .git are read-only
    func(path)


def rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_force_remove)
    else:
        shutil.rmtree(path, onerror=_force_remove)


def read_text(p: Path, limit: int) -> str:
    try:
        if p.suffix.lower() == ".ipynb":
            nb = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            cells = ["".join(c.get("source") or []) for c in nb.get("cells", [])]
            return "\n\n".join(cells)[:limit]
        return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except (OSError, ValueError):
        return ""


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name or "").strip("-.") or "project"


# ---------- source detection ----------

def classify(source: str) -> dict:
    """Work out what kind of input this is. Returns a dict with a 'kind' key."""
    s = (source or "").strip().strip('"').strip("'")
    if not s:
        raise AgentError("source is empty")
    low = s.lower()

    if not low.startswith(("http://", "https://")):
        p = Path(s).expanduser()
        if p.is_dir():
            return {"kind": "dir", "path": p.resolve(), "owner": "local", "repo": slug(p.resolve().name)}
        if low.endswith(".zip"):
            if not p.is_file():
                raise AgentError(f"zip file not found: {s}")
            return {"kind": "zip_file", "path": p, "owner": "local", "repo": None}
        raise AgentError(f"not a URL, a .zip or an existing folder: {s}")

    if low.startswith("http://"):
        raise AgentError("only https:// URLs are accepted")

    m = ZIP_URL_RE.search(s)
    if m or low.split("?")[0].endswith(".zip"):
        owner, repo = (m.group(1), m.group(2)) if m else ("remote", None)
        return {"kind": "zip_url", "url": s, "owner": owner, "repo": repo}

    s_clean = re.sub(r"/(tree|blob|-/tree)/.*$", "", s.split("?")[0].split("#")[0])
    m = GIT_URL_RE.match(s_clean)
    if m and (m.group(1).lower() in GIT_HOSTS or s_clean.endswith(".git")):
        host, owner, repo = m.group(1).lower(), m.group(2), m.group(3)
        return {"kind": "git", "host": host, "owner": owner, "repo": repo,
                "url": f"https://{host}/{owner}/{repo}.git", "web": f"https://{host}/{owner}/{repo}"}
    raise AgentError(f"not a supported git URL (GitHub, GitLab, Bitbucket, Codeberg or a .git URL): {source}")


# ---------- zip handling ----------

def download_zip(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "facetcast"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
            total = 0
            while chunk := r.read(1 << 16):
                total += len(chunk)
                if total > ZIP_MAX_DOWNLOAD:
                    raise AgentError("zip download is larger than 100 MB")
                f.write(chunk)
    except AgentError:
        raise
    except Exception as e:
        raise AgentError(f"could not download zip: {type(e).__name__}: {e}")


def safe_extract(zip_path: Path, dest: Path) -> zipfile.ZipFile:
    """Extract with zip-slip, symlink and zip-bomb protection."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise AgentError("file is not a valid zip archive")
    infos = zf.infolist()
    if len(infos) > ZIP_MAX_MEMBERS:
        raise AgentError(f"zip has too many entries ({len(infos)})")
    if sum(i.file_size for i in infos) > ZIP_MAX_UNCOMPRESSED:
        raise AgentError("zip expands to more than 300 MB")
    for info in infos:
        name = info.filename.replace("\\", "/")
        parts = PurePosixPath(name).parts
        if name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
            raise AgentError(f"unsafe path in zip: {info.filename}")
        if stat.S_ISLNK(info.external_attr >> 16):
            continue                          # never materialise symlinks
        zf.extract(info, dest)
    return zf


def zip_root(extracted: Path) -> Path:
    """GitHub zips wrap everything in one folder, e.g. repo-main/. Step into it."""
    entries = [p for p in extracted.iterdir() if p.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extracted


def zip_identity(zf: zipfile.ZipFile, zip_path: Path) -> tuple[str, str]:
    """(head_sha, kind). GitHub/git-archive zips store the commit SHA as the zip comment."""
    comment = zf.comment.decode("ascii", "ignore").strip().lower()
    if SHA40_RE.match(comment):
        return comment, "commit"
    return hashlib.sha256(zip_path.read_bytes()).hexdigest()[:40], "content-hash"


def repo_name_from_folder(folder: Path, fallback: str) -> str:
    name = folder.name or fallback
    name = re.sub(r"^\d{8}-\d{6}-", "", name)                 # dashboard upload prefix
    return slug(re.sub(r"-(main|master|[0-9a-f]{7,40})$", "", name)) or fallback


# ---------- extraction (pure functions: easy to test offline) ----------

def walk_tree(root: Path) -> tuple[list[dict], bool]:
    """All files as project-relative POSIX paths. Returns (files, truncated)."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info"))
        for f in sorted(filenames):
            if f in SKIP_DIRS:
                continue
            p = Path(dirpath) / f
            if p.is_symlink():
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            files.append({"path": p.relative_to(root).as_posix(), "size": size})
            if len(files) >= MAX_FILES:
                return files, True
    return files, False


def find_readme(root: Path, tree: list[dict]) -> tuple[str, str | None]:
    """(text, path). Root README first, then docs/README, then any README."""
    readmes = [f["path"] for f in tree if Path(f["path"]).name.lower().startswith("readme")]
    readmes.sort(key=lambda p: (p.count("/"), not p.lower().endswith((".md", ".markdown")), p))
    for path in readmes:
        text = read_text(root / path, README_CHARS)
        if text.strip():
            return text, path
    return "", None


def find_deps(root: Path, tree: list[dict]) -> dict[str, str]:
    return {f["path"]: read_text(root / f["path"], DEP_CHARS)
            for f in tree if Path(f["path"]).name in DEP_FILES and f["path"].count("/") <= 1}


def read_commits(root: Path) -> list[dict]:
    out = git(["log", f"-n{MAX_COMMITS}", "--date=short", "--pretty=format:%H%x1f%an%x1f%ad%x1f%s"], cwd=root)
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f", 3)
        if len(parts) == 4:
            sha, author, date, subject = parts
            commits.append({"sha": sha, "author": author, "date": date, "subject": subject})
    return commits


def pick_key_files(root: Path, tree: list[dict], readme_path: str | None) -> dict[str, str]:
    """Files the analyzer reads, within budget. Writing and entry points first,
    then code, then config; hidden dirs, tests and vendored code last."""
    candidates = [f for f in tree
                  if Path(f["path"]).suffix.lower() in TEXT_EXT
                  and f["path"] != readme_path
                  and Path(f["path"]).name not in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml",
                                                   "poetry.lock", "Cargo.lock", "LICENSE", "LICENSE.md")
                  and 0 < f["size"] < 3_000_000]

    def priority(f):
        path = f["path"]
        suf = Path(path).suffix.lower()
        name = Path(path).stem.lower()
        is_hidden = any(part.startswith(".") for part in path.split("/"))
        is_test = bool(re.search(r"(^|/)(tests?|spec|__tests__)(/|$)|_test\.|\.test\.|test_", path.lower()))
        is_low = path.lower().startswith(LOW_VALUE_DIRS)
        is_doc = suf in DOC_EXT
        is_code = suf in CODE_EXT
        is_entry = any(h in name for h in ENTRY_HINTS)
        return (is_hidden, is_test, is_low, not (is_code or is_doc), not is_entry,
                path.count("/"), suf == ".json", f["size"])

    picked, used = {}, 0
    for f in sorted(candidates, key=priority):
        if used >= KEY_FILES_BUDGET:
            break
        text = read_text(root / f["path"], min(KEY_FILE_CHARS, KEY_FILES_BUDGET - used))
        if text.strip():
            picked[f["path"]] = text
            used += len(text)
    return picked


def language_mix(tree: list[dict]) -> dict[str, int]:
    c = Counter(Path(f["path"]).suffix.lower() or "(none)" for f in tree)
    return dict(c.most_common(10))


def project_kind_hint(tree: list[dict]) -> str:
    """A cheap guess the analyzer can confirm or correct."""
    sufs = Counter(Path(f["path"]).suffix.lower() for f in tree)
    code = sum(v for k, v in sufs.items() if k in CODE_EXT)
    docs = sum(v for k, v in sufs.items() if k in DOC_EXT | {".pdf", ".docx"})
    imgs = sum(v for k, v in sufs.items() if k in IMAGE_EXT)
    if code >= max(3, docs):
        return "software"
    if imgs > max(docs, code) * 2:
        return "visual"
    if sufs.get(".ipynb") or sufs.get(".csv"):
        return "data"
    return "writing"


def extract(root: Path, meta: dict, commits: list[dict]) -> dict:
    tree, truncated = walk_tree(root)
    readme, readme_path = find_readme(root, tree)
    return {
        **meta,   # source_type, owner, repo, url, head_sha, source_ref_kind
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(tree),
        "tree_truncated": truncated,
        "languages": language_mix(tree),
        "kind_hint": project_kind_hint(tree),
        "readme": readme,
        "readme_path": readme_path,
        "images": [f["path"] for f in tree if Path(f["path"]).suffix.lower() in IMAGE_EXT][:40],
        "dependencies": find_deps(root, tree),
        "commits": commits,
        "tree": tree,
        "key_files": pick_key_files(root, tree, readme_path),
    }


def content_hash(root: Path, tree: list[dict]) -> str:
    h = hashlib.sha256()
    for f in tree:
        h.update(f["path"].encode())
        try:
            with open(root / f["path"], "rb") as fh:
                h.update(fh.read(HASH_FILE_CAP))
        except OSError:
            pass
    return h.hexdigest()[:40]


def cache_path(source_type: str, owner: str, repo: str, head_sha: str) -> Path:
    return CACHE_DIR / f"v{CACHE_VERSION}__{source_type}__{slug(owner)}__{slug(repo)}__{head_sha[:12]}.json"


# ---------- agent ----------

class Ingest(BaseAgent):
    agent_id = "A01"
    name = "ingest"
    title = "Read the project"
    requires = ("source",)
    produces = "repo"
    uses_llm = False

    def run(self, ctx: dict) -> dict:
        src = classify(ctx["source"])
        if src["kind"] == "git":
            return self._from_git(src)
        if src["kind"] == "dir":
            return self._from_dir(src)
        return self._from_zip(src)

    def _from_git(self, src: dict) -> dict:
        owner, repo = src["owner"], src["repo"]
        head = git(["ls-remote", src["url"], "HEAD"]).split()
        if not head:
            raise AgentError("repo has no commits yet")
        head_sha = head[0]
        cached = cache_path("git", owner, repo, head_sha)
        if cached.exists():
            return {**json.loads(cached.read_text(encoding="utf-8")), "cache_hit": True}
        tmp = Path(tempfile.mkdtemp(prefix="fc_"))
        try:
            dest = tmp / repo
            git(["clone", f"--depth={MAX_COMMITS}", "--quiet", src["url"], str(dest)])
            meta = {"source_type": "git", "host": src["host"], "owner": owner, "repo": repo,
                    "url": src["web"], "head_sha": head_sha, "source_ref_kind": "commit"}
            data = extract(dest, meta, read_commits(dest))
        finally:
            rmtree(tmp)
        return self._save(data)

    def _from_dir(self, src: dict) -> dict:
        root: Path = src["path"]
        total = 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                try:
                    total += (Path(dirpath) / f).stat().st_size
                except OSError:
                    pass
            if total > LOCAL_MAX_BYTES:
                raise AgentError("folder is larger than 400 MB (excluding node_modules, .git, venv...)")
        commits, head_sha, kind = [], None, "content-hash"
        if (root / ".git").exists() and _has_git():
            try:
                commits = read_commits(root)
                head_sha = git(["rev-parse", "HEAD"], cwd=root).strip()
                kind = "commit"
            except AgentError:
                commits = []
        tree, _ = walk_tree(root)
        dirty_hash = content_hash(root, tree)
        if head_sha is None:
            head_sha = dirty_hash
        cached = cache_path("dir", "local", src["repo"], dirty_hash)
        if cached.exists():
            return {**json.loads(cached.read_text(encoding="utf-8")), "cache_hit": True}
        meta = {"source_type": "dir", "host": None, "owner": "local", "repo": src["repo"],
                "url": str(root), "head_sha": head_sha, "source_ref_kind": kind}
        data = extract(root, meta, commits)
        cached.write_text(json.dumps(data, indent=1), encoding="utf-8")
        return {**data, "cache_hit": False}

    def _from_zip(self, src: dict) -> dict:
        tmp = Path(tempfile.mkdtemp(prefix="fc_"))
        try:
            if src["kind"] == "zip_url":
                zip_path = tmp / "download.zip"
                download_zip(src["url"], zip_path)
                url = src["url"]
            else:
                zip_path = src["path"]
                url = str(zip_path)
            out = tmp / "x"
            zf = safe_extract(zip_path, out)
            head_sha, ref_kind = zip_identity(zf, zip_path)
            zf.close()
            root = zip_root(out)
            owner = src["owner"]
            repo = src["repo"] or repo_name_from_folder(root if root != out else zip_path.with_suffix(""), zip_path.stem)
            cached = cache_path("zip", owner, repo, head_sha)
            if cached.exists():
                return {**json.loads(cached.read_text(encoding="utf-8")), "cache_hit": True}
            meta = {"source_type": "zip", "host": "github.com" if owner not in ("local", "remote") else None,
                    "owner": owner, "repo": repo,
                    "url": f"https://github.com/{owner}/{repo}" if owner not in ("local", "remote") else url,
                    "head_sha": head_sha, "source_ref_kind": ref_kind}
            data = extract(root, meta, commits=[])
        finally:
            rmtree(tmp)
        return self._save(data)

    def _save(self, data: dict) -> dict:
        cache_path(data["source_type"], data["owner"], data["repo"], data["head_sha"]).write_text(
            json.dumps(data, indent=1), encoding="utf-8")
        return {**data, "cache_hit": False}


if __name__ == "__main__":
    ctx = {"source": sys.argv[1] if len(sys.argv) > 1 else "examples/night-shift-thesis"}
    rec = Ingest().execute(ctx)
    print(json.dumps(rec, indent=2))
    if rec["status"] == "success":
        r = ctx["repo"]
        print(f"{r['owner']}/{r['repo']}  {r['source_type']}  ref {r['head_sha'][:12]} ({r['source_ref_kind']})")
        print(f"files {r['file_count']}  kind {r['kind_hint']}  readme {r['readme_path']} ({len(r['readme'])} chars)")
        print(f"key files {list(r['key_files'])}")
