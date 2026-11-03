"""Tests for processor.service (DESIGN.md Step 2 flow) — fake clone, no network."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor import __main__ as processor_main
from processor import service
from processor.clone import CloneError
from shared import db
from shared.models import ProcessedRepo

GOOD_FILES = {"README.md": "# Rover\n", "main.py": "def main():\n    return 1\n"}


def seed_db(tmp_path, repos):
    path = tmp_path / "t.db"
    conn = db.connect(path)
    db.init_db(conn)
    for rid, name, stars in repos:
        db.add_repo_if_new(conn, rid, name, f"https://github.com/{name}.git", stars)
    conn.close()
    return path


def fake_clone_factory(fail_names=()):
    def fake_clone(url, name, *, dest_root=None, timeout=None):
        if name in fail_names:
            raise CloneError(f"boom cloning {name}")
        dest = Path(dest_root) / name.replace("/", "_")
        dest.mkdir(parents=True)
        for rel, text in GOOD_FILES.items():
            (dest / rel).write_text(text, encoding="utf-8")
        return dest
    return fake_clone


def make_env(tmp_path, monkeypatch, fail_names=()):
    monkeypatch.setattr(service, "clone_repo", fake_clone_factory(fail_names))
    return tmp_path / "cache"


# --- success path ------------------------------------------------------------
def test_success(tmp_path, monkeypatch):
    cache = make_env(tmp_path, monkeypatch)
    db_path = seed_db(tmp_path, [(1, "acme/rover", 1500)])
    assert service.run_once(db_path=db_path, cache_dir=cache) == 1

    conn = db.connect(db_path)
    repo = db.get_repo(conn, 1)
    assert repo["status"] == "PROCESSED" and repo["error"] is None
    conn.close()

    out = service.processed_json_path("acme/rover", cache)
    assert out.exists()
    data = ProcessedRepo.model_validate_json(out.read_text(encoding="utf-8"))
    assert data.repo_id == 1 and "main.py" in data.tree_text
    assert not (cache / "acme_rover").exists()  # clone dir cleaned up


# --- failure path ------------------------------------------------------------
def test_failed_repo_marks_failed_audit_with_event(tmp_path, monkeypatch):
    cache = make_env(tmp_path, monkeypatch, fail_names=("bad/repo",))
    db_path = seed_db(tmp_path, [(1, "bad/repo", 9000)])
    assert service.run_once(db_path=db_path, cache_dir=cache) == 0

    conn = db.connect(db_path)
    repo = db.get_repo(conn, 1)
    assert repo["status"] == "FAILED_AUDIT"
    assert "boom cloning bad/repo" in repo["error"]
    events = db.list_events_since(conn, 0)
    assert [e for e in events if e["type"] == "FAILED_AUDIT" and e["repo_id"] == 1]
    conn.close()


# --- acceptance: a failing repo never stops the loop -------------------------
def test_failure_does_not_stop_the_loop(tmp_path, monkeypatch):
    cache = make_env(tmp_path, monkeypatch, fail_names=("bad/repo",))
    # bad repo has MORE stars so claim_next (stars-first) picks it first
    db_path = seed_db(tmp_path, [(1, "bad/repo", 9999), (2, "good/repo", 1500)])
    assert service.run_once(db_path=db_path, cache_dir=cache) == 1

    conn = db.connect(db_path)
    assert db.get_repo(conn, 1)["status"] == "FAILED_AUDIT"
    assert db.get_repo(conn, 2)["status"] == "PROCESSED"
    conn.close()


def test_chunker_crash_also_isolated_and_clone_cleaned(tmp_path, monkeypatch):
    cache = make_env(tmp_path, monkeypatch)
    db_path = seed_db(tmp_path, [(1, "acme/rover", 1500)])

    def explode(repo_id, name, root):
        raise RuntimeError("chunker exploded")

    monkeypatch.setattr(service, "process_repo", explode)
    assert service.run_once(db_path=db_path, cache_dir=cache) == 0
    conn = db.connect(db_path)
    assert db.get_repo(conn, 1)["status"] == "FAILED_AUDIT"
    assert "chunker exploded" in db.get_repo(conn, 1)["error"]
    conn.close()
    assert not (cache / "acme_rover").exists()  # finally-cleanup still ran


def test_empty_queue_returns_zero(tmp_path, monkeypatch):
    cache = make_env(tmp_path, monkeypatch)
    db_path = seed_db(tmp_path, [])
    assert service.run_once(db_path=db_path, cache_dir=cache) == 0


def test_main_once_flag(tmp_path, monkeypatch):
    calls = []

    def fake_run_once():
        calls.append("once")
        return 0

    monkeypatch.setattr(processor_main.service, "run_once", fake_run_once)
    assert processor_main.main(["--once"]) == 0
    assert calls == ["once"]
