"""Async Ollama client with VRAM serialization (DESIGN.md section 2 principle 3, section 4).

One process-wide ``asyncio.Semaphore(1)`` guarantees a single model call at a
time, so Model A (synthesis) and Model B (security) can never both load into
6GB VRAM. Talks plain HTTP to /api/generate like scripts/check_ollama.py does
(the `ollama` pip package is not needed). Transient
failures are retried once; answer time is uncapped (REQUEST_TIMEOUT).
generate_json() is the pydantic-validated front door used by the workers.
"""
import asyncio
import json
import re
from typing import Type, TypeVar

import httpx
from pydantic import BaseModel

from shared.config import settings
from shared.logging import get_logger

logger = get_logger("llm_engine")

# One call at a time, process-wide (DESIGN.md §2 principle 3: VRAM serialization).
_MODEL_LOCK = asyncio.Semaphore(1)

# Hardware calibration (first real run): 4.6 tok/s decode once the 9B spills
# past 6GB VRAM. Cap output LENGTH only (runaway generations) — answer TIME is
# deliberately uncapped, see REQUEST_TIMEOUT.
MAX_TOKENS_PER_CALL = 1500

# User decision 2026-11: let models take as long as they need — read/write/pool
# timeouts are None; only the TCP connect is bounded so a dead Ollama fails fast.
REQUEST_TIMEOUT = httpx.Timeout(None, connect=30.0)

FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

T = TypeVar("T", bound=BaseModel)


def _schema_reminder(schema: Type[BaseModel], strict: bool) -> str:
    text = ("\n\nRespond ONLY with a JSON object valid for this schema: "
            + json.dumps(schema.model_json_schema()))
    if strict:
        text += "\n\nSTRICT: no prose, no code fences, valid JSON only."
    return text


def clean_json_text(raw: str) -> str:
    """Strip code fences / chatter and repair the commonest LLM JSON mistakes."""
    match = FENCE_RE.search(raw)
    text = match.group(1) if match else raw
    if not match:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]      # drop prose around the object
    return TRAILING_COMMA_RE.sub(r"\1", text.strip())


async def generate(prompt: str, *, model: str | None = None,
                   client: httpx.AsyncClient | None = None,
                   max_tokens: int = MAX_TOKENS_PER_CALL) -> str:
    """One model call under the VRAM lock. Retries transient errors once.

    ``client`` is injected by tests; otherwise an ephemeral AsyncClient is
    created against settings.ollama_host and closed here.
    """
    model = model or settings.synthesis_model
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    try:
        async with _MODEL_LOCK:
            last_exc: Exception | None = None
            for attempt in range(2):  # one retry on transient errors
                try:
                    resp = await client.post(
                        f"{settings.ollama_host.rstrip('/')}/api/generate",
                        json={"model": model, "prompt": prompt, "stream": False,
                              "options": {"num_predict": max_tokens}},
                        timeout=REQUEST_TIMEOUT,
                    )
                    resp.raise_for_status()
                    return resp.json()["response"]
                except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
                    last_exc = exc
                    logger.warning("ollama call failed (attempt %d): %r", attempt + 1, exc)
            raise last_exc
    finally:
        if owns_client:
            await client.aclose()


async def generate_json(model: str, prompt: str, schema: Type[T], *,
                        client: httpx.AsyncClient | None = None) -> T:
    """Ask for schema-shaped JSON; validate with pydantic.

    On a parse/validation failure, retries ONCE with a stricter reminder.
    Raises the last ValidationError/ValueError if both attempts fail.
    """
    last_exc: Exception | None = None
    for attempt, strict in enumerate((False, True)):
        raw = await generate(prompt + _schema_reminder(schema, strict),
                             model=model, client=client)
        try:
            return schema.model_validate_json(clean_json_text(raw))
        except ValueError as exc:  # ValidationError and JSONDecodeError are ValueError
            last_exc = exc
            logger.warning("%s: bad JSON (attempt %d): %s", model, attempt + 1, exc)
    raise last_exc
