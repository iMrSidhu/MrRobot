"""Tests for processor.chunker (DESIGN.md Step 3.3) — fixture trees, no LLM/network."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.chunker import (
    README_DIGEST_MAX_CHARS,
    chunk_text,
    digest_markdown,
    pack_items,
    process_repo,
    security_candidates,
    summarize_source,
)

MAIN_PY = '''"""Rover core loop."""
import os
from .tools import hammer

class Rover(Base):
    """Mars rover."""

    def run(self, cmd, timeout=5) -> str:
        """Execute a command string."""
        return cmd

async def loop(state):
    pass
'''

README_MD = "# Rover\n\nAutonomous Mars explorer with AI harness.\n" * 30


@pytest.fixture
def repo(tmp_path):
    files = {
        "README.md": README_MD,
        "main.py": MAIN_PY,
        "cli.py": "def broken(:\n    RUN_RAW_SENTINEL = 1\n",   # unparsable
        "app.js": "export function start() { return 1; }\n",
        "agent.py": "import subprocess\nsubprocess.list2cmdline([])\n",
        "utils.py": "def only_in_utils():\n    pass\n",
        "evil.py": ("import subprocess, pickle\n"
                    "subprocess.run('ls', shell=True)\n"
                    "os.system('rm -rf /')\n"
                    "eval(input())\nexec('x=1')\n"
                    "pickle.loads(data)\n"
                    "requests.get(url)\n"
                    "API_KEY = \"sk-abc123def456ghi789\"\n"),
        "clean.py": "x = 1\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return tmp_path


def all_chunks(result):
    return result.readme_chunks + result.code_chunks


# --- acceptance 1: no chunk exceeds the budget ------------------------------
def test_no_chunk_exceeds_budget(repo):
    result = process_repo(1, "acme/rover", repo, budget_tokens=25)  # 100 chars
    assert all_chunks(result)
    for chunk in all_chunks(result):
        assert len(chunk) <= 100, f"chunk of {len(chunk)} chars over budget"
    assert len(result.tree_text) <= 100  # tree is budgeted too


def test_budget_survives_one_giant_line(tmp_path):
    (tmp_path / "README.md").write_text("x" * 400)
    result = process_repo(1, "a/b", tmp_path, budget_tokens=25)
    assert result.readme_chunks and all(len(c) <= 100 for c in result.readme_chunks)


def test_chunk_text_and_pack_items_invariants():
    assert chunk_text("", 10) == []
    assert chunk_text("abc", 10) == ["abc"]
    assert chunk_text("abcdefg", 3) == ["abc", "def", "g"]
    assert pack_items([], 5) == []
    packed = pack_items(["aaa", "bbb", "ccccc"], 5)   # "ccccc" fits alone
    assert packed == ["aaa", "bbb", "ccccc"]


# --- AST summary + raw fallback ----------------------------------------------
def test_ast_summary_extracts_imports_signatures_docstrings(repo):
    summary = summarize_source(repo / "main.py")
    assert 'module docstring: "Rover core loop."' in summary
    assert "import os" in summary
    assert "from .tools import hammer" in summary
    assert "class Rover(Base)  # Mars rover." in summary
    assert "def run(self, cmd, timeout)" in summary
    assert "async def loop(state)" in summary
    assert "return cmd" not in summary  # bodies are NOT included


def test_unparsable_python_falls_back_to_raw(repo):
    summary = summarize_source(repo / "cli.py")
    assert summary.startswith("(raw text - could not parse)")
    assert "RUN_RAW_SENTINEL" in summary


# --- entry-point detection ----------------------------------------------------
def test_entry_points_only(repo):
    result = process_repo(1, "acme/rover", repo)
    joined = "\n".join(result.code_chunks)
    for entry in ("main.py", "cli.py", "app.js", "agent.py"):
        assert f"=== {entry} ===" in joined
    assert "utils.py" not in joined and "evil.py" not in joined
    assert "only_in_utils" not in joined


def test_non_python_entry_kept_raw(repo):
    joined = "\n".join(process_repo(1, "a/b", repo).code_chunks)
    assert "export function start()" in joined  # js has no AST path — raw text


# --- security candidates ------------------------------------------------------
def test_security_ranking_by_hit_count(repo):
    result = process_repo(1, "acme/rover", repo)
    cands = result.security_candidate_files
    assert cands[0] == "evil.py"
    assert "agent.py" in cands  # 1 subprocess hit ranks lower
    assert cands.index("evil.py") < cands.index("agent.py")
    assert "clean.py" not in cands and "main.py" not in cands
    assert all(not Path(c).is_absolute() for c in cands)  # relative paths only


def test_dynamic_url_pattern(repo):
    (repo / "dyn.py").write_text("import httpx\nhttpx.post(url, json=p)\n"
                                 'httpx.get("https://static.example")\n')
    from processor.filter import filter_repo
    cands = security_candidates(repo, filter_repo(repo))
    assert "dyn.py" in cands
    assert all(not Path(c).is_absolute() for c in cands)  # relative paths only


# --- ProcessedRepo shape ------------------------------------------------------
def test_processed_repo_fields(repo):
    result = process_repo(42, "acme/rover", repo)
    assert result.repo_id == 42 and result.name == "acme/rover"
    assert "main.py" in result.tree_text and "README.md" in result.tree_text
    assert result.readme_chunks  # README present
    assert "".join(result.readme_chunks).replace("=== README.md ===\n", "") \
        .count("Autonomous") >= 10  # most of the README survived chunking


# --- deterministic README digest (no LLM) --------------------------------------
def test_digest_keeps_structure_drops_noise():
    readme = "\n".join([
        "[![build](https://img.shields.io/ci.svg)](https://ci)",
        '<p align="center"><img src="logo.png"></p>',
        "# Colibri",
        "Tagline sentence under the heading.",
        "A long prose paragraph about the vision that should be dropped.",
        "## Quickstart",
        "Run `colibri run`.",
        "More prose nobody needs at this stage.",
        "- Fast: benchmarked startup",
        "- Safe: sandboxed tools",
        "```bash",
        "pip install colibri",
        "```",
    ])
    digest = digest_markdown(readme)
    assert "# Colibri" in digest and "## Quickstart" in digest
    assert "Tagline sentence" in digest and "Run `colibri run`." in digest
    assert "- Fast: benchmarked startup" in digest and "pip install colibri" in digest
    assert "shields.io" not in digest and "<p align" not in digest
    assert "vision that should" not in digest and "More prose" not in digest


def test_digest_caps_long_code_fences():
    body = "\n".join(f"echo line {i}" for i in range(25))
    digest = digest_markdown(f"# T\n\n```sh\n{body}\n```\n")
    assert "echo line 0" in digest and "echo line 9" in digest
    assert "echo line 10" not in digest
    assert "(15 fence lines dropped)" in digest


def test_digest_fallback_and_cap():
    prose = "word " * 40_000  # no markdown structure at all
    assert digest_markdown(prose) == prose[:README_DIGEST_MAX_CHARS]
    big = "\n".join(f"# H{i}\nlead {i}" for i in range(3000))
    cut = digest_markdown(big)
    assert cut.endswith("(digest truncated)")
    assert len(cut) <= README_DIGEST_MAX_CHARS + 30
