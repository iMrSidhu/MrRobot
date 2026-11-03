import asyncio
import pathlib
import sys

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion import service  # noqa: E402
from ingestion import __main__ as ingestion_main  # noqa: E402
from shared import db  # noqa: E402


def item(rid: int, name: str, stars: int) -> dict:
    return {"id": rid, "full_name": name, "clone_url": f"https://github.com/{name}.git", "stargazers_count": stars}


def fake_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.github.com")


def two_repos(request):
    return httpx.Response(200, json={"items": [item(1, "new/one", 5000), item(2, "new/two", 2000)]})


async def run_pass(tmp_path, handler):
    async with fake_client(handler) as c:
        return await service.run_once(client=c, db_path=tmp_path / "t.db")


def events(tmp_path, type_):
    conn = db.connect(tmp_path / "t.db")
    try:
        return [e for e in db.list_events_since(conn, 0) if e["type"] == type_]
    finally:
        conn.close()


def test_once_enqueues_rows_and_events(tmp_path):
    added = asyncio.run(run_pass(tmp_path, two_repos))
    assert added == 2
    conn = db.connect(tmp_path / "t.db")
    repos = db.list_repos(conn, "QUEUED")
    assert [r["name"] for r in repos] == ["new/one", "new/two"]
    disc = db.list_events_since(conn, 0)
    assert [e["type"] for e in disc] == ["DISCOVERED", "DISCOVERED"]
    assert disc[0]["repo_id"] == 1 and "5000 stars" in disc[0]["message"]
    conn.close()


def test_dedupe_skips_known_repos(tmp_path):
    first = asyncio.run(run_pass(tmp_path, two_repos))
    second = asyncio.run(run_pass(tmp_path, two_repos))
    assert first == 2 and second == 0
    conn = db.connect(tmp_path / "t.db")
    assert len(db.list_repos(conn)) == 2
    assert len(db.list_events_since(conn, 0)) == 2  # no duplicate DISCOVERED events
    conn.close()


def test_rate_limit_event_pause_and_continue(tmp_path, monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)

    def limited(request):
        return httpx.Response(403, json={"message": "slow down"}, headers={"Retry-After": "7"})

    added = asyncio.run(run_pass(tmp_path, limited))
    assert added == 0 and slept == [7]  # slept exactly GitHub's requested time, no crash
    rate = events(tmp_path, "RATE_LIMIT")
    assert len(rate) == 1 and rate[0]["repo_id"] is None
    assert len(events(tmp_path, "DISCOVERED")) == 0

    # loop continues working after the pause: a later good pass still enqueues
    added = asyncio.run(run_pass(tmp_path, two_repos))
    assert added == 2


def test_api_errors_never_crash_the_pass(tmp_path):
    def boom(request):
        return httpx.Response(500, json={"message": "kaboom"})

    assert asyncio.run(run_pass(tmp_path, boom)) == 0

    def refused(request):
        raise httpx.ConnectError("connection refused")

    assert asyncio.run(run_pass(tmp_path, refused)) == 0
    assert len(events(tmp_path, "ERROR")) == 2


def test_main_once_flag(monkeypatch):
    calls = []

    async def fake_once():
        calls.append("once")
        return 1

    monkeypatch.setattr(ingestion_main, "run_once", fake_once)
    assert ingestion_main.main(["--once"]) == 0
    assert calls == ["once"]
