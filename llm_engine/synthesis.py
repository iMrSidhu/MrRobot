"""Model A synthesis worker (DESIGN.md section 5 Phase 4, section 3 step 3.3).

run_synthesis(processed_repo) -> SynthesisResult. The prompt template lives
in llm_engine/prompts/synthesis.md so it can be tuned without touching code.
When the material for a template slot exceeds its share of the context budget
(Context Model Adaptation: tokens ~= chars/4, same heuristic as the chunker),
that slot is summarized chunk-by-chunk into a compressed dossier and the final
call merges the dossiers — small repos stay a single LLM call.
"""
from pathlib import Path

import httpx

from llm_engine.client import generate, generate_json
from shared.config import settings
from shared.logging import get_logger
from shared.models import ProcessedRepo, SynthesisResult

logger = get_logger("llm_engine.synthesis")

TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "synthesis.md"
CHARS_PER_TOKEN = 4
SUMMARY_PROMPT = (
    "Compress into concise bullet notes, keeping every architectural fact, "
    "feature claim and file reference (PARTIAL DOSSIER pass, not the final "
    "answer):\n\n"
)
# Hardware calibration (first real run, 6GB GPU): ~4.6 tok/s decode — one call
# per group of a 500k-char README would take hours. Compress at most this many
# groups per slot; the remainder is truncated and disclosed to the model.
MAX_DOSSIER_GROUPS = 4


def _budget_chars() -> int:
    return settings.context_budget_tokens * CHARS_PER_TOKEN


def _groups(items: list[str], max_chars: int) -> list[list[str]]:
    """Greedy line-safe packing of chunks into <= max_chars groups."""
    expanded: list[str] = []
    for it in items:
        while len(it) > max_chars:
            cut = it.rfind("\n", 0, max_chars) + 1 or max_chars
            expanded.append(it[:cut])
            it = it[cut:]
        expanded.append(it)
    groups: list[list[str]] = []
    cur: list[str] = []
    n = 0
    for it in expanded:
        if cur and n + len(it) + 2 > max_chars:
            groups.append(cur)
            cur, n = [], 0
        cur.append(it)
        n += len(it) + 2
    if cur:
        groups.append(cur)
    return groups


async def _fit(items: list[str], label: str, alloc: int, *,
               model: str, client: httpx.AsyncClient | None) -> str:
    """Return items joined to <= alloc chars, summarizing via LLM if needed."""
    text = "\n\n".join(i for i in items if i)
    if len(text) <= alloc:
        return text
    summaries = []
    groups = _groups(items, alloc)
    truncated = sum(len(g) for g in groups[MAX_DOSSIER_GROUPS:])
    for group in groups[:MAX_DOSSIER_GROUPS]:
        part = await generate(SUMMARY_PROMPT + "\n\n".join(group),
                              model=model, client=client)
        summaries.append(part.strip())
    logger.info("slot %s compressed: %d -> %d chars via %d dossier passes (%d chars dropped)",
                label, len(text), sum(len(s) for s in summaries), len(summaries), truncated)
    merged = "\n".join(summaries)
    if truncated:
        merged += f"\n(dossier covered only the first {alloc * MAX_DOSSIER_GROUPS} of {len(text)} chars)"
    # shortcut: dossiers assumed to compress below alloc; hard-cut if not,
    # revisit only if models ever return longer summaries than input.
    return merged[:alloc]


async def run_synthesis(repo: ProcessedRepo, *, model: str | None = None,
                        client: httpx.AsyncClient | None = None) -> SynthesisResult:
    """Analyze one processed repository with Model A (blocking on LLM lock)."""
    model = model or settings.synthesis_model
    # alloc: template overhead ignored — chars/4 is an estimate anyway (shortcut)
    alloc = max(_budget_chars() // 3, 500)
    tree = await _fit([repo.tree_text], "tree", alloc, model=model, client=client)
    readme = await _fit(repo.readme_chunks, "readme", alloc, model=model, client=client)
    code = await _fit(repo.code_chunks, "code", alloc, model=model, client=client)
    prompt = (TEMPLATE_PATH.read_text(encoding="utf-8")
              .replace("{name}", repo.name)
              .replace("{tree}", tree or "(none)")
              .replace("{readme}", readme or "(none)")
              .replace("{code}", code or "(none)"))
    return await generate_json(model, prompt, SynthesisResult, client=client)
