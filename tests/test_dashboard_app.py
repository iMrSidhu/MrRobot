"""Dashboard step tests: the seeder produces a complete demo dataset and
the Streamlit page renders all three panels from it (acceptance: seeded
data -> three panels, feed updates on new events). Streamlit's official
AppTest runner replaces the app without a browser; the SSE thread is
disabled via SENTINEL_FEED=off so panels read the DB deterministically -
the thread itself is covered in test_feed.py."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from streamlit.testing.v1 import AppTest

from scripts.seed_demo import seed
from shared import db

APP = str(pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "app.py")


def _env(tmp_path):
    """Point the app at a tmp DB with the feed thread switched off."""
    paths = {"db": tmp_path / "hud.db", "cache": tmp_path / "cache", "vault": tmp_path / "vault"}
    summary = seed(str(paths["db"]), str(paths["cache"]), str(paths["vault"]))
    os.environ["SENTINEL_DB_PATH"] = str(paths["db"])
    os.environ["SENTINEL_FEED"] = "off"
    return paths, summary


def _run():
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_seed_produces_full_demo_dataset(tmp_path):
    paths, s = _env(tmp_path)
    assert s == {"repos": 3, "analyzed": 2, "events": 11, "skipped": 0}
    conn = db.connect(paths["db"])
    rows = db.list_repos(conn)
    by_name = {r["name"]: r for r in rows}
    assert by_name["acme/rover"]["status"] == "DONE"
    assert by_name["zip/quicktask"]["status"] == "QUEUED"
    synth_path = pathlib.Path(by_name["acme/rover"]["synthesis_path"])
    assert synth_path.is_file() and synth_path.with_name(
        synth_path.name.replace(".synthesis.json", ".security.json")).is_file()
    vault_md = pathlib.Path(by_name["acme/rover"]["security_report_path"])
    assert "Marketing vs Reality" in vault_md.read_text(encoding="utf-8")
    # re-seeding is a no-op
    _, s2 = _env(tmp_path)
    assert s2["skipped"] == 3 and s2["repos"] == 0


def test_all_three_panels_render_with_seeded_data(tmp_path):
    _env(tmp_path)
    at = _run()
    headers = [h.value for h in at.subheader]
    assert "Event radar" in headers and "Repo dossier" in headers and "Vulnerabilities" in headers
    # left: terminal-style feed shows seeded events
    assert "DISCOVERED" in at.code[0].value and "acme/rover" in at.code[0].value
    # center: split card + tag cloud for the default (first analyzed) repo
    md = "\n".join(m.value for m in at.markdown)
    assert "Marketing vs Reality" in md
    assert "Fully autonomous multi-agent orchestration" in md  # claim
    assert "Single-agent loop with fixed tool order" in md     # reality
    assert "agent-loop" in md                                  # tag cloud span
    assert at.selectbox[0].value == "acme/rover"
    # right: severity-sorted findings + action items
    assert "CRITICAL" in md and "rover/client.py:17" in md
    assert "Action items" in md and "Rotate the key" in md


def test_clean_vuln_repo_shows_no_findings(tmp_path):
    _env(tmp_path)
    at = _run()
    at.selectbox[0].set_value("nova-labs/agentforge").run()
    assert not at.exception
    assert any("No vulnerabilities found" in s.value for s in at.success)


def test_empty_database_shows_clear_state(tmp_path):
    os.environ["SENTINEL_DB_PATH"] = str(tmp_path / "empty.db")
    os.environ["SENTINEL_FEED"] = "off"
    conn = db.connect(tmp_path / "empty.db")
    db.init_db(conn)
    conn.close()
    at = _run()
    infos = " ".join(i.value for i in at.info)
    assert "No repos in the queue yet" in infos
    assert "No events yet" in infos


def test_feed_updates_when_new_event_inserted(tmp_path):
    paths, _ = _env(tmp_path)
    at = _run()
    before = at.code[0].value
    conn = db.connect(paths["db"])
    db.add_event(conn, 81123456, "ANALYSIS_START", "brand new event")
    conn.close()
    at.run()  # timer-equivalent rerun reads the DB again
    assert "brand new event" in at.code[0].value
    assert before != at.code[0].value
