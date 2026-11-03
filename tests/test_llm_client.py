"""Tests for llm_engine.client — fake Ollama via httpx.MockTransport, no live server."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_engine import client as llm
from llm_engine.client import clean_json_text, generate, generate_json


class Answer(BaseModel):
    answer: str


def handler_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def respond(text, request=None):
    return httpx.Response(200, json={"response": text}, request=request)


def body_prompt(request):
    return json.loads(request.content)["prompt"]


# --- generate: retry + timeout -----------------------------------------------
def test_transient_error_retried_once():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("transient", request=request)
        return respond("hi", request)

    async def run():
        async with handler_client(handler) as ac:
            return await generate("p", model="m", client=ac)

    assert asyncio.run(run()) == "hi"
    assert len(calls) == 2


def test_read_timeout_retried_once_then_raises():
    # with answer time uncapped, a ReadTimeout can only come from outside
    # (proxy cut etc.); the retry-then-propagate path must still work.
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("slow", request=request)

    async def run():
        async with handler_client(handler) as ac:
            await generate("p", model="m", client=ac)

    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(run())
    assert len(calls) == 2


def test_answer_time_is_uncapped():
    # user decision 2026-11: models may take as long as they like — read/pool/
    # write have no deadline; only connect stays bounded (fail fast on dead host).
    seen = []

    def handler(request):
        seen.append(request)
        return respond("ok", request)

    asyncio.run(generate("p", model="m", client=handler_client(handler)))
    timeout = seen[0].extensions["timeout"]
    assert timeout["read"] is None and timeout["connect"] == 30.0


def test_5xx_retried_once_then_ok():
    n = []

    def handler(request):
        n.append(1)
        if len(n) == 1:
            return httpx.Response(500, request=request)
        return respond("recovered", request)

    async def run():
        async with handler_client(handler) as ac:
            return await generate("p", model="m", client=ac)

    assert asyncio.run(run()) == "recovered"


# --- generate_json: fences, repair, strict retry -------------------------------
def test_generate_json_strips_fences_and_repairs_commas():
    def handler(request):
        return respond('Here you go:\n```json\n{"answer": "42",}\n```', request)

    async def run():
        async with handler_client(handler) as ac:
            return await generate_json("m", "p", Answer, client=ac)

    assert asyncio.run(run()) == Answer(answer="42")


def test_bad_json_then_good_with_stricter_reminder():
    prompts = []

    def handler(request):
        prompts.append(body_prompt(request))
        text = "sorry, I cannot" if len(prompts) == 1 else '{"answer": "ok"}'
        return respond(text, request)

    async def run():
        async with handler_client(handler) as ac:
            return await generate_json("m", "p", Answer, client=ac)

    result = asyncio.run(run())
    assert result.answer == "ok"
    assert "STRICT" not in prompts[0] and "STRICT" in prompts[1]


def test_generate_json_raises_after_two_bad_replies():
    calls = []

    def handler(request):
        calls.append(request)
        return respond("not json at all", request)

    async def run():
        async with handler_client(handler) as ac:
            await generate_json("m", "p", Answer, client=ac)

    with pytest.raises(Exception):
        asyncio.run(run())
    assert len(calls) == 2


# --- acceptance: two concurrent calls run strictly one after the other --------
def test_concurrent_calls_are_serialized():
    events, state = [], {"active": 0, "max_active": 0}

    async def handler(request):
        model = json.loads(request.content)["model"]
        events.append(f"start:{model}")
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0.02)          # without the lock these would overlap
        state["active"] -= 1
        events.append(f"end:{model}")
        return respond(f"reply-{model}", request)

    async def run():
        async with handler_client(handler) as ac:
            return await asyncio.gather(
                generate("p1", model="A", client=ac),
                generate("p2", model="B", client=ac),
            )

    replies = asyncio.run(run())
    assert replies == ["reply-A", "reply-B"]
    assert state["max_active"] == 1
    assert events[0].startswith("start:") and events[1].startswith("end:")  # never start+start


# --- pure helper ---------------------------------------------------------------
def test_clean_json_text():
    assert clean_json_text('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert clean_json_text('Sure! {"a": 1,} hope that helps') == '{"a": 1}'
    assert clean_json_text('{"a": [1,2,],}') == '{"a": [1,2]}'


def test_generate_caps_output_tokens():
    # Hardware calibration: slow decode must never run away — every call ships num_predict.
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return respond('ok', request)

    asyncio.run(generate('hi', client=handler_client(handler), max_tokens=77))
    asyncio.run(generate('hi', client=handler_client(handler)))
    assert seen[0]['options']['num_predict'] == 77
    assert seen[1]['options']['num_predict'] == llm.MAX_TOKENS_PER_CALL
