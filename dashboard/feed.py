"""Live event feed for the Streamlit dashboard (design 5 Phase 5.3).

Streamlit cannot consume SSE natively, so a background thread reads
``/events/stream`` from the API and appends parsed events to a shared
FeedState; the page renders it on a timer. If the stream errors or ends
(no server, crash, proxy cut) the thread degrades to polling the events
table directly - the dashboard never stops updating.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Callable, Iterator, Optional

from shared import db

MAX_EVENTS_KEPT = 500  # ring-buffer size in the browser session


class FeedState:
    """Mutable store shared between the feed thread and the page script."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.mode = "connecting"  # connecting | live | polling | stopped
        self.error = ""
        self.last_id = 0
        self._lock = threading.Lock()

    def add(self, event: dict) -> bool:
        """Append if newer than what we have; returns whether it was new."""
        with self._lock:
            if event["id"] <= self.last_id:
                return False
            self.last_id = event["id"]
            self.events.append(event)
            if len(self.events) > MAX_EVENTS_KEPT:
                del self.events[: -MAX_EVENTS_KEPT]
            return True

    def snapshot(self) -> tuple[list[dict], str, str]:
        with self._lock:
            return list(self.events), self.mode, self.error


def parse_sse_lines(lines: Iterator[str]) -> Iterator[dict]:
    """Minimal SSE frame parser: blank line ends a frame; ``data:`` holds
    the event JSON the API writes (id/event fields are inside it)."""
    data: Optional[str] = None
    event_id: Optional[int] = None
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        line = line.rstrip("\r")
        if not line:
            if data is not None:
                try:
                    ev = json.loads(data)
                    ev["id"] = event_id if event_id is not None else ev.get("id", 0)
                    yield ev
                except ValueError:
                    pass
            data, event_id = None, None
            continue
        if line.startswith("id:"):
            try:
                event_id = int(line[3:].strip())
            except ValueError:
                event_id = None
        elif line.startswith("data:"):
            chunk = line[5:].strip()
            data = chunk if data is None else data + chunk
    # no trailing blank line: flush the last frame if complete
    if data is not None:
        try:
            ev = json.loads(data)
            ev["id"] = event_id if event_id is not None else ev.get("id", 0)
            yield ev
        except ValueError:
            pass


def _db_poll_loop(state: FeedState, db_path: str, stop: threading.Event,
                  poll_interval: float, sleep) -> None:
    cursor = state.last_id
    conn = db.connect(db_path)
    try:
        while not stop.is_set():
            rows = db.list_events_since(conn, cursor)
            for row in rows:
                cursor = row["id"]
                state.add({
                    "id": row["id"],
                    "repo_id": row["repo_id"],
                    "type": row["type"],
                    "message": row["message"],
                    "timestamp": row["timestamp"],
                })
            with state._lock:
                state.mode = "polling"
            sleep(poll_interval)
    finally:
        conn.close()
    with state._lock:
        state.mode = "stopped"


def feed_loop(state: FeedState, *, url: str, db_path: str,
              opener: Callable[[str, Optional[int]], Iterator[str]],
              stop: threading.Event,
              poll_interval: float = 1.0, sleep=time.sleep) -> None:
    """Thread body: consume SSE via `opener(url, last_event_id)`; any
    failure or clean end drops to DB polling for the rest of the session.
    shortcut: no retry-back-to-SSE; the polling fallback is complete on its
    own. Add a reconnect-with-backoff wrapper if live-mode drops prove
    annoying."""
    last_id: Optional[int] = None
    try:
        for ev in parse_sse_lines(opener(url, last_id)):
            if stop.is_set():
                return
            if state.add(ev):
                with state._lock:
                    if state.mode != "live":
                        state.mode = "live"
        # opener ended (server closed the stream)
        state.error = "stream ended - polling DB instead"
    except Exception as exc:  # noqa: BLE001 - thread must die quietly into fallback
        state.error = f"{type(exc).__name__}: {exc}"
    with state._lock:
        state.mode = "polling"
    # replay anything missed during the drop, then keep polling
    conn = db.connect(db_path)
    try:
        start = state.last_id
        for row in db.list_events_since(conn, start):
            state.add({"id": row["id"], "repo_id": row["repo_id"],
                       "type": row["type"], "message": row["message"],
                       "timestamp": row["timestamp"]})
    finally:
        conn.close()
    _db_poll_loop(state, db_path, stop, poll_interval, sleep)


def start_feed(state: FeedState, stop: threading.Event, **kwargs) -> threading.Thread:
    t = threading.Thread(target=feed_loop, args=(state,), kwargs=kwargs, daemon=True)
    t.start()
    return t
