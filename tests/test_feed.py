"""Feed thread mechanics: SSE frame parsing, live updates, polling
fallback. All synchronous - the injected opener/sleep keep it deterministic."""
import json
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dashboard import feed
from shared import db


def _frame(evid, etype="DISCOVERED", message="m", repo_id=None):
    data = json.dumps({"repo_id": repo_id, "type": etype, "message": message,
                       "payload": {}, "timestamp": "2026-11-03T10:00:00"})
    return [f"id: {evid}", f"event: {etype}", f"data: {data}", ""]


def test_parse_sse_lines_basic_and_multiline_data():
    lines = _frame(1, message="one") + ["id: 2", "data: " + json.dumps(
        {"repo_id": None, "type": "X", "message": "part1"}
    )[:20], "data: " + json.dumps({"repo_id": None, "type": "X", "message": "part1"})[20:], ""]
    events = list(feed.parse_sse_lines(iter(lines)))
    assert [e["id"] for e in events] == [1, 2]
    assert events[0]["message"] == "one"
    assert events[1]["message"] == "part1"


def test_parse_sse_lines_skips_garbage_and_flushes_trailing_frame():
    lines = ["data: not-json", "", "id: 9", "data: " + json.dumps({"type": "T", "message": "m"})]
    events = list(feed.parse_sse_lines(iter(lines)))
    assert len(events) == 1 and events[0]["id"] == 9


def _mkdb(tmp_path):
    path = tmp_path / "feed.db"
    conn = db.connect(path)
    db.init_db(conn)
    return path, conn


def test_feed_loop_streams_live_then_polls_missed_events(tmp_path):
    path, conn = _mkdb(tmp_path)
    db.add_repo_if_new(conn, 1, "acme/rover", "u", 1500)
    eid1 = db.add_event(conn, 1, "DISCOVERED", "via sse")
    conn.close()
    stop = threading.Event()
    state = feed.FeedState()

    def opener(url, last_event_id):
        yield from _frame(eid1, repo_id=1, message="via sse")
        # stream then dies; a DB event that appeared during the drop:
        conn2 = db.connect(path)
        db.add_event(conn2, 1, "ANALYSIS_START", "missed me?")
        conn2.close()

    def sleep(_s):
        stop.set()  # end the poll loop after one pass

    feed.feed_loop(state, url="x", db_path=str(path), opener=opener,
                   stop=stop, sleep=sleep)
    messages = [e["message"] for e in state.events]
    assert "via sse" in messages                      # live path
    assert "missed me?" in messages                   # replay after drop
    assert messages.count("via sse") == 1             # replay deduped
    assert state.mode == "stopped"


def test_add_dedupes_by_id_and_advances_last_id():
    state = feed.FeedState()
    assert state.add({"id": 1, "repo_id": None, "type": "T", "message": "a", "timestamp": ""})
    assert not state.add({"id": 1, "repo_id": None, "type": "T", "message": "a", "timestamp": ""})
    assert state.last_id == 1


def test_feed_loop_falls_back_to_db_when_stream_fails(tmp_path):
    path, conn = _mkdb(tmp_path)
    db.add_repo_if_new(conn, 1, "acme/rover", "u", 1500)
    db.add_event(conn, 1, "DISCOVERED", "only in db")
    conn.close()
    stop = threading.Event()
    state = feed.FeedState()

    def boom_opener(url, last_event_id):
        raise ConnectionError("no api running")
        yield  # pragma: no cover - makes it a generator

    feed.feed_loop(state, url="x", db_path=str(path), opener=boom_opener,
                   stop=stop, sleep=lambda s: stop.set())
    assert [e["message"] for e in state.events] == ["only in db"]
    assert state.mode == "stopped"
    assert "ConnectionError" in state.error
