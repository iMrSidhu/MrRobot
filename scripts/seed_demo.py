"""Seed realistic demo data so the dashboard can be built/checked without
running Ollama (design 5 Phase 5.3). Writes DONE rows with the same
artifact layout the real pipeline produces (.synthesis.json /
.security.json sidecars + a vault Markdown report) and a full event
timeline. Idempotent: existing rows are kept, artifacts re-written.

    python scripts/seed_demo.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_engine.report import write_report
from shared import db
from shared.config import settings
from shared.models import Finding, SecurityResult, SynthesisResult


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


REPOS = [
    {
        "id": 81123456,
        "name": "acme/rover",
        "url": "https://github.com/acme/rover",
        "stars": 4213,
        "synthesis": {
            "architecture": (
                "Click CLI (`rover`) wrapping an OpenAI-compatible chat loop; "
                "state lives in a local SQLite file. Plugins are import-string "
                "entry points; no scheduler, no web UI despite the landing page."
            ),
            "marketing_claims": [
                "Fully autonomous multi-agent orchestration",
                "Runs 24/7 in the cloud out of the box",
                "Supports every LLM provider",
            ],
            "verified_reality": [
                "Single-agent loop with fixed tool order; no orchestration layer",
                "Local foreground process only; Dockerfile is an unfinished stub",
                "Only OpenAI + Azure endpoints are wired; others raise NotImplemented",
            ],
            "gaps": [
                "README hero section describes a roadmap, not the released code",
                "No tests for the tool-execution path",
            ],
            "capability_tags": ["cli", "agent-loop", "openai", "sqlite", "plugin-system"],
        },
        "findings": [
            Finding(severity="CRITICAL", file="rover/client.py", line=17,
                    description="known-token-prefix: API_KEY = \"sk-abc123...\" committed in source",
                    mitigation="Rotate the key, load it from the environment, purge git history"),
            Finding(severity="HIGH", file="rover/plugins.py", line=88,
                    description="insecure deserialization: pickle.loads on plugin archive contents",
                    mitigation="Use JSON + a schema check, or verify signatures before unpickling"),
            Finding(severity="MEDIUM", file="rover/tools.py", line=42,
                    description="RCE via tool use: subprocess(shell=True) on model-authored commands",
                    mitigation="Run commands through an allow-list in a sandbox; never shell=True"),
        ],
    },
    {
        "id": 82234567,
        "name": "nova-labs/agentforge",
        "url": "https://github.com/nova-labs/agentforge",
        "stars": 1877,
        "synthesis": {
            "architecture": (
                "Async FastAPI service with a Postgres-backed job queue and a "
                "pluggable executor; agents are YAML-declared graphs executed by "
                "a small interpreter."
            ),
            "marketing_claims": [
                "Enterprise-grade RBAC and audit logging",
                "Horizontal auto-scaling workers",
            ],
            "verified_reality": [
                "Auth middleware exists but RBAC roles are hardcoded to admin",
                "Worker pool scales only vertically (single process, multiple coros)",
            ],
            "gaps": ["No metrics exporter despite README badge"],
            "capability_tags": ["fastapi", "yaml-graph", "postgres", "async", "executor"],
        },
        "findings": [],
    },
    {
        "id": 83345678,
        "name": "zip/quicktask",
        "url": "https://github.com/zip/quicktask",
        "stars": 1042,
        "status": "QUEUED",
    },
]


def seed(db_path=None, cache_dir=None, vault_dir=None) -> dict:
    """Insert demo rows/artifacts/events; returns a summary dict."""
    db_path = Path(db_path or settings.db_path)
    cache_dir = Path(cache_dir or settings.repo_cache_dir)
    vault_dir = Path(vault_dir or settings.vault_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(db_path)
    db.init_db(conn)
    summary = {"repos": 0, "analyzed": 0, "events": 0, "skipped": 0}
    try:
        for spec in REPOS:
            if db.add_repo_if_new(conn, spec["id"], spec["name"], spec["url"], spec["stars"]) is None:
                summary["skipped"] += 1  # already seeded (or a real run got there first)
                continue
            summary["repos"] += 1
            status = spec.get("status", "DONE")
            if status == "QUEUED":
                db.add_event(conn, spec["id"], "DISCOVERED",
                             f"{spec['name']} ({spec['stars']} stars)",
                             {"url": spec["url"], "stars": spec["stars"]})
                summary["events"] += 1
                continue

            synth = SynthesisResult(**spec["synthesis"])
            security = SecurityResult(findings=spec["findings"])
            base = cache_dir / _safe(spec["name"])
            cache_dir.mkdir(parents=True, exist_ok=True)
            synth_path = Path(str(base) + ".synthesis.json")
            synth_path.write_text(synth.model_dump_json(indent=2), encoding="utf-8")
            Path(str(base) + ".security.json").write_text(
                security.model_dump_json(indent=2), encoding="utf-8")
            report = write_report({"id": spec["id"], "name": spec["name"],
                                   "url": spec["url"], "stars": spec["stars"]},
                                  synth, security, vault_dir=vault_dir)
            # full lifecycle event timeline, ids in insertion order
            for etype, message in [
                ("DISCOVERED", f"{spec['name']} ({spec['stars']} stars)"),
                ("ANALYSIS_START", "synthesis starting (qwen2.5-coder:3b)"),
                ("SYNTHESIS_DONE", f"tags: {', '.join(synth.capability_tags)}"),
                ("SECURITY_DONE", f"{len(security.findings)} findings after validation"),
                ("REPORTED", f"report at {report}"),
            ]:
                payload = {"url": spec["url"], "stars": spec["stars"]} if etype == "DISCOVERED" else None
                db.add_event(conn, spec["id"], etype, message, payload)
                summary["events"] += 1
            db.set_status(conn, spec["id"], "DONE",
                          synthesis_path=str(synth_path),
                          security_report_path=str(report))
            summary["analyzed"] += 1
        return summary
    finally:
        conn.close()


def main() -> int:
    s = seed()
    print(f"seeded {s['repos']} repos ({s['analyzed']} analyzed, {s['events']} events, "
          f"{s['skipped']} already present)")
    print(f"db: {settings.db_path}   reports: {settings.vault_dir}")
    print("next: streamlit run dashboard/app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
