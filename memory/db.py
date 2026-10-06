"""
db - SQLite memory: what you have already published, so Facetcast never repeats itself.

Four tables:
  projects  one row per project ingested (git repo, zip or local folder)
  runs      one row per finished run (full context kept for audit)
  angles    every angle proposed; unused ones stay 'queued' for a later run
  posts     every approved piece of content, one row per platform, with its embedding

init() is idempotent and migrates older databases in place.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id           TEXT PRIMARY KEY,              -- "owner/name" or "local/name"
    url          TEXT NOT NULL,
    last_ref     TEXT,
    ingested_at  TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id),
    status       TEXT NOT NULL DEFAULT 'done',
    platforms    TEXT,                          -- "linkedin,x,github"
    context_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS angles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT NOT NULL REFERENCES projects(id),
    run_id       TEXT REFERENCES runs(id),
    title        TEXT NOT NULL,
    summary      TEXT,
    score        REAL,
    dedup_status TEXT,
    status       TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','used','dropped')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT NOT NULL REFERENCES projects(id),
    run_id       TEXT REFERENCES runs(id),
    angle_id     INTEGER REFERENCES angles(id),
    platform     TEXT NOT NULL DEFAULT 'linkedin',
    text         TEXT NOT NULL,
    embedding    BLOB,                          -- float32 bytes; never goes into run context
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Rows behave like dicts; foreign keys enforced.
    journal_mode=TRUNCATE works on shared/synced folders that forbid deleting files."""
    conn = sqlite3.connect(path or settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = TRUNCATE")
    return conn


def init(path: Path | str | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def tables(path: Path | str | None = None) -> list[str]:
    with connect(path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                            "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    return [r["name"] for r in rows]


# ---------- writes (each takes an open connection so a caller can do one transaction) ----------

def upsert_project(conn, project_id: str, url: str, last_ref: str | None, ingested_at: str | None) -> None:
    conn.execute(
        "INSERT INTO projects (id, url, last_ref, ingested_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET url=excluded.url, last_ref=excluded.last_ref, "
        "ingested_at=excluded.ingested_at", (project_id, url, last_ref, ingested_at))


def finish_run(conn, run_id: str, project_id: str, platforms: str, context_json: str) -> None:
    conn.execute(
        "INSERT INTO runs (id, project_id, status, platforms, context_json) VALUES (?, ?, 'done', ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET status='done', platforms=excluded.platforms, "
        "context_json=excluded.context_json, updated_at=datetime('now')",
        (run_id, project_id, platforms, context_json))


def insert_angle(conn, project_id: str, run_id: str | None, title: str, summary: str | None,
                 score: float | None, dedup_status: str | None, status: str) -> int:
    cur = conn.execute(
        "INSERT INTO angles (project_id, run_id, title, summary, score, dedup_status, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", (project_id, run_id, title, summary, score, dedup_status, status))
    return cur.lastrowid


def insert_post(conn, project_id: str, run_id: str | None, angle_id: int | None, platform: str,
                text: str, embedding: bytes | None) -> int:
    cur = conn.execute(
        "INSERT INTO posts (project_id, run_id, angle_id, platform, text, embedding) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, run_id, angle_id, platform, text, embedding))
    return cur.lastrowid


# ---------- reads ----------

def recent_posts(conn, limit: int = 60) -> list[dict]:
    """Most recent posts across ALL projects (dedup must see everything you've published)."""
    rows = conn.execute(
        "SELECT p.id, p.project_id, p.platform, p.text, p.created_at, a.title AS angle_title, "
        "       p.embedding IS NOT NULL AS has_embedding "
        "FROM posts p LEFT JOIN angles a ON a.id = p.angle_id ORDER BY p.id DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "has_embedding": bool(r["has_embedding"])} for r in rows]


def queued_angles(conn, project_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, title, summary, score, dedup_status FROM angles "
        "WHERE project_id = ? AND status = 'queued' ORDER BY score DESC, id", (project_id,)).fetchall()
    return [dict(r) for r in rows]


def post_vectors(conn, post_ids: list[int]) -> dict[int, bytes]:
    if not post_ids:
        return {}
    marks = ",".join("?" * len(post_ids))
    rows = conn.execute(f"SELECT id, embedding FROM posts WHERE id IN ({marks}) AND embedding IS NOT NULL",
                        post_ids).fetchall()
    return {r["id"]: r["embedding"] for r in rows}


def overview(limit: int = 60) -> dict:
    if not Path(settings.DB_PATH).exists():
        return {"posts": [], "queued": [], "counts": {"posts": 0, "queued": 0, "projects": 0}}
    init()
    with connect() as conn:
        posts = [dict(r) for r in conn.execute(
            "SELECT id, project_id, platform, substr(text, 1, 180) AS preview, length(text) AS chars, "
            "embedding IS NOT NULL AS embedded, created_at FROM posts ORDER BY id DESC LIMIT ?", (limit,))]
        queued = [dict(r) for r in conn.execute(
            "SELECT project_id, title, score FROM angles WHERE status='queued' ORDER BY score DESC LIMIT ?", (limit,))]
        projects = conn.execute("SELECT count(*) FROM projects").fetchone()[0]
        n_posts = conn.execute("SELECT count(*) FROM posts").fetchone()[0]
        n_queued = conn.execute("SELECT count(*) FROM angles WHERE status='queued'").fetchone()[0]
    return {"posts": posts, "queued": queued,
            "counts": {"posts": n_posts, "queued": n_queued, "projects": projects}}


if __name__ == "__main__":
    init()
    print(f"database  {settings.DB_PATH}")
    for t in tables():
        with connect() as c:
            print(f"table     {t:<9} rows={c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
