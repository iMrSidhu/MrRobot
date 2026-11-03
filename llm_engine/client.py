"""Async Ollama client with VRAM serialization (DESIGN.md section 2 principle 3, section 4).

One process-wide ``asyncio.Semaphore(1)`` guarantees a single model call at a
time, so Model A (synthesis) and Model B (security) can never both load into
6GB VRAM. Talks plain HTTP to /api/generate like scripts/check_ollama.py does
(the `ollama` pip package is not needed). Transient failures are retried once;
persistent timeouts surface as LLMTimeout. generate_json() is the pydantic-
validated front door used by the workers.
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

FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

T = TypeVar("T", bound=BaseModel)


class LLMTimeout(RuntimeError):
    """Ollama did not answer within LLM_TIMEOUT_SEC (after the single retry)."""


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
                   client: httpx.AsyncClient | None = None) -> str:
    """One model call under the VRAM lock. Retries transient errors once.

    ``client`` is injected by tests; otherwise an ephemeral AsyncClient is
    created against settings.ollama_host and closed here.
    """
    model = model or settings.synthesis_model
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=settings.llm_timeout_sec)
    try:
        async with _MODEL_LOCK:
            last_exc: Exception | None = None
            for attempt in range(2):  # one retry on transient errors
                try:
                    resp = await client.post(
                        f"{settings.ollama_host.rstrip('/')}/api/generate",
                        json={"model": model, "prompt": prompt, "stream": False},
                        timeout=settings.llm_timeout_sec,
                    )
                    resp.raise_for_status()
                    return resp.json()["response"]
                except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
                    last_exc = exc
                    logger.warning("ollama call failed (attempt %d): %r", attempt + 1, exc)
            if isinstance(last_exc, httpx.TimeoutException):
                raise LLMTimeout(f"{model}: no answer within "
                                 f"{settings.llm_timeout_sec}s (2 attempts)") from last_exc
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
