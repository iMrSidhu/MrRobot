"""LLM analysis service loop (DESIGN.md section 2 principles 2-3, section 3 step 3).

Claims PROCESSED -> ANALYZING, re-reads the ProcessedRepo JSON the processor
left in the cache dir, runs Model A synthesis then re-clones the tree (the
processor wipes it at PROCESSED) for Model B's security validation, stores
both results as JSON, writes the Markdown dossier into the vault (report.py),
marks DONE and writes an event at each stage.
Any failure -> FAILED_AUDIT + error + event, loop continues (principle 2).
Synthesis and security run sequentially in ONE process, so the single-model
6GB VRAM lock (principle 3) holds without cross-process coordination.
"""
import asyncio
import time
from pathlib import Path

from llm_engine.report import write_report
from llm_engine.security import run_security
from llm_engine.synthesis import run_synthesis
# shortcut: cross-service import against protocol rule c - reuse the hardened
# clone utility instead of duplicating security-critical code; upgrade path is
# moving processor/clone.py to shared/ if the user approves.
from processor.clone import cleanup, clone_repo, sanitize_dir_name
from shared import db
from shared.config import settings
from shared.logging import get_logger
from shared.models import ProcessedRepo

logger = get_logger("llm_engine.service")

PROCESSED_SUFFIX = ".processed.json"    # same on-disk convention processor/service.py writes
SYNTHESIS_SUFFIX = ".synthesis.json"
SECURITY_SUFFIX = ".security.json"


def _cache_path(name: str, suffix: str, cache_dir: Path | str | None) -> Path:
    """<cache_dir>/<sanitized repo name><suffix> - survives clone cleanup."""
    root = Path(cache_dir or settings.repo_cache_dir)
    return root / (sanitize_dir_name(name) + suffix)


async def _analyze_one(conn, repo: dict, cache_dir, vault_dir, client=None) -> bool:
    """Analyze one claimed repo end to end; returns True on success. Never raises."""
    repo_id, name, url = repo["id"], repo["name"], repo["url"]
    dest = None
    try:
        db.add_event(conn, repo_id, "ANALYSIS_START", f"{name}: dual-LLM pipeline started")
        processed = ProcessedRepo.model_validate_json(
            _cache_path(name, PROCESSED_SUFFIX, cache_dir).read_text(encoding="utf-8"))

        synthesis = await run_synthesis(processed, client=client)
        synth_out = _cache_path(name, SYNTHESIS_SUFFIX, cache_dir)
        synth_out.parent.mkdir(parents=True, exist_ok=True)
        synth_out.write_text(synthesis.model_dump_json(), encoding="utf-8")
        db.add_event(conn, repo_id, "SYNTHESIS_DONE", f"{name}: model A finished",
                     {"capability_tags": synthesis.capability_tags})

        dest = clone_repo(url, name, dest_root=cache_dir)
        security = await run_security(processed, dest, client=client)
        sec_out = _cache_path(name, SECURITY_SUFFIX, cache_dir)
        sec_out.write_text(security.model_dump_json(), encoding="utf-8")
        db.add_event(conn, repo_id, "SECURITY_DONE", f"{name}: model B finished",
                     {"findings": len(security.findings)})

        db.set_status(conn, repo_id, "ANALYZED",
                      synthesis_path=str(synth_out), security_report_path=str(sec_out))
        report_path = write_report(repo, synthesis, security, vault_dir=vault_dir)
        db.set_status(conn, repo_id, "DONE", synthesis_path=str(synth_out),
                      security_report_path=str(report_path))
        db.add_event(conn, repo_id, "REPORTED", f"{name}: report at {report_path}")
        logger.info(f"{name} -> DONE ({len(security.findings)} findings, {report_path.name})")
        return True
    except Exception as exc:
        try:
            db.set_status(conn, repo_id, "FAILED_AUDIT", error=f"{type(exc).__name__}: {exc}")
            db.add_event(conn, repo_id, "FAILED_AUDIT", f"{name}: {exc}")
        except Exception:  # DB itself sick - log and let the loop live anyway
            logger.exception("could not record FAILED_AUDIT for repo %s", repo_id)
        logger.warning(f"{name} -> FAILED_AUDIT ({exc})")
        return False
    finally:
        if dest is not None:
            cleanup(dest)


def run_once(db_path: Path | str | None = None,
             cache_dir: Path | str | None = None,
             vault_dir: Path | str | None = None,
             client=None) -> int:
    """Drain everything currently PROCESSED; returns the number analyzed OK.
    `client` is injected into the LLM calls (tests run the whole pipeline
    against a fake Ollama transport)."""
    conn = db.connect(Path(db_path or settings.db_path))
    db.init_db(conn)
    # crashed-worker recovery (shared/db.reclaim_stale): rows a killed worker
    # abandoned mid-run requeue here; artifacts are idempotent so a full rerun is safe
    db.reclaim_stale(conn, "ANALYZING", "PROCESSED")
    db.reclaim_stale(conn, "ANALYZED", "PROCESSED")
    analyzed = 0

    async def _drain() -> None:
        nonlocal analyzed
        while True:
            repo = db.claim_next(conn, "PROCESSED", "ANALYZING")
            if repo is None:
                break
            analyzed += await _analyze_one(conn, repo, cache_dir, vault_dir, client)

    asyncio.run(_drain())
    conn.close()
    return analyzed


def run_forever(db_path: Path | str | None = None,
                cache_dir: Path | str | None = None,
                vault_dir: Path | str | None = None,
                client=None) -> None:
    """Worker loop: drain backlogs immediately, idle-poll otherwise."""
    while True:
        if run_once(db_path, cache_dir, vault_dir, client) == 0:
            time.sleep(settings.poll_interval_sec)
