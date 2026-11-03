"""Ingestion service loop (DESIGN.md §2 principle 1 + §5 Steps 2.2-2.3).

GitHub search -> shared DB: run each configured keyword query, skip repos already
known (dedupe by name), insert new ones as QUEUED and log a DISCOVERED event each.
The loop must never crash on API errors; RateLimited pauses the pass for the
wait GitHub asks for.
"""
from __future__ import annotations

import asyncio

from ingestion.github_client import RateLimited, search_repositories
from shared import db
from shared.config import settings
from shared.logging import get_logger

log = get_logger("ingestion")


async def run_once(*, client=None, db_path=None) -> int:
    """One polling pass. Returns the number of newly queued repos (0 on any error)."""
    conn = db.connect(db_path or settings.db_path)
    try:
        db.init_db(conn)
        try:
            candidates = await search_repositories(
                settings.search_keywords, settings.min_stars, client=client
            )
        except RateLimited as rl:
            log.warning(f"rate limited, sleeping {rl.wait_seconds}s")
            db.add_event(conn, None, "RATE_LIMIT", f"ingestion paused {rl.wait_seconds}s", {"wait_seconds": rl.wait_seconds})
            await asyncio.sleep(rl.wait_seconds)
            return 0
        except Exception as exc:  # noqa: BLE001 — the loop must never die on API errors
            log.error(f"search pass failed: {exc!r}")
            db.add_event(conn, None, "ERROR", f"search pass failed: {exc!r}")
            return 0

        added = 0
        for c in candidates:
            if db.add_repo_if_new(conn, c.id, c.name, c.url, c.stars) is None:
                # Known repo: the search result still carries a fresh star count,
                # so keep a sample for the growth chart (one row per pass).
                db.record_star_sample(conn, c.id, c.stars)
                continue  # known repo, skip re-queueing (Step 2.2)
            db.add_event(conn, c.id, "DISCOVERED", f"{c.name} ({c.stars} stars)", {"url": c.url, "stars": c.stars})
            added += 1
        log.info(f"pass complete: {added} new repos queued, {len(candidates)} candidates seen")
        return added
    finally:
        conn.close()


async def run_forever(*, client=None, db_path=None) -> None:
    """Poll pass -> wait POLL_INTERVAL_SEC -> repeat."""
    while True:
        await run_once(client=client, db_path=db_path)
        await asyncio.sleep(settings.poll_interval_sec)
