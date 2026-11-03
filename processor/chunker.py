"""Directory tree + LLM context chunks (DESIGN.md section 5, Step 3.3; section 4 "Code Processing").

Reads a filtered clone (processor.filter) as plain text only — nothing here
imports or executes cloned code. Token estimate is chars/4 (design §4 keeps it
deliberately crude); every returned chunk is guaranteed <= CONTEXT_BUDGET_TOKENS
* 4 characters. Python entry points are reduced to an AST summary (imports,
class/function signatures, docstrings); anything unparseable falls back to raw
text instead of crashing.
"""
import ast
import re
from pathlib import Path

from processor.filter import KeptFile, filter_repo
from shared.config import settings
from shared.models import ProcessedRepo

# Edit-friendly constants ----------------------------------------------------
ENTRYPOINT_STEMS = {"main", "__main__", "cli", "app", "agent"}  # exact stem match
SECURITY_PATTERNS = {
    "subprocess": re.compile(r"\bsubprocess\b"),
    "eval": re.compile(r"\beval\("),
    "exec": re.compile(r"\bexec\("),
    "pickle": re.compile(r"\bpickle\b"),
    "os.system": re.compile(r"os\.system\("),
    "shell=True": re.compile(r"shell\s*=\s*True\b"),
    # dynamic URL: a requests/httpx call whose first arg is a variable, not a literal
    "dynamic-url": re.compile(
        r"\b(?:requests|httpx)\.(?:get|post|put|delete|patch|head|request|stream)\(\s*[A-Za-z_]\w*\s*[,)]"),
    "secret-string": re.compile(  # API_KEY = "long-ish value" style assignments
        r"(?i)\b\w*(?:api|key|secret|token|password)\w*\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"),
    "known-token-prefix": re.compile(
        r"\b(?:sk|ghp|gho|github_pat|AKIA|xox[bap])[\-_][A-Za-z0-9\-_.]{8,}\b"),
}
TRUNCATE_MARK = "\n... (tree truncated)"


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text into <= max_chars pieces (line boundaries; oversized single
    lines are hard-sliced). Empty text yields no chunks."""
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > max_chars:
            head, line = line[:max_chars], line[max_chars:]
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(head)
        if len(cur) + len(line) <= max_chars:
            cur += line
        else:
            if cur:
                chunks.append(cur)
            cur = line
    if cur:
        chunks.append(cur)
    return chunks


def pack_items(items: list[str], max_chars: int) -> list[str]:
    """Greedy bin-packing of whole items; items bigger than the budget get
    hard-split via chunk_text. Guarantees every chunk is <= max_chars."""
    chunks, cur = [], ""
    for item in items:
        candidate = f"{cur}\n\n{item}" if cur else item
        if len(candidate) <= max_chars:
            cur = candidate
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        if len(item) <= max_chars:
            cur = item
        else:
            chunks.extend(chunk_text(item, max_chars))
    if cur:
        chunks.append(cur)
    return chunks


def _signature(fn: ast.AST) -> str:
    args = fn.args
    parts = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    star_at = len(args.posonlyargs + args.args)
    if args.vararg:
        parts.insert(star_at, f"*{args.vararg.arg}")
    elif args.kwonlyargs:
        parts.insert(star_at, "*")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    kw = "async def" if isinstance(fn, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(fn.returns)}" if fn.returns else ""
    return f"{kw} {fn.name}({', '.join(parts)}){ret}"


def _doc_note(node: ast.AST) -> str:
    doc = ast.get_docstring(node)
    return f"  # {doc.splitlines()[0]}" if doc else ""


def summarize_source(path: Path) -> str:
    """AST summary for .py files, raw text otherwise. Syntax errors fall back
    to raw text (read_text uses errors='replace', so decoding never throws)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() != ".py":
        return text
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return f"(raw text - could not parse)\n{text}"
    lines = []
    module_doc = ast.get_docstring(tree)
    if module_doc:
        lines.append(f'module docstring: "{module_doc.splitlines()[0]}"')
    imports, classes, funcs = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            line = ast.unparse(node)
            if line not in imports:
                imports.append(line)
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            name = f"class {node.name}" + (f"({bases})" if bases else "")
            classes.append(name + _doc_note(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(_signature(node) + _doc_note(node))
    return "\n".join(lines + imports + classes + funcs) or "(no imports, classes or functions)"


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def build_tree(root: Path, kept: list[KeptFile], max_chars: int) -> str:
    """Flattened text tree: every kept file's relative path, one per line."""
    tree = "\n".join(_rel(root, k.path) for k in kept)
    if len(tree) > max_chars:
        tree = tree[: max(0, max_chars - len(TRUNCATE_MARK))] + TRUNCATE_MARK
    return tree


def find_entry_points(kept: list[KeptFile]) -> list[KeptFile]:
    return [k for k in kept if k.path.stem.lower() in ENTRYPOINT_STEMS]


def security_candidates(root: Path, kept: list[KeptFile]) -> list[str]:
    """Relative paths of files matching SECURITY_PATTERNS, ranked by hit count.

    shortcut: regex heuristics over file text, no semantics — if precision
    ever matters, upgrade to an AST/taint pass in the dedicated security worker.
    """
    scored = []
    for k in kept:
        text = k.path.read_text(encoding="utf-8", errors="replace")
        hits = sum(len(pat.findall(text)) for pat in SECURITY_PATTERNS.values())
        if hits:
            scored.append((-hits, _rel(root, k.path)))
    return [path for _, path in sorted(scored)]


def process_repo(repo_id: int, name: str, root: str | Path,
                 budget_tokens: int | None = None) -> ProcessedRepo:
    """Turn a filtered clone into the ProcessedRepo contract for both LLMs."""
    root = Path(root)
    budget = budget_tokens or settings.context_budget_tokens
    max_chars = max(1, budget * 4)  # token estimate = chars/4
    kept = filter_repo(root)

    readmes = [f"=== {_rel(root, k.path)} ===\n"
               f"{k.path.read_text(encoding='utf-8', errors='replace')}"
               for k in kept if k.language == "Markdown"]
    code_items = [f"=== {_rel(root, k.path)} ===\n{summarize_source(k.path)}"
                  for k in find_entry_points(kept)]

    return ProcessedRepo(
        repo_id=repo_id,
        name=name,
        tree_text=build_tree(root, kept, max_chars),
        readme_chunks=pack_items(readmes, max_chars),
        code_chunks=pack_items(code_items, max_chars),
        security_candidate_files=security_candidates(root, kept),
    )
