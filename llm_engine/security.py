"""Model B security worker (DESIGN.md section 5 Phase 4, section 3 step 3.3).

run_security(processed_repo, root) -> SecurityResult:
1. deterministic regex scan for hardcoded secrets across the repo files;
2. LLM audit (Model B) of the top security_candidate_files;
3. validation: every finding must point at a real file under ``root`` and a
   line number inside it — hallucinated rows are dropped;
4. duplicates merged, findings sorted CRITICAL -> LOW.

``root`` is the directory that currently holds the repo's files: the processor
wipes its clone after chunking (step 09), so the analysis service (step 13)
re-clones (or otherwise restores) before calling this.
"""
import re
from pathlib import Path

import httpx

from llm_engine.client import generate_json
from shared.config import settings
from shared.logging import get_logger
from shared.models import Finding, ProcessedRepo, SecurityResult, Severity

logger = get_logger("llm_engine.security")

TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "security.md"
MAX_SCAN_BYTES = 200_000          # same cap as processor/filter (shortcut: value duplicated, services stay independent)
CHARS_PER_TOKEN = 4               # same estimate as processor/chunker.py
SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# label -> (regex, severity, mitigation) — deterministic hardcoded-secret scan
SECRET_PATTERNS: dict[str, tuple[re.Pattern, Severity, str]] = {
    "known-token-prefix": (re.compile(
        r"(?:sk|ghp|gho|ghu|ghs|ghr|github_pat|AIza|AKIA|xox)[-_]"
        r"[A-Za-z0-9_-]{16,}"), "CRITICAL",
        "Remove the key, rotate it immediately, load from env/secret store."),
    "hardcoded-credential": (re.compile(
        r"(?i)\b\w*(api[_-]?key|secret|token|passwo?rd|credential)\w*\s*[:=]\s*"
        r"['\"][^'\"]{8,}['\"]"), "HIGH",
        "Move the value to an environment variable or secret manager."),
    "private-key-block": (re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "CRITICAL",
        "Delete the embedded key and use a key file outside the repo, rotated."),
    "credentials-in-url": (re.compile(
        r"(?i)\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s:@]+@\S+"), "HIGH",
        "Strip user:pass from URLs; authenticate via env-provided credentials."),
}


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _read(path: Path) -> list[str] | None:
    """Lines of a small text file, or None if binary/too big."""
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        data = path.read_bytes()
        if b"\0" in data[:4096]:
            return None
        return data.decode("utf-8", errors="ignore").splitlines()
    except OSError:
        return None


def scan_secrets(root: Path) -> list[Finding]:
    """Deterministic hardcoded-secret sweep over every small text file."""
    root = Path(root).resolve()
    findings: list[Finding] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        lines = _read(path)
        if lines is None:
            continue
        for lineno, line in enumerate(lines, 1):
            for label, (rx, severity, mitigation) in SECRET_PATTERNS.items():
                if rx.search(line):
                    excerpt = line.strip()[:120]
                    findings.append(Finding(
                        severity=severity, file=_rel(path, root), line=lineno,
                        description=f"{label}: {excerpt}", mitigation=mitigation))
    return findings


def _audit_text(repo: ProcessedRepo, root: Path) -> str:
    """Concatenate top-ranked candidate files for the Model B prompt."""
    root = Path(root).resolve()
    budget = settings.context_budget_tokens * CHARS_PER_TOKEN // 2
    parts: list[str] = []
    used = 0
    for rel in repo.security_candidate_files:
        path = (root / rel).resolve()
        if root not in path.parents or not path.is_file():
            continue
        lines = _read(path)
        if lines is None:
            continue
        block = f"=== {rel} ===\n" + "\n".join(lines)[:8000]
        if used + len(block) > budget:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def validate_findings(findings: list[Finding], root: Path) -> list[Finding]:
    """Drop findings whose file doesn't exist under root or line is out of range."""
    root = Path(root).resolve()
    kept: list[Finding] = []
    cache: dict[str, int | None] = {}
    for f in findings:
        path = (root / f.file).resolve()
        if root not in path.parents or not path.is_file():
            logger.warning("dropped finding for missing file %s", f.file)
            continue
        if f.file not in cache:
            lines = _read(path)
            cache[f.file] = None if lines is None else len(lines)
        total = cache[f.file]
        if total is None or not (1 <= f.line <= total):
            logger.warning("dropped finding %s:%s (file has %s lines)",
                           f.file, f.line, total)
            continue
        kept.append(f)
    return kept


def merge_findings(findings: list[Finding]) -> list[Finding]:
    """Dedupe identical (file, line, description) rows; sort CRITICAL -> LOW."""
    seen: set[tuple[str, int, str]] = set()
    merged: list[Finding] = []
    for f in sorted(findings, key=lambda x: (SEVERITY_RANK[x.severity], x.file, x.line)):
        key = (f.file, f.line, f.description)
        if key in seen:
            continue
        seen.add(key)
        merged.append(f)
    return merged


async def run_security(repo: ProcessedRepo, root: Path, *,
                       client: httpx.AsyncClient | None = None) -> SecurityResult:
    """Full Model B pass: regex sweep first, LLM audit of candidates second."""
    root = Path(root).resolve()
    deterministic = scan_secrets(root)
    findings = list(deterministic)
    material = _audit_text(repo, root)
    if material:
        known = "\n".join(f"- {f.file}:{f.line} {f.description}"
                          for f in deterministic) or "(none)"
        prompt = (TEMPLATE_PATH.read_text(encoding="utf-8")
                  .replace("{name}", repo.name)
                  .replace("{known}", known)
                  .replace("{tree}", repo.tree_text or "(none)")
                  .replace("{files}", material))
        result = await generate_json(settings.security_model, prompt,
                                     SecurityResult, client=client)
        findings.extend(result.findings)
    else:
        logger.info("%s: no candidate files to hand to Model B", repo.name)
    validated = merge_findings(validate_findings(findings, root))
    return SecurityResult(findings=validated)
