"""Tests for llm_engine.synthesis with a fake Ollama (httpx.MockTransport)."""
import asyncio
import json
import pathlib
import sys
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from llm_engine import synthesis
from shared.models import ProcessedRepo, SynthesisResult

RESULT = {
    "architecture": "Flask app with plugin loader.",
    "marketing_claims": ["10x faster agents"],
    "verified_reality": ["app.py defines routes only"],
    "gaps": ["no benchmarks found in code"],
    "capability_tags": ["web", "flask"],
}


def reply_for(prompt: str) -> str:
    if prompt.startswith(synthesis.SUMMARY_PROMPT[:40]):
        return "- BULLETS: kept facts"
    return json.dumps(RESULT)


def make_client(prompts, models):
    def handler(request):
        body = json.loads(request.content)
        prompts.append(body["prompt"])
        models.append(body["model"])
        return httpx.Response(200, json={"response": reply_for(body["prompt"])})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(repo):
    prompts, models = [], []
    client = make_client(prompts, models)
    result = asyncio.run(synthesis.run_synthesis(repo, client=client))
    return result, prompts, models


def test_small_repo_is_one_llm_call_and_validates():
    repo = ProcessedRepo(repo_id=1, name="a/b", tree_text="main.py",
                         readme_chunks=["# tiny"], code_chunks=["def main(): ..."])
    result, prompts, models = run(repo)
    assert isinstance(result, SynthesisResult)
    assert result == SynthesisResult(**RESULT)
    assert len(prompts) == 1
    assert "Directory tree" in prompts[0] and "a/b" in prompts[0]
    assert "main.py" in prompts[0]
    assert models == [synthesis.settings.synthesis_model]


def test_empty_sections_render_placeholders():
    repo = ProcessedRepo(repo_id=2, name="c/d", tree_text="",
                         readme_chunks=[], code_chunks=[])
    _, prompts, _ = run(repo)
    assert "(none)" in prompts[0]


def test_oversized_repo_summarizes_then_merges(monkeypatch):
    monkeypatch.setattr(synthesis, "settings", SimpleNamespace(
        context_budget_tokens=300, synthesis_model="m"))
    big = "R" * 800  # one chunk way past the 500-char slot alloc
    repo = ProcessedRepo(repo_id=3, name="e/f", tree_text="cli.py",
                         readme_chunks=[big, big], code_chunks=["print(1)"])
    result, prompts, models = run(repo)
    assert isinstance(result, SynthesisResult)
    # acceptance: oversized path = dossier passes, then a final merge call
    summaries = [p for p in prompts if p.startswith(synthesis.SUMMARY_PROMPT[:40])]
    final = prompts[-1]
    assert len(summaries) >= 2
    assert "BULLETS: kept facts" in final          # merged into the template
    assert big[:50] not in final                    # raw oversized text dropped
    assert models[-1] == "m" and len(prompts) == len(summaries) + 1


def test_dossier_passes_are_capped(monkeypatch):
    monkeypatch.setattr(synthesis, 'settings', SimpleNamespace(context_budget_tokens=300, synthesis_model='m'))
    monkeypatch.setattr(synthesis, 'MAX_DOSSIER_GROUPS', 3)
    repo = ProcessedRepo(repo_id=1, name='a/b', tree_text='',
                         readme_chunks=['R' * 800] * 10, code_chunks=[])
    result, prompts, models = run(repo)
    assert isinstance(result, SynthesisResult)
    assert len(prompts) == 4                        # 3 capped dossier passes + final merge
    assert 'dossier covered only' in prompts[-1]    # the model is told the rest was dropped
