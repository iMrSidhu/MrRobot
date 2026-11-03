r"""LIVE contract tests: real OpenCode Go model, real dashboard payload.

Skipped unless SENTINEL_LIVE=1 AND OPENCODE_GO_API_KEY is set, so the normal
offline suite (and CI) never spends tokens:

    $env:SENTINEL_LIVE='1'; .\.venv\Scripts\python.exe -m pytest tests/test_cloud_live.py -q

What they pin down is the CONTRACT the dashboard reads:
  center panel  -> SynthesisResult JSON (architecture, marketing_claims, tags)
  right panel   -> SecurityResult JSON (severity/file/line/description/mitigation)
  vault md      -> section headings app.py/report rendering depend on
"""
import asyncio
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from dotenv import load_dotenv

load_dotenv()  # key lives in .env; must be in os.environ BEFORE the marker below

pytestmark = pytest.mark.skipif(
    not (os.environ.get("SENTINEL_LIVE") == "1"
         and os.environ.get("OPENCODE_GO_API_KEY", "").strip()),
    reason="set SENTINEL_LIVE=1 (and OPENCODE_GO_API_KEY) to hit the live API")

from llm_engine import run_cloud
from llm_engine.report import build_report, write_report
from llm_engine.security import run_security
from llm_engine.synthesis import run_synthesis
from shared.models import SecurityResult, SynthesisResult

README = """# WidgetDB

An embedded vector database that is 100x faster than Postgres and runs on a
Raspberry Pi with zero dependencies.

## Features

- **Blazing fast**: single-digit microsecond queries via a SIMD index.
- **Tiny**: one C file, no install step.
- **Production ready**: used in by 10,000 companies worldwide.

## Install

```bash
pip install widgetdb
```
"""


def setup_module():
    run_cloud.use_cloud()  # same rebinding the real entry point does


def test_live_synthesis_provides_dashboard_center_panel():
    from shared.models import ProcessedRepo
    repo = ProcessedRepo(
        repo_id=1, name="acme/widgetdb", tree_text="README.md",
        readme_chunks=["=== README.md ===\n" + README],
        code_chunks=[], security_candidate_files=[])
    result = asyncio.run(run_synthesis(repo))
    assert isinstance(result, SynthesisResult)
    # center panel shows architecture text and a claim table + tag cloud:
    assert len(result.architecture.strip()) > 40, result.architecture
    assert any("fast" in c.lower() or "raspberry" in c.lower()
               for c in result.marketing_claims), result.marketing_claims
    assert isinstance(result.capability_tags, list)
    # and it must round-trip through the JSON the dashboard load_json() reads:
    assert SynthesisResult.model_validate_json(
        result.model_dump_json()).architecture == result.architecture


def test_live_security_provides_dashboard_finding_rows(tmp_path):
    from shared.models import ProcessedRepo
    victim = tmp_path / "app.py"
    victim.write_text('import os\n'
                      'API_KEY = "sk-liveTESTABCDEFGHIJKLMNOPQRSTUV"\n'
                      'def run(cmd):\n    os.system(cmd)\n')
    repo = ProcessedRepo(
        repo_id=2, name="acme/victim", tree_text="app.py",
        readme_chunks=[], code_chunks=[],
        security_candidate_files=["app.py"])
    result = asyncio.run(run_security(repo, tmp_path))
    assert isinstance(result, SecurityResult) and result.findings
    for f in result.findings:
        # right-panel table columns, all present and sane:
        assert f.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert f.file == "app.py" and 1 <= f.line <= 4
        assert f.description.strip() and f.mitigation.strip()
    # the planted key must survive regardless of model behaviour:
    assert any("sk-liveTEST" in f.description or "token" in f.description.lower()
               for f in result.findings), result.findings
    SecurityResult.model_validate_json(result.model_dump_json())


def test_live_pipeline_renders_report_the_vault_and_ui_expect():
    from shared.models import ProcessedRepo
    repo_row = {"name": "acme/widgetdb", "stars": 1234, "url": "https://x/y"}
    processed = ProcessedRepo(
        repo_id=3, name="acme/widgetdb", tree_text="README.md\napp.py",
        readme_chunks=["=== README.md ===\n" + README],
        code_chunks=[], security_candidate_files=[])
    synthesis = asyncio.run(run_synthesis(processed))
    security = asyncio.run(run_security(processed, pathlib.Path(__file__).parent))
    md = build_report(repo_row, synthesis, security)
    for heading in ("# acme/widgetdb", "## Architecture",
                    "## Marketing vs Reality", "## Capability tags",
                    "## Vulnerability matrix", "## Action items"):
        assert heading in md, md[:400]
    assert synthesis.architecture[:40] in md  # center panel text made it in
