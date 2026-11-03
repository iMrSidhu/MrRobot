import json
import pathlib
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared import db  # noqa: E402


def _db(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    return conn


def test_wal_mode_enabled(tmp_path):
    conn = _db(tmp_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_dedupe_by_name(tmp_path):
    conn = _db(tmp_path)
    first = db.add_repo_if_new(conn, 1, "owner/repo", "https://github.com/owner/repo", 1500)
    dup = db.add_repo_if_new(conn, 1, "owner/repo", "https://github.com/owner/repo", 9999)
    assert first["stars"] == 1500  # second insert ignored, stars unchanged
    assert dup is None
    assert len(db.list_repos(conn)) == 1


def test_claim_next_is_exclusive_for_single_row(tmp_path):
    conn = _db(tmp_path)
    db.add_repo_if_new(conn, 1, "a/b", "u", 10)
    claimed = db.claim_next(conn, "QUEUED", "CLONING")
    assert claimed["id"] == 1 and claimed["status"] == "CLONING"
    assert db.claim_next(conn, "QUEUED", "CLONING") is None  # nothing left in QUEUED


def test_claim_prefers_high_stars(tmp_path):
    conn = _db(tmp_path)
    db.add_repo_if_new(conn, 1, "low/x", "u", 5)
    db.add_repo_if_new(conn, 2, "high/y", "u", 500)
    assert db.claim_next(conn, "QUEUED", "CLONING")["id"] == 2


def test_two_concurrent_claimers_never_share_a_row(tmp_path):
    _db(tmp_path).close()  # create schema
    conn = db.connect(tmp_path / "test.db")
    for i in (1, 2, 3):
        db.add_repo_if_new(conn, i, f"org/r{i}", "u", 10 * i)
    conn.close()

    claimed, errors = [], []
    barrier = threading.Barrier(2)

    def worker():
        c = db.connect(tmp_path / "test.db")
        try:
            barrier.wait()  # maximize overlap
            row = db.claim_next(c, "QUEUED", "CLONING")
            if row:
                claimed.append(row["id"])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(claimed) == 2 and len(set(claimed)) == 2  # distinct rows
    c = db.connect(tmp_path / "test.db")
    assert len(db.list_repos(c, "QUEUED")) == 1  # third untouched
    c.close()


def test_event_ordering_and_since_cursor(tmp_path):
    conn = _db(tmp_path)
    db.add_repo_if_new(conn, 1, "a/b", "u", 10)
    e1 = db.add_event(conn, 1, "DISCOVERED", "found", {"stars": 10})
    e2 = db.add_event(conn, 1, "CLONED", "ok")
    assert e1 < e2
    events = db.list_events_since(conn, 0)
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)
    assert json.loads(events[0]["payload_json"]) == {"stars": 10}
    assert [e["id"] for e in db.list_events_since(conn, e1)] == [e2]


def test_set_status_fields_and_validation(tmp_path):
    conn = _db(tmp_path)
    db.add_repo_if_new(conn, 1, "a/b", "u", 10)
    db.set_status(conn, 1, "FAILED_AUDIT", error="ollama timeout")
    r = db.get_repo(conn, 1)
    assert r["status"] == "FAILED_AUDIT" and r["error"] == "ollama timeout"

    db.set_status(conn, 1, "DONE", synthesis_path="vault/a-b.md")
    r = db.get_repo(conn, 1)
    assert r["status"] == "DONE" and r["synthesis_path"] == "vault/a-b.md"

    db.set_status(conn, 1, "ANALYZED", security_json_path="cache/a_b.security.json")
    r = db.get_repo(conn, 1)  # merge semantics: previous paths survive
    assert r["security_json_path"] == "cache/a_b.security.json" and r["synthesis_path"] == "vault/a-b.md"

    with pytest.raises(ValueError):
        db.set_status(conn, 1, "NOPE")
    with pytest.raises(ValueError):
        db.claim_next(conn, "BOGUS", "CLONING")


def test_reclaim_stale_hands_back_only_abandoned_rows(tmp_path):
    conn = _db(tmp_path)
    db.add_repo_if_new(conn, 1, "dead/x", "u", 10)
    db.add_repo_if_new(conn, 2, "busy/y", "u", 10)
    db.claim_next(conn, "QUEUED", "CLONING")
    db.claim_next(conn, "QUEUED", "CLONING")
    conn.execute("UPDATE repositories"
                 " SET timestamp = strftime('%Y-%m-%dT%H:%M:%fZ','now','-3600 seconds') WHERE id = 1")
    conn.commit()

    assert db.reclaim_stale(conn, "CLONING", "QUEUED") == 1
    assert db.get_repo(conn, 1)["status"] == "QUEUED"
    assert db.get_repo(conn, 2)["status"] == "CLONING"  # fresh (alive) row untouched
    ev = db.list_events_since(conn, 0)[-1]
    assert ev["type"] == "RECLAIMED" and ev["repo_id"] == 1
    assert db.claim_next(conn, "QUEUED", "CLONING")["id"] == 1  # re-runnable
    with pytest.raises(ValueError):
        db.reclaim_stale(conn, "BOGUS", "QUEUED")


def test_init_db_migrates_legacy_database(tmp_path):
    conn = db.connect(tmp_path / "legacy.db")
    conn.executescript(  # pre-v1.2 schema: no security_json_path column
        "CREATE TABLE repositories ("
        " id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, url TEXT NOT NULL,"
        " stars INTEGER NOT NULL, status TEXT NOT NULL, synthesis_path TEXT,"
        " security_report_path TEXT, error TEXT,"
        " timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));")
    conn.execute("INSERT INTO repositories (id,name,url,stars,status) VALUES (1,'a','u',1,'QUEUED')")
    conn.commit()
    db.init_db(conn)
    assert db.get_repo(conn, 1)["security_json_path"] is None  # column added in place
    db.set_status(conn, 1, "DONE", security_json_path="x.security.json")
    assert db.get_repo(conn, 1)["security_json_path"] == "x.security.json"
    conn.close()
