"""Dashboard API (design 5 Phase 5.2): read-only FastAPI over the sentinel DB.

Endpoints: ``/health``, ``/repos``, ``/repos/{id}`` (repo row plus the
synthesis and security JSON artifacts), ``/repos/{id}/report`` (vault
Markdown, guarded to VAULT_DIR), ``/events/stream`` (Server-Sent
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


def load_json(path: Optional[str]) -> Optional[dict]:
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sse(row: dict) -> str:
    data = {
        "repo_id": row["repo_id"],
        "type": row["type"],
        "message": row["message"],
        "payload": json.loads(row["payload_json"]) if row["payload_json"] else {},
        "timestamp": row["timestamp"],
    }
    return f"id: {row['id']}\nevent: {row['type']}\ndata: {json.dumps(data)}\n\n"


def create_app(db_path: Optional[str] = None,
               vault_dir: Optional[str] = None,
               cache_dir: Optional[str] = None) -> FastAPI:
    """App factory so tests (and other DB files) get their own read-only view.
    ``vault_dir`` scopes the report endpoint's traversal guard (design 7);
    ``cache_dir`` is where requested adoption artifacts and clones live."""
    path = str(db_path or settings.db_path)
    vault_root = Path(vault_dir or settings.vault_dir).resolve()
    repo_cache = str(cache_dir or settings.repo_cache_dir)
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
        return {
            "repo": row,
            "synthesis": load_json(row.get("synthesis_path")),
            "security": load_json(row.get("security_json_path")),
        }

    @app.get("/repos/{repo_id}/stars")
    def repo_stars(repo_id: int) -> dict:
        """Star observations for the growth chart (one sample per ingestion pass)."""
        conn = db.connect(path)
        try:
            row = db.get_repo(conn, repo_id)
            samples = db.list_star_samples(conn, repo_id) if row else []
        finally:
            conn.close()
        if row is None:
            raise HTTPException(status_code=404, detail=f"no repo {repo_id}")
        return {
            "repo_id": repo_id,
            "stars": row.get("stars"),
            "samples": samples,
            "state": "available" if len(samples) >= 2 else "collecting",
        }

    @app.get("/repos/{repo_id}/adoption")
    def repo_adoption(repo_id: int) -> dict:
        """Requested adoption artifact, or an explicit 'not generated' state."""
        conn = db.connect(path)
        try:
            row = db.get_repo(conn, repo_id)
        finally:
            conn.close()
        if row is None:
            raise HTTPException(status_code=404, detail=f"no repo {repo_id}")
        artifact = row.get("adoption_json_path")
        if not artifact:
            return {"repo": row, "state": "not_generated", "adoption": None}
        target = Path(artifact)
        if not target.is_file():
            return {"repo": row, "state": "missing", "adoption": None}
        data = load_json(str(target))
        return {"repo": row, "state": "available" if data else "invalid", "adoption": data}

    @app.post("/repos/{repo_id}/adoption")
    def repo_adoption_run(repo_id: int) -> dict:
        """Generate the adoption report on request (deterministic, no LLM)."""
        conn = db.connect(path)
        try:
            row = db.get_repo(conn, repo_id)
        finally:
            conn.close()
        if row is None:
            raise HTTPException(status_code=404, detail=f"no repo {repo_id}")
        try:
            report = run_adoption(row, cache_dir=repo_cache, db_path=path)
        except CloneError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"repo": row, "state": "available", "adoption": report}

    @app.get("/repos/{repo_id}/report")
    def repo_report(repo_id: int) -> dict:
        conn = db.connect(path)
        try:
            row = db.get_repo(conn, repo_id)
        finally:
            conn.close()
        if row is None:
            raise HTTPException(status_code=404, detail=f"no repo {repo_id}")
        md_path = row.get("security_report_path")
        if not md_path:
            raise HTTPException(status_code=404,
                                detail=f"no report yet (status {row['status']})")
        target = Path(md_path).resolve()
        # Traversal guard: the DB is trusted-ish but a hostile/pulled row must
        # never make the API read outside VAULT_DIR (design 7).
        if not target.is_relative_to(vault_root):
            raise HTTPException(status_code=400,
                                detail="report path outside vault dir")
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"report file missing: {md_path}")
        return {"path": str(target),
                "markdown": target.read_text(encoding="utf-8")}

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
