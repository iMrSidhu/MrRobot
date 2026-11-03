"""Processor service loop (DESIGN.md section 2 principles 1-2, section 3 step 2).

Claims QUEUED -> CLONING, clones safely, filters/chunks the code, saves the
ProcessedRepo JSON next to the clone in the cache dir, marks PROCESSED, and
always deletes the clone directory. Any failure is circuit-broken per
principle 2: the repo gets FAILED_AUDIT status + error + event, and the loop
keeps going. Runs as its own independent process (principle 1); all work is
blocking subprocess/file IO, so this is a plain sync loop.
"""
import time
from pathlib import Path

from processor.chunker import process_repo
from processor.clone import clone_repo, cleanup, sanitize_dir_name
from shared import db
from shared.config import settings
from shared.logging import get_logger

logger = get_logger("processor")

PROCESSED_SUFFIX = ".processed.json"


def processed_json_path(name: str, cache_dir: Path | str | None = None) -> Path:
    """Convention: <cache_dir>/<sanitized repo name>.processed.json (survives clone cleanup)."""
    root = Path(cache_dir or settings.repo_cache_dir)
    return root / (sanitize_dir_name(name) + PROCESSED_SUFFIX)


def _process_one(conn, repo: dict, cache_dir) -> bool:
    """Process one claimed repo; returns True on success. Never raises."""
    repo_id, name, url = repo["id"], repo["name"], repo["url"]
    dest = None
    try:
        dest = clone_repo(url, name, dest_root=cache_dir)
        processed = process_repo(repo_id, name, dest)
        out = processed_json_path(name, cache_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(processed.model_dump_json(), encoding="utf-8")
        db.set_status(conn, repo_id, "PROCESSED")
        logger.info(f"{name} -> PROCESSED ({out.name})")
        return True
    except Exception as exc:
        try:
            db.set_status(conn, repo_id, "FAILED_AUDIT", error=f"{type(exc).__name__}: {exc}")
            db.add_event(conn, repo_id, "FAILED_AUDIT", f"{name}: {exc}")
        except Exception:  # DB itself sick — log and let the loop live anyway
            logger.exception("could not record FAILED_AUDIT for repo %s", repo_id)
        logger.warning(f"{name} -> FAILED_AUDIT ({exc})")
        return False
    finally:
        if dest is not None:
            cleanup(dest)


def run_once(db_path: Path | str | None = None,
             cache_dir: Path | str | None = None) -> int:
    """Drain everything currently QUEUED; returns the number processed OK."""
    conn = db.connect(Path(db_path or settings.db_path))
    db.init_db(conn)
    db.reclaim_stale(conn, "CLONING", "QUEUED")  # crashed-worker recovery
    processed = 0
    while True:
        repo = db.claim_next(conn, "QUEUED", "CLONING")
        if repo is None:
            break
        processed += _process_one(conn, repo, cache_dir)
    conn.close()
    return processed


def run_forever(db_path: Path | str | None = None,
                cache_dir: Path | str | None = None) -> None:
    """Worker loop: process queue backlogs immediately, idle-poll otherwise."""
    while True:
        if run_once(db_path, cache_dir) == 0:
            time.sleep(settings.poll_interval_sec)
