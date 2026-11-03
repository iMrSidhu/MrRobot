"""Dashboard API (design 5 Phase 5.2): read-only FastAPI over the sentinel DB.

Endpoints: ``/health``, ``/repos``, ``/repos/{id}`` (repo row plus the
synthesis and security JSON artifacts), ``/events/stream`` (Server-Sent
Events from the events table, resumable via Last-Event-ID). No business
logic here - workers own the pipeline, this only reports what they wrote.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from shared import db
from shared.config import settings

# Design 3 (5): the HUD must feel live. Polling every 0.25s keeps delivery
# of a committed event well under the 1s acceptance budget.
POLL_INTERVAL_SEC = 0.25


def _load_json(path: Optional[str]) -> Optional[dict]:
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _security_json_path(row: dict) -> Optional[Path]:
    """Sidecar guess: llm_engine writes <base>.synthesis.json and
    <base>.security.json next to each other (its service.py), and the DB
    stores the synthesis path - so the security JSON is its sibling.
    shortcut: relies on that co-location; move to an explicit DB column if
    artifacts ever split."""
    synth = row.get("synthesis_path")
    if not synth or not synth.endswith(".synthesis.json"):
        return None
    p = Path(synth)
    candidate = p.with_name(p.name[: -len(".synthesis.json")] + ".security.json")
    return candidate if candidate.is_file() else None


def _sse(row: dict) -> str:
    data = {
        "repo_id": row["repo_id"],
        "type": row["type"],
        "message": row["message"],
        "payload": json.loads(row["payload_json"]) if row["payload_json"] else {},
        "timestamp": row["timestamp"],
    }
    return f"id: {row['id']}\nevent: {row['type']}\ndata: {json.dumps(data)}\n\n"


def create_app(db_path: Optional[str] = None) -> FastAPI:
    """App factory so tests (and other DB files) get their own read-only view."""
    path = str(db_path or settings.db_path)
    app = FastAPI(title="GitHub Capability & Security Sentinel", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "db": path}

    @app.get("/repos")
    def repos() -> list[dict]:
        conn = db.connect(path)
        try:
            return db.list_repos(conn)
        finally:
            conn.close()

    @app.get("/repos/{repo_id}")
    def repo_detail(repo_id: int) -> dict:
        conn = db.connect(path)
        try:
            row = db.get_repo(conn, repo_id)
        finally:
            conn.close()
        if row is None:
            raise HTTPException(status_code=404, detail=f"no repo {repo_id}")
        sec_path = _security_json_path(row)
        return {
            "repo": row,
            "synthesis": _load_json(row.get("synthesis_path")),
            "security": _load_json(str(sec_path)) if sec_path else None,
        }

    @app.get("/events/stream")
    def events_stream(request: Request) -> StreamingResponse:
        resume = request.headers.get("last-event-id")
        after = int(resume) if resume and resume.isdigit() else 0
        return StreamingResponse(
            _event_stream(path, after),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


async def _event_stream(path: str, after: int) -> AsyncIterator[str]:
    """Async generator: Starlette cancels it on client disconnect (a sync
    generator would run to completion - i.e. never - hence this must stay
    async). The sqlite poll is sub-millisecond, fine on the event loop."""
    conn = db.connect(path)
    try:
        cursor = after
        while True:
            rows = db.list_events_since(conn, cursor)
            if rows:
                for row in rows:
                    cursor = row["id"]
                    yield _sse(row)
                continue
            await asyncio.sleep(POLL_INTERVAL_SEC)
    finally:
        conn.close()


# For ``uvicorn dashboard.api:app`` (design 5 Phase 5.2).
app = create_app()
