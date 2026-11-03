"""Tests for llm_engine.security — fake Model B transport, planted secrets."""
import asyncio
import json
import pathlib
import sys

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from llm_engine import security
from shared.config import settings
from shared.models import ProcessedRepo

KEY_LINE = 'API = "sk-' + "A" * 25 + '"\n'          # planted fake secret, line 2 below


def plant(tmp_path, **files) -> ProcessedRepo:
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return ProcessedRepo(repo_id=1, name="hostile/repo",
                         tree_text="\n".join(files),
                         security_candidate_files=list(files))


def fake_client(reply: dict, prompts: list, models: list):
    def handler(request):
        body = json.loads(request.content)
        prompts.append(body["prompt"])
        models.append(body["model"])
        return httpx.Response(200, json={"response": json.dumps(reply)})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(repo, reply, tmp_path):
    prompts, models = [], []
    client = fake_client(reply, prompts, models)
    result = asyncio.run(security.run_security(repo, tmp_path, client=client))
    return result, prompts, models


def test_planted_key_reported_even_when_llm_returns_nothing(tmp_path):
    repo = plant(tmp_path, **{"evil.py": "import os\n" + KEY_LINE + "print(API)\n"})
    result, prompts, models = run(repo, {"findings": []}, tmp_path)
    hits = [f for f in result.findings if f.file == "evil.py"]
    assert hits and hits[0].severity == "CRITICAL" and hits[0].line == 2
    assert len(prompts) == 1 and "evil.py:2" in prompts[0]      # known finding fed back
    assert models[0] == settings.security_model


def test_hallucinated_file_and_line_are_dropped(tmp_path):
    repo = plant(tmp_path, **{"evil.py": "import os\n" + KEY_LINE,
                              "app.py": "eval(user_input)\n"})
    reply = {"findings": [
        {"severity": "HIGH", "file": "evil.py", "line": 9999,
         "description": "ghost line", "mitigation": "x"},
        {"severity": "HIGH", "file": "ghost.py", "line": 1,
         "description": "ghost file", "mitigation": "x"},
        {"severity": "MEDIUM", "file": "app.py", "line": 1,
         "description": "eval on untrusted input", "mitigation": "ast.literal_eval"},
    ]}
    result, _, _ = run(repo, reply, tmp_path)
    files = {(f.file, f.line) for f in result.findings}
    assert ("evil.py", 9999) not in files and ("ghost.py", 1) not in files
    assert ("app.py", 1) in files


def test_duplicates_merged_and_sorted_by_severity(tmp_path):
    repo = plant(tmp_path, **{"evil.py": KEY_LINE, "app.py": "eval(x)\ny = 1\n"})
    dup = {"severity": "MEDIUM", "file": "app.py", "line": 1,
           "description": "eval on untrusted input", "mitigation": "m"}
    reply = {"findings": [
        dup,
        dict(dup),
        {"severity": "LOW", "file": "app.py", "line": 2,
         "description": "dead code", "mitigation": "m"},
        {"severity": "CRITICAL", "file": "app.py", "line": 1,
         "description": "RCE via eval", "mitigation": "remove eval"},
    ]}
    result, _, _ = run(repo, reply, tmp_path)
    keys = [(f.severity, f.file, f.line) for f in result.findings]
    dups = [f for f in result.findings if f.description == "eval on untrusted input"]
    assert len(dups) == 1                                          # merged dupes only
    assert len(result.findings) == 4          # 3 LLM (dup merged) + 1 regex hit
    sev_order = [security.SEVERITY_RANK[s] for s, _, _ in keys]
    assert sev_order == sorted(sev_order)                        # CRITICAL -> LOW
    assert keys[0][0] == "CRITICAL"
    assert any(f.file == "evil.py" for f in result.findings)     # regex hit survives


def test_no_candidates_skips_llm_but_keeps_regex_sweep(tmp_path):
    repo = plant(tmp_path, **{"lib.py": "a = 1\n" + KEY_LINE})
    repo.security_candidate_files = []
    prompts: list = []
    result, prompts, _ = run(repo, {"findings": []}, tmp_path)
    assert prompts == []
    assert [f.file for f in result.findings] == ["lib.py"]
