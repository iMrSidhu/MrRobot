import pathlib
import sys

import pytest
from pydantic import ValidationError

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.models import (  # noqa: E402
    STATUSES,
    Finding,
    ProcessedRepo,
    RepoCandidate,
    SecurityResult,
    SynthesisResult,
)


def test_repo_candidate_roundtrip():
    c = RepoCandidate(id=1, name="a/b", url="https://x", stars=1200)
    assert RepoCandidate.model_validate(c.model_dump()) == c


def test_defaults_are_empty_containers():
    p = ProcessedRepo(repo_id=1, name="a/b", tree_text="src/\n  main.py")
    assert p.readme_chunks == [] and p.code_chunks == [] and p.security_candidate_files == []
    assert SynthesisResult(architecture="async workers").capability_tags == []


def test_security_matrix_finding():
    s = SecurityResult(
        findings=[
            Finding(severity="HIGH", file="app.py", line=10, description="eval on user input", mitigation="allowlist")
        ]
    )
    assert s.findings[0].severity == "HIGH"


def test_severity_and_statuses_are_enforced():
    with pytest.raises(ValidationError):
        Finding(severity="MEGA", file="x", line=1, description="d", mitigation="m")
    assert STATUSES == ("QUEUED", "CLONING", "PROCESSED", "ANALYZING", "ANALYZED", "DONE", "FAILED_AUDIT")
