"""SQLite state: repo queue + event log (DESIGN.md §2 — services decouple through this DB).

WAL mode + busy timeout so independent services/processes can read and write concurrently.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from shared.models import STATUSES

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repositories (
    id                   INTEGER PRIMARY KEY,
    name                 TEXT NOT NULL UNIQUE,
    url                  TEXT NOT NULL,
    stars                INTEGER NOT NULL,
    status               TEXT NOT NULL,
    synthesis_path       TEXT,
    security_report_path TEXT,
    security_json_path   TEXT,
    adoption_json_path   TEXT,
    error                TEXT,
    timestamp            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id      INTEGER,
    type         TEXT NOT NULL,
    message      TEXT NOT NULL,
    payload_json TEXT,
    timestamp    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS star_samples (
    repo_id    INTEGER NOT NULL,
    stars      INTEGER NOT NULL,
    sampled_at TEXT NOT NULL,
    PRIMARY KEY (repo_id, sampled_at)
);
"""


def _check_status(status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"bad status {status!r}; expected one of {STATUSES}")


def connect(db_path) -> sqlite3.Connection:
    p = Path(db_path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(conn) -> None:
    conn.executescript(_SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(repositories)")}
    if "security_json_path" not in cols:  # pre-v1.2 databases: add the column in place
        conn.execute("ALTER TABLE repositories ADD COLUMN security_json_path TEXT")
    if "adoption_json_path" not in cols:  # pre-v2 databases: requested adoption artifacts
        conn.execute("ALTER TABLE repositories ADD COLUMN adoption_json_path TEXT")
    conn.commit()


def add_repo_if_new(conn, id: int, name: str, url: str, stars: int, status: str = "QUEUED"):
    """Dedupe by name (DESIGN.md §5 Step 2.2): returns the row dict, or None if known."""
    cur = conn.execute(
        "INSERT INTO repositories (id, name, url, stars, status) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(name) DO NOTHING",
        (id, name, url, stars, status),
    )
    conn.commit()
    return get_repo(conn, id) if cur.rowcount else None


def claim_next(conn, from_status: str, to_status: str):
    """Atomic handoff of one repo, highest stars first: a single UPDATE...RETURNING statement,
    serialized by SQLite — two concurrent claimers can never get the same row. Returns dict/None."""
    _check_status(from_status)
    _check_status(to_status)
    cur = conn.execute(
        "UPDATE repositories"
        " SET status = ?, timestamp = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
        " WHERE id = (SELECT id FROM repositories WHERE status = ? ORDER BY stars DESC, id LIMIT 1)"
        " RETURNING *",
        (to_status, from_status),
    )
    row = cur.fetchone()
    cur.close()  # finalize the RETURNING statement, otherwise commit() errors
    conn.commit()
    return dict(row) if row else None


def reclaim_stale(conn, from_status: str, to_status: str, older_than_sec: int = 300) -> int:
    """Crashed-worker recovery: rows that entered `from_status` more than
    `older_than_sec` ago but never left it are handed back to `to_status` so the
    next claim re-runs them (every stage is idempotent). Call at the START of a
    drain pass only: while a row is in flight its worker is busy draining and
    cannot reclaim, so a slow-but-alive run (model calls are uncapped) is never
    stolen. 300s covers supervisor restart jitter.
    shortcut: assumes one worker process per service (VRAM lock already does);
    add a per-worker claim token to the row before supporting runners."""
    _check_status(from_status)
    _check_status(to_status)
    rows = conn.execute(
        "UPDATE repositories"
        " SET status = ?, timestamp = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
        " WHERE status = ? AND timestamp < strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)"
        " RETURNING id, name",
        (to_status, from_status, f"-{older_than_sec} seconds"),
    ).fetchall()
    for r in rows:
        add_event(conn, r["id"], "RECLAIMED",
                  f"{r['name']}: worker died in {from_status}, requeued to {to_status}")
    conn.commit()
    return len(rows)


def set_status(conn, repo_id: int, status: str, *, error=None, synthesis_path=None,
               security_report_path=None, security_json_path=None) -> None:
    """Update status; optional fields are merged in (None keeps the previous value)."""
    _check_status(status)
    conn.execute(
        "UPDATE repositories SET status = ?, timestamp = strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
        " error = COALESCE(?, error), synthesis_path = COALESCE(?, synthesis_path),"
        " security_report_path = COALESCE(?, security_report_path),"
        " security_json_path = COALESCE(?, security_json_path) WHERE id = ?",
        (status, error, synthesis_path, security_report_path, security_json_path, repo_id),
    )
    conn.commit()


def set_adoption_path(conn, repo_id: int, path: str) -> None:
    """Record a requested adoption artifact without touching the pipeline status."""
    conn.execute("UPDATE repositories SET adoption_json_path = ? WHERE id = ?", (path, repo_id))
    conn.commit()


def record_star_sample(conn, repo_id: int, stars: int) -> None:
    """One star observation per repo per pass; also refreshes the current count."""
    conn.execute(
        "INSERT OR REPLACE INTO star_samples (repo_id, stars, sampled_at)"
        " VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
        (repo_id, int(stars)),
    )
    conn.execute("UPDATE repositories SET stars = ? WHERE id = ?", (int(stars), repo_id))
    conn.commit()


def list_star_samples(conn, repo_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT stars, sampled_at FROM star_samples WHERE repo_id = ? ORDER BY sampled_at",
        (repo_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def repos_due_for_star_sample(conn, interval_seconds: int, limit: int) -> list[dict]:
    """Repos whose newest sample is older than `interval_seconds` (never sampled first)."""
    rows = conn.execute(
        """
        SELECT r.id, r.name
        FROM repositories r
        LEFT JOIN (
            SELECT repo_id, MAX(sampled_at) AS last_at FROM star_samples GROUP BY repo_id
        ) s ON s.repo_id = r.id
        WHERE s.last_at IS NULL
           OR s.last_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)
        ORDER BY s.last_at IS NOT NULL, s.last_at
        LIMIT ?
        """,
        (f"-{int(interval_seconds)} seconds", int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def add_event(conn, repo_id, type: str, message: str, payload: dict | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO events (repo_id, type, message, payload_json) VALUES (?, ?, ?, ?)",
        (repo_id, type, message, json.dumps(payload) if payload is not None else None),
    )
    conn.commit()
    return cur.lastrowid


def list_events_since(conn, last_id: int) -> list[dict]:
    """Event feed for the dashboard/SSE, in insertion order (id is autoincrement)."""
    rows = conn.execute("SELECT * FROM events WHERE id > ? ORDER BY id", (last_id,)).fetchall()
    return [dict(r) for r in rows]


def get_repo(conn, repo_id: int):
    row = conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
    return dict(row) if row else None


def list_repos(conn, status: str | None = None) -> list[dict]:
    if status is not None:
        _check_status(status)
        rows = conn.execute("SELECT * FROM repositories WHERE status = ? ORDER BY id", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM repositories ORDER BY id").fetchall()
    return [dict(r) for r in rows]
