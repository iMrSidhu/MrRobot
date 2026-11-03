"""Offline tests for the OpenCode Go cloud client (fake transport, no network)."""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import httpx
import pytest
from pydantic import BaseModel

from llm_engine import cloud_client


class Answer(BaseModel):
    answer: str


def make_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def ok_reply(text: str):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": text}}]})


def test_generate_payload_model_pin_and_headers(monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["session"] = request.headers.get("x-opencode-session")
        seen["agent"] = request.headers.get("user-agent")
        seen["body"] = request.content
        return ok_reply("hi")

    async def run():
        return await cloud_client.generate(
            "P", model="gemma4:12b", client=make_client(handler))

    assert asyncio.run(run()) == "hi"
    assert seen["url"].endswith("/inference/go/openai/v1/chat/completions")
    assert seen["auth"] == "Bearer test-key"
    assert seen["session"] == cloud_client.SESSION_ID
    assert "sentinel" in seen["agent"]
    import json
    body = json.loads(seen["body"])
    assert body["model"] == cloud_client.CLOUD_MODEL       # local arg ignored
    assert body["messages"] == [{"role": "user", "content": "P"}]
    assert body["max_tokens"] == cloud_client.MAX_TOKENS_PER_CALL
    assert body["stream"] is False


def test_missing_api_key_fails_fast(monkeypatch):
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENCODE_GO_API_KEY"):
        asyncio.run(cloud_client.generate("P", client=make_client(ok_reply)))


def test_transient_error_retried_once(monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
    calls = []

    async def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500)
        return ok_reply("second")

    async def run():
        return await cloud_client.generate("P", client=make_client(handler))

    assert asyncio.run(run()) == "second"
    assert len(calls) == 2


def test_generate_json_repairs_fenced_output(monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
    prompts = []

    async def handler(request):
        import json
        prompts.append(json.loads(request.content)["messages"][0]["content"])
        return ok_reply("```json\n{\"answer\": \"42\",}\n```")

    async def run():
        return await cloud_client.generate_json(
            "any", "base", Answer, client=make_client(handler))

    result = asyncio.run(run())
    assert result == Answer(answer="42")
    assert "STRICT" not in prompts[0]          # first attempt succeeded

def test_empty_completion_fails_fast(monkeypatch):
    # reasoning models can burn the whole budget on hidden thinking and
    # return visible content '' - must NOT pass silently into a fake report
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
    calls = []

    async def handler(request):
        calls.append(1)
        return ok_reply("")

    async def run():
        return await cloud_client.generate("P", client=make_client(handler))

    with pytest.raises(RuntimeError, match="empty completion"):
        asyncio.run(run())
    assert len(calls) == 1  # no retry: same budget, same silent emptiness
