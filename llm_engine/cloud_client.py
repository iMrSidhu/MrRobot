"""OpenCode Go cloud client — clone of llm_engine/client.py's transport, untouched.

Pick your backend:
  local model : python -m llm_engine          (llm_engine/client.py -> Ollama)
  cloud API   : python -m llm_engine.run_cloud (this module -> OpenCode Go)

Speaks the OpenAI-compatible Chat Completions API of OpenCode Go
(https://opencode.ai/v2/docs/console/go/), pinned to CLOUD_MODEL for BOTH
stages. The GPU VRAM semaphore and the hardware num_predict calibration are
local-box concerns only, so this clone drops the lock (the queue runs one
repo at a time anyway). JSON repair/validation loop is the same code.

Required env (.env, gitignored): OPENCODE_GO_API_KEY from OpenCode Console.
Optional: SENTINEL_CLOUD_MODEL (default deepseek-v4.1-flash),
OPENCODE_GO_BASE_URL (default the Go openai chat-completions base).
"""
import asyncio
import os
import uuid
from typing import Type, TypeVar

import httpx
from pydantic import BaseModel

# same package: reuse the schema-reminder text and the JSON repair verbatim
from llm_engine.client import _schema_reminder, clean_json_text
from shared.logging import get_logger

logger = get_logger("llm_engine.cloud")

DEFAULT_BASE_URL = "https://opencode.ai/inference/go/openai/v1"
API_KEY_ENV = "OPENCODE_GO_API_KEY"
CLOUD_MODEL = os.environ.get("SENTINEL_CLOUD_MODEL", "deepseek-v4.1-flash")
# hardware calibration: deepseek-v4.1-flash is a REASONING model — measured
# 2026-11-04, an 18k-char dossier chunk with max_tokens=8000 finished with
# finish_reason=length, 8000 hidden reasoning tokens and ZERO visible content;
# 16000 gives it headroom for reasoning + answer. Do not lower for speed.
MAX_TOKENS_PER_CALL = 16_000
# same policy the user set for local: answer time uncapped, connect bounded
REQUEST_TIMEOUT = httpx.Timeout(None, connect=30.0)
# stable per-process session id — Go asks for one to optimize routing/caching
SESSION_ID = uuid.uuid4().hex

T = TypeVar("T", bound=BaseModel)


async def generate(prompt: str, *, model: str | None = None,
                   client: httpx.AsyncClient | None = None,
                   max_tokens: int = MAX_TOKENS_PER_CALL) -> str:
    """One cloud call. ``model`` is accepted for signature parity with the
    local client but IGNORED — the cloud path always uses CLOUD_MODEL.
    Retries transient failures once, like the local client."""
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise RuntimeError(
            f"{API_KEY_ENV} is not set — copy your API key from OpenCode "
            "Console (opencode.ai/console, Go page) into .env")
    base = os.environ.get("OPENCODE_GO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    try:
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = await client.post(
                    f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}",
                             "x-opencode-session": SESSION_ID,
                             "User-Agent": "sentinel-github-analysis/1.0"},
                    json={"model": CLOUD_MODEL, "stream": False,
                          "max_tokens": max_tokens,
                          "messages": [{"role": "user", "content": prompt}]},
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                if not (content or "").strip():
                    # a fake-empty report is worse than a loud failure
                    raise RuntimeError(
                        f"{CLOUD_MODEL}: empty completion — model spent the "
                        f"whole max_tokens={max_tokens} budget on hidden reasoning")
                return content
            except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
                last_exc = exc
                logger.warning("opencode-go call failed (attempt %d): %r",
                               attempt + 1, exc)
        raise last_exc
    finally:
        if owns_client:
            await client.aclose()


async def generate_json(model: str, prompt: str, schema: Type[T], *,
                        client: httpx.AsyncClient | None = None) -> T:
    """Ask for schema-shaped JSON; validate with pydantic. Identical contract
    to llm_engine/client.py:generate_json — one retry with a STRICT reminder."""
    last_exc: Exception | None = None
    for attempt, strict in enumerate((False, True)):
        raw = await generate(prompt + _schema_reminder(schema, strict),
                             model=model, client=client)
        try:
            return schema.model_validate_json(clean_json_text(raw))
        except ValueError as exc:
            last_exc = exc
            logger.warning("%s: bad JSON (attempt %d): %s",
                           CLOUD_MODEL, attempt + 1, exc)
    raise last_exc
