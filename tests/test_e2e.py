"""End-to-end pipeline test (step 17): fixture git repo -> fake GitHub
search -> ingestion -> processor (REAL clone/filter/chunk against a local
git repo) -> llm_engine with a fake-Ollama transport -> vault report.
Asserts the repo reaches DONE, the report exists, and events come out in
order. No network, no models - the whole pipeline runs in-process."""
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import httpx

from ingestion.service import run_once as ingest_once
from llm_engine.service import run_once as analyze_once
from processor.service import run_once as process_once
from shared import db
from shared.config import settings
from tests.test_clone import make_source_repo

REPO_ID = 555000
SYNTH_JSON = json.dumps({
    "architecture": "single-file CLI with a subprocess tool loop",
    "marketing_claims": ["does everything"],
    "verified_reality": ["does two things"],
    "gaps": ["no tests"],
    "capability_tags": ["cli", "agent-loop"],
})


def _handler_factory(local_clone_url: str):
    """One MockTransport handler serving both GitHub search (yielding the
    fixture repo with its LOCAL path as clone_url) and fake Ollama."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(200, json={"items": [
                {"id": REPO_ID, "full_name": "acme/rover", "stargazers_count": 1500,
                 "clone_url": local_clone_url}]})
        model = json.loads(request.content)["model"]
        if model == settings.synthesis_model:
            return httpx.Response(200, json={"response": SYNTH_JSON})
        if model == settings.security_model:
            # model B adds nothing - the deterministic regex hit must survive
            return httpx.Response(200, json={"response": '{"findings": []}'})
        return httpx.Response(500, json={"error": f"unconfigured model {model}"})
    return handler


def test_full_pipeline_reaches_done(tmp_path):
    src = make_source_repo(tmp_path, extra={  # planted fake secret for the regex sweep
        "client.py": "API_KEY = \"sk-testABCDEFGHIJKLMNOPQRSTUV\"\n"})
    db_path = tmp_path / "e2e.db"
    cache = tmp_path / "cache"
    vault = tmp_path / "vault"
    transport = httpx.MockTransport(_handler_factory(str(src)))

    assert asyncio.run(ingest_once(client=httpx.AsyncClient(transport=transport,
                                                            base_url="https://api.github.com"),
                                   db_path=db_path)) == 1
    assert process_once(db_path, cache) == 1
    conn = db.connect(db_path)
    assert db.get_repo(conn, REPO_ID)["status"] == "PROCESSED"
    conn.close()

    assert analyze_once(db_path, cache, vault,
                        client=httpx.AsyncClient(transport=transport)) == 1

    conn = db.connect(db_path)
    row = db.get_repo(conn, REPO_ID)
    events = [e for e in db.list_events_since(conn, 0) if e["repo_id"] == REPO_ID]
    conn.close()

    assert row["status"] == "DONE"
    synth = pathlib.Path(row["synthesis_path"])
    assert synth.is_file() and "subprocess tool loop" in synth.read_text(encoding="utf-8")
    report = pathlib.Path(row["security_report_path"])
    assert report.is_file() and report.parent.name == "vault"
    body = report.read_text(encoding="utf-8")
    assert "single-file CLI with a subprocess tool loop" in body   # synthesis section
    assert "does everything" in body and "does two things" in body  # claims vs reality
    assert "known-token-prefix" in body  # regex finding survived the empty LLM reply
    assert [e["type"] for e in events] == [
        "DISCOVERED", "ANALYSIS_START", "SYNTHESIS_DONE", "SECURITY_DONE", "REPORTED"]
    # intermediates land beside the processed artifact, clone dirs are gone
    sec_json = pathlib.Path(row["security_json_path"])
    assert sec_json.is_file() and sec_json.name == "acme_rover.security.json"
    assert not any(p.is_dir() and p.name.startswith("acme_rover") for p in cache.iterdir())


def test_run_all_backoff_schedule_and_single_command():
    from scripts import run_all

    assert [run_all.next_delay(n) for n in (1, 2, 3, 10)] == [1.0, 2.0, 4.0, 60.0]
    assert set(run_all.SERVICES) == {"ingestion", "processor", "llm_engine", "api", "dashboard"}
    assert run_all.main(["--list"]) == 0  # every service is one command, launched from here
