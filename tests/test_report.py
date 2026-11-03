"""Tests for llm_engine.report (DESIGN.md 5.1) — golden-file comparison, no LLM."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_engine.report import build_report, report_filename, write_report
from shared.models import Finding, SecurityResult, SynthesisResult

REPO = {"id": 1, "name": "acme/rover", "url": "https://github.com/acme/rover", "stars": 1500}
SYNTH = SynthesisResult(
    architecture="Async Python harness for rover fleets.",
    marketing_claims=["Fleet-scale orchestration", "Zero-config setup"],
    verified_reality=["async loop in main.py"],
    gaps=["no config layer"],
    capability_tags=["robotics", "async"])
SEC = SecurityResult(findings=[
    Finding(severity="HIGH", file="main.py", line=12,
            description="subprocess shell=True", mitigation="Pass an argv list"),
    Finding(severity="LOW", file="cli.py", line=4,
            description="eval on input", mitigation="Use ast.literal_eval")])

GOLDEN = """# acme/rover

**Stars:** 1500 | **Link:** https://github.com/acme/rover

## Architecture

Async Python harness for rover fleets.

## Marketing vs Reality

| Marketing claim | Verified reality |
| --- | --- |
| Fleet-scale orchestration | async loop in main.py |
| Zero-config setup | - |

## Capability tags

- `robotics`
- `async`

## Vulnerability matrix

| Severity | File / Line | Description | Mitigation |
| --- | --- | --- | --- |
| HIGH | main.py:12 | subprocess shell=True | Pass an argv list |
| LOW | cli.py:4 | eval on input | Use ast.literal_eval |

## Action items

- [ ] Pass an argv list
- [ ] Use ast.literal_eval
"""


def test_golden_report(tmp_path):
    expected = tmp_path / "golden.md"
    expected.write_text(GOLDEN, encoding="utf-8")
    assert build_report(REPO, SYNTH, SEC) == expected.read_text(encoding="utf-8")


def test_empty_findings_render_cleanly(tmp_path):
    """Acceptance: no findings, no claims, no tags still yields a complete report."""
    empty = SynthesisResult(architecture="Small utility script.", marketing_claims=[],
                            verified_reality=[], gaps=[], capability_tags=[])
    md = build_report(REPO, empty, SecurityResult(findings=[]))
    assert "## Vulnerability matrix\n\nNo vulnerabilities found." in md
    assert "Nothing to action." in md
    assert "None identified." in md
    assert "None" not in md.replace("None identified.", "")  # no null leaks
    assert md.startswith("# acme/rover") and md.endswith("\n")


def test_pipes_and_newlines_escaped():
    nasty = SynthesisResult(architecture="a | b\nc", marketing_claims=["x|y"],
                           verified_reality=["1\n2"], gaps=[], capability_tags=["t|g"])
    md = build_report(REPO, nasty, SecurityResult(findings=[
        Finding(severity="LOW", file="a.py", line=1, description="d", mitigation="m | n")]))
    assert "| x\\|y | 1 2 |" in md       # table cells escaped + newlines flattened
    assert "a \\| b c" in md            # body: pipes escaped, newline flattened
    assert "m \\| n" in md
    assert "- `t|g`" in md              # bullets need no escaping


def test_report_filename():
    assert report_filename("acme/rover") == "acme__rover.md"
    assert report_filename("we ird/x y") == "we_ird__x_y.md"
    assert report_filename("../../evil") == "..__..__evil.md"  # no separators survive
    assert report_filename("solo") == "solo.md"


def test_write_report_places_file(tmp_path):
    vault = tmp_path / "vault"
    path = write_report(REPO, SYNTH, SEC, vault_dir=vault)
    assert path == vault / "acme__rover.md"
    assert path.read_text(encoding="utf-8") == GOLDEN
