"""Tests for llm_engine.service (DESIGN.md Phase 4) — fake workers, no Ollama, no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from llm_engine import __main__ as llm_main
from llm_engine import service
from shared import db
from shared.models import Finding, ProcessedRepo, SecurityResult, SynthesisResult

SYNTH = SynthesisResult(architecture="A robot harness.", marketing_claims=["fast"],
                        verified_reality=["tests exist"], gaps=["no docs"],
                        capability_tags=["robotics"])
SEC = SecurityResult(findings=[Finding(severity="LOW", file="main.py", line=1,
                                       description="d", mitigation="m")])


def seed(tmp_path, cache, repos):
    """Repos already PROCESSED with a processed JSON on disk; returns db path."""
    path = tmp_path / "t.db"
    conn = db.connect(path)
    db.init_db(conn)
    for rid, name, stars in repos:
        db.add_repo_if_new(conn, rid, name, f"https://github.com/{name}.git", stars)
        db.set_status(conn, rid, "PROCESSED")
        processed = ProcessedRepo(repo_id=rid, name=name, tree_text="README.md\nmain.py",
                                  readme_chunks=["# " + name], code_chunks=["def main(): ..."],
                                  security_candidate_files=["main.py"])
        out = service._cache_path(name, service.PROCESSED_SUFFIX, cache)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(processed.model_dump_json(), encoding="utf-8")
    conn.close()
    return path


def wire(monkeypatch, fail_synth=(), fail_security=()):
    """Patch the two model passes + clone; records calls for assertions."""
    calls = {"synth": [], "security": [], "clone": []}

    async def fake_synth(repo, **kw):
        calls["synth"].append(repo.name)
        if repo.name in fail_synth:
            raise httpx.ReadTimeout(f"{repo.name}: no answer")
        return SYNTH

    async def fake_security(repo, root, **kw):
        calls["security"].append((repo.name, Path(root).exists()))
        if repo.name in fail_security:
            raise RuntimeError(f"security died on {repo.name}")
        return SEC

    def fake_clone(url, name, *, dest_root=None, timeout=None):
        calls["clone"].append(name)
        dest = Path(dest_root) / name.replace("/", "_")
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "main.py").write_text("print(1)\n", encoding="utf-8")
        return dest

    monkeypatch.setattr(service, "run_synthesis", fake_synth)
    monkeypatch.setattr(service, "run_security", fake_security)
    monkeypatch.setattr(service, "clone_repo", fake_clone)
    return calls


# --- success path -------------------------------------------------------------
def test_success_sets_done_with_vault_report(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    vault = tmp_path / "vault"
    db_path = seed(tmp_path, cache, [(1, "acme/rover", 1500)])
    calls = wire(monkeypatch)
    assert service.run_once(db_path=db_path, cache_dir=cache, vault_dir=vault) == 1

    conn = db.connect(db_path)
    repo = db.get_repo(conn, 1)
    assert repo["status"] == "DONE" and repo["error"] is None
    assert SynthesisResult.model_validate_json(
        Path(repo["synthesis_path"]).read_text(encoding="utf-8")) == SYNTH
    report_file = Path(repo["security_report_path"])
    assert report_file == vault / "acme__rover.md"
    md = report_file.read_text(encoding="utf-8")
    assert md.startswith("# acme/rover") and "## Vulnerability matrix" in md
    sec_json = Path(repo["security_json_path"])
    assert sec_json == service._cache_path("acme/rover", service.SECURITY_SUFFIX, cache)
    assert sec_json.is_file()
    events = [e["type"] for e in db.list_events_since(conn, 0) if e["repo_id"] == 1]
    assert events == ["ANALYSIS_START", "SYNTHESIS_DONE", "SECURITY_DONE", "REPORTED"]
    conn.close()

    assert calls["clone"] == ["acme/rover"]
    assert calls["security"][0] == ("acme/rover", True)  # tree re-cloned before Model B
    assert not (cache / "acme_rover").exists()  # and cleaned up again


# --- model failure path ---------------------------------------------------------
def test_synthesis_model_failure_fails_repo_without_cloning(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    db_path = seed(tmp_path, cache, [(1, "slow/repo", 1500)])
    calls = wire(monkeypatch, fail_synth=("slow/repo",))
    assert service.run_once(db_path=db_path, cache_dir=cache) == 0

    conn = db.connect(db_path)
    repo = db.get_repo(conn, 1)
    assert repo["status"] == "FAILED_AUDIT"
    assert "ReadTimeout" in repo["error"] and "no answer" in repo["error"]
    types = [e["type"] for e in db.list_events_since(conn, 0) if e["repo_id"] == 1]
    assert types == ["ANALYSIS_START", "FAILED_AUDIT"]
    conn.close()
    assert calls["clone"] == []  # synthesis first: no wasted clone when model A dies


# --- partial failure ----------------------------------------------------------
def test_security_failure_after_good_synthesis(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    db_path = seed(tmp_path, cache, [(1, "half/repo", 1500)])
    wire(monkeypatch, fail_security=("half/repo",))
    assert service.run_once(db_path=db_path, cache_dir=cache) == 0

    conn = db.connect(db_path)
    repo = db.get_repo(conn, 1)
    assert repo["status"] == "FAILED_AUDIT"
    assert "security died" in repo["error"]
    types = [e["type"] for e in db.list_events_since(conn, 0) if e["repo_id"] == 1]
    assert types == ["ANALYSIS_START", "SYNTHESIS_DONE", "FAILED_AUDIT"]
    conn.close()
    # synthesis JSON survived the failure: rerunning later can reuse it
    assert service._cache_path("half/repo", service.SYNTHESIS_SUFFIX, cache).exists()
    assert not (cache / "half_repo").exists()  # re-clone still cleaned up


# --- acceptance: one failing repo does not block the next ---------------------
def test_failure_does_not_stop_the_loop(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    # bad repo has MORE stars so claim_next (stars-first) picks it first
    db_path = seed(tmp_path, cache, [(1, "bad/repo", 9999), (2, "good/repo", 1500)])
    wire(monkeypatch, fail_synth=("bad/repo",))
    assert service.run_once(db_path=db_path, cache_dir=cache,
                             vault_dir=tmp_path / "vault") == 1

    conn = db.connect(db_path)
    assert db.get_repo(conn, 1)["status"] == "FAILED_AUDIT"
    assert db.get_repo(conn, 2)["status"] == "DONE"
    conn.close()


def test_report_write_failure_is_audited(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    db_path = seed(tmp_path, cache, [(1, "acme/rover", 1500)])
    wire(monkeypatch)

    def boom(repo, synthesis, security, *, vault_dir=None):
        raise OSError("vault disk gone")

    monkeypatch.setattr(service, "write_report", boom)
    assert service.run_once(db_path=db_path, cache_dir=cache,
                             vault_dir=tmp_path / "vault") == 0
    conn = db.connect(db_path)
    repo = db.get_repo(conn, 1)
    assert repo["status"] == "FAILED_AUDIT" and "OSError" in repo["error"]
    types = [e["type"] for e in db.list_events_since(conn, 0) if e["repo_id"] == 1]
    assert types == ["ANALYSIS_START", "SYNTHESIS_DONE", "SECURITY_DONE", "FAILED_AUDIT"]
    conn.close()
    assert not (cache / "acme_rover").exists()  # clone cleaned even on report failure


def test_missing_processed_json_is_audited(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    db_path = seed(tmp_path, cache, [(1, "lost/repo", 1500)])
    service._cache_path("lost/repo", service.PROCESSED_SUFFIX, cache).unlink()
    wire(monkeypatch)
    assert service.run_once(db_path=db_path, cache_dir=cache) == 0
    conn = db.connect(db_path)
    assert db.get_repo(conn, 1)["status"] == "FAILED_AUDIT"
    assert "FileNotFoundError" in db.get_repo(conn, 1)["error"]
    conn.close()


def test_empty_queue_returns_zero(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    db_path = seed(tmp_path, cache, [])
    wire(monkeypatch)
    assert service.run_once(db_path=db_path, cache_dir=cache) == 0


# --- crashed-worker recovery ----------------------------------------------------
def test_stale_analyzing_row_is_reclaimed_and_rerun(tmp_path, monkeypatch):
    """Simulates a worker killed mid-analysis: the row sits in ANALYZING with an
    old timestamp; the next drain must requeue it and take it to DONE."""
    cache = tmp_path / "cache"
    vault = tmp_path / "vault"
    db_path = seed(tmp_path, cache, [(1, "dead/repo", 1500)])
    conn = db.connect(db_path)
    assert db.claim_next(conn, "PROCESSED", "ANALYZING") is not None
    conn.execute("UPDATE repositories"
                 " SET timestamp = strftime('%Y-%m-%dT%H:%M:%fZ','now','-3600 seconds') WHERE id = 1")
    conn.commit()
    conn.close()

    calls = wire(monkeypatch)
    assert service.run_once(db_path=db_path, cache_dir=cache, vault_dir=vault) == 1

    conn = db.connect(db_path)
    assert db.get_repo(conn, 1)["status"] == "DONE"
    types = [e["type"] for e in db.list_events_since(conn, 0) if e["repo_id"] == 1]
    assert types == ["RECLAIMED", "ANALYSIS_START", "SYNTHESIS_DONE", "SECURITY_DONE", "REPORTED"]
    conn.close()
    assert calls["synth"] == ["dead/repo"]  # actually re-ran, not just marked


def test_main_once_flag(monkeypatch):
    calls = []

    def fake_run_once():
        calls.append("once")
        return 0

    monkeypatch.setattr(llm_main.service, "run_once", fake_run_once)
    assert llm_main.main(["--once"]) == 0
    assert calls == ["once"]


# --- budgeted runs ------------------------------------------------------------
def test_run_once_limit_caps_claims_in_star_order(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    vault = tmp_path / "vault"
    db_path = seed(tmp_path, cache, [(1, "a/big", 9000), (2, "a/mid", 500), (3, "a/small", 10)])
    calls = wire(monkeypatch)
    assert service.run_once(db_path=db_path, cache_dir=cache, vault_dir=vault, limit=2) == 2
    assert calls["synth"] == ["a/big", "a/mid"]
    conn = db.connect(db_path)
    assert [r["name"] for r in db.list_repos(conn, "PROCESSED")] == ["a/small"]
    conn.close()
