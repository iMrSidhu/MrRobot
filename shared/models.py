"""Inter-service contracts (DESIGN.md §2 isolation: services exchange these through the
DB/queue, never by importing each other's internals). Keep models small and documented."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Workflow states for repositories.status (DESIGN.md §2/§3)
STATUSES = ("QUEUED", "CLONING", "PROCESSED", "ANALYZING", "ANALYZED", "DONE", "FAILED_AUDIT")
RepoStatus = Literal["QUEUED", "CLONING", "PROCESSED", "ANALYZING", "ANALYZED", "DONE", "FAILED_AUDIT"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class RepoCandidate(BaseModel):
    """Ingestion -> Processor queue item: one newly discovered repo."""

    id: int  # GitHub repository id
    name: str  # "owner/repo" — the dedupe key in shared.db
    url: str  # clone URL
    stars: int


class ProcessedRepo(BaseModel):
    """Processor -> LLM engine: everything safely extracted from one clone (read-only text)."""

    repo_id: int
    name: str
    tree_text: str  # flattened directory tree (DESIGN.md §3 Step 3.3)
    readme_chunks: list[str] = []  # README split to fit CONTEXT_BUDGET_TOKENS
    code_chunks: list[str] = []  # core entry-point chunks
    security_candidate_files: list[str] = []  # paths most worth auditing (entry points, tool loaders)


class SynthesisResult(BaseModel):
    """Model A output (DESIGN.md §5 Phase 4): capability report."""

    architecture: str
    marketing_claims: list[str] = []
    verified_reality: list[str] = []
    gaps: list[str] = []  # claims not backed by code
    capability_tags: list[str] = []


class Finding(BaseModel):
    """One row of the security vulnerability matrix (DESIGN.md §5 Phase 4 Model B)."""

    severity: Severity
    file: str
    line: int
    description: str
    mitigation: str


class SecurityResult(BaseModel):
    """Model B output: full audit for one repo."""

    findings: list[Finding] = []
