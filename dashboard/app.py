"""Streamlit HUD (design 5 Phase 5.3).

Three areas: left = live event radar (SSE via background thread, DB-polling
fallback from dashboard/feed.py, refreshed by a 1s fragment timer);
center = Marketing-vs-Reality split card + capability tag cloud for the
selected repo; right = vulnerability table by severity with mitigation
action items. Center+right re-read the DB and artifact JSONs on a 2s
fragment timer, so a finished analysis shows up without a page reload.
All DB reads are read-only.

Env overrides: SENTINEL_DB_PATH, SENTINEL_API_URL, SENTINEL_FEED=off
(disables the SSE thread and reads events straight from the DB - used by
tests and handy when the API is not running).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import streamlit as st

from dashboard.api import load_json
from dashboard.feed import FeedState, start_feed
from shared import db
from shared.config import settings

SEVERITY_DOT = {"CRITICAL": "red", "HIGH": "orange", "MEDIUM": "gold", "LOW": "green"}
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
FEED_TAIL = 60


def _db_path() -> str:
    return os.environ.get("SENTINEL_DB_PATH") or str(settings.db_path)


def _api_url() -> str:
    return os.environ.get("SENTINEL_API_URL", "http://localhost:8000/events/stream")


def _feed_enabled() -> bool:
    return os.environ.get("SENTINEL_FEED", "on").lower() != "off"


def _load_repos(path: str) -> list[dict]:
    conn = db.connect(path)
    try:
        return db.list_repos(conn)
    finally:
        conn.close()


def _load_events(path: str) -> list[dict]:
    conn = db.connect(path)
    try:
        return db.list_events_since(conn, 0)
    finally:
        conn.close()


def _fmt_event(ev: dict, names: dict) -> str:
    who = names.get(ev.get("repo_id"), "system")
    ts = str(ev.get("timestamp", ""))[11:19]
    return f"[{ts}] {ev.get('type', '?'):<14} {who} - {ev.get('message', '')}"


def _get_feed_state():
    """Start the SSE/polling thread once per browser session."""
    if not _feed_enabled():
        return None
    if "feed_state" not in st.session_state:
        st.session_state.feed_state = FeedState()
        st.session_state.feed_stop = threading.Event()
        # daemon thread; dies with the server process. shortcut: no explicit
        # session-shutdown hook - Streamlit gives us a reliable disconnect event.
        start_feed(
            st.session_state.feed_state,
            st.session_state.feed_stop,
            url=_api_url(),
            db_path=_db_path(),
            opener=_http_opener,
        )
    return st.session_state.feed_state


def _http_opener(url: str, last_event_id):
    """Blocking SSE reader for the feed thread (httpx sync stream)."""
    import httpx

    headers = {"Accept": "text/event-stream"}
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    with httpx.stream("GET", url, headers=headers, timeout=httpx.Timeout(30.0, read=None)) as resp:
        resp.raise_for_status()
        yield from resp.iter_lines()


st.set_page_config(page_title="Sentinel HUD", layout="wide")
st.title(":material/shield: GitHub Capability & Security Sentinel")

path = _db_path()
repos = _load_repos(path)
names = {r["id"]: r["name"] for r in repos}

# ---------- left: live event radar ----------
col_feed, col_mid, col_right = st.columns([1.05, 1.35, 1.25], border=False)


@st.fragment(run_every="1s")
def event_radar() -> None:
    with col_feed:
        st.subheader("Event radar")
        state = _get_feed_state()
        if state is not None:
            events, mode, error = state.snapshot()
            badge = {"live": ":material/broadcast_on_personal: live (SSE)",
                     "polling": ":material/timer: DB polling fallback",
                     "connecting": ":material/hourglass_top: connecting..."}.get(mode, mode)
            st.caption(f"**{badge}**" + (f" - {error}" if error and mode != "live" else ""))
            tail = events[-FEED_TAIL:]
        else:
            tail = _load_events(path)[-FEED_TAIL:]
            st.caption(":material/database: direct DB read (feed thread off)")
        if not tail:
            st.info("No events yet. Waiting for ingestion... or run `python scripts/seed_demo.py`.")
            return
        st.code("\n".join(_fmt_event(ev, names) for ev in reversed(tail)), language=None)


event_radar()

# ---------- center + right: one 2s fragment so finished analyses appear live ----------
@st.fragment(run_every="2s")
def dossier() -> None:
    repos = _load_repos(path)
    if not repos:
        with col_mid:
            st.subheader("Repo dossier")
            st.info("No repos in the queue yet - nothing to show. "
                    "Ingestion runs every few minutes; or seed demo data with `python scripts/seed_demo.py`.")
        with col_right:
            st.subheader("Vulnerabilities")
            st.info("No repos analyzed yet.")
        return

    with col_mid:
        st.subheader("Repo dossier")
        analyzed_names = {r["name"] for r in repos if load_json(r.get("synthesis_path"))}
        options = [r["name"] for r in repos]
        default_idx = next((i for i, n in enumerate(options) if n in analyzed_names), 0)
        choice = st.selectbox("Repository", options, index=default_idx)
        repo = next(r for r in repos if r["name"] == choice)
        if repo["name"] not in analyzed_names:
            st.info(f"`{repo['name']}` is {repo['status']} - dossier appears once synthesis finishes.")

        synthesis = load_json(repo.get("synthesis_path"))
        if synthesis:
            claims = synthesis.get("marketing_claims", [])
            reality = synthesis.get("verified_reality", [])
            with st.container(border=True):
                st.markdown("**Marketing vs Reality**")
                mc, rc = st.columns(2)
                with mc:
                    st.caption("README promises")
                    for c in claims or ["(none listed)"]:
                        st.markdown(f"- {c}")
                with rc:
                    st.caption("Code delivers")
                    for v in reality or ["(none verified)"]:
                        st.markdown(f"- {v}")
            with st.container(border=True):
                st.markdown("**Capability tags**")
                # tag "cloud": font-size by how many analyzed repos carry the tag
                freq: dict[str, int] = {}
                for r in repos:
                    s = load_json(r.get("synthesis_path")) or {}
                    for t in s.get("capability_tags", []):
                        freq[t] = freq.get(t, 0) + 1
                html = []
                for t in sorted(synthesis.get("capability_tags", []), key=lambda t: -freq[t]):
                    size = 13 + 4 * min(freq.get(t, 1), 4)
                    html.append(f"<span style='font-size:{size}px;margin-right:12px'>{t}</span>")
                st.markdown(" ".join(html) or "(no tags)", unsafe_allow_html=True)

    with col_right:
        st.subheader("Vulnerabilities")
        security = load_json(repo.get("security_json_path"))
        if security is None:
            st.info("No security results yet for this repo.")
        else:
            findings = security.get("findings", [])
            if not findings:
                st.success("No vulnerabilities found.")
            else:
                counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITY_ORDER}
                st.markdown(" ".join(f":{SEVERITY_DOT[s]}[{counts[s]}]" for s in SEVERITY_ORDER if counts[s]))
                for f in sorted(findings, key=lambda f: SEVERITY_ORDER.index(f["severity"])):
                    with st.container(border=True):
                        st.markdown(f":{SEVERITY_DOT[f['severity']]} **{f['severity']}** - "
                                    f"`{f['file']}:{f['line']}`")
                        st.markdown(f["description"])
                        st.caption(f"**Mitigation:** {f['mitigation']}")
                actions = list(dict.fromkeys(f["mitigation"] for f in findings if f["mitigation"]))
                if actions:
                    st.markdown("**Action items**")
                    st.markdown("\n".join(f"- [ ] {a}" for a in actions))


dossier()
