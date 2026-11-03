"""Vault report generation (DESIGN.md section 5 step 5.1).

build_report() renders one repository's dual-model results as Markdown;
write_report() drops it at VAULT_DIR/<owner>__<repo>.md. Pure text: this
module never touches the (already-deleted) clone and never runs repo code.
"""
import re
from itertools import zip_longest
from pathlib import Path

from shared.config import settings
from shared.models import SecurityResult, SynthesisResult


def report_filename(name: str) -> str:
    """'owner/repo' -> 'owner__repo.md'; anything path-ish is neutralised."""
    parts = [re.sub(r"[^A-Za-z0-9._-]+", "_", p) for p in re.split(r"[/\\]+", name.strip("/")) if p]
    return ("__".join(parts) or "repo") + ".md"


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _table(header: tuple[str, ...], rows: list[tuple]) -> str:
    lines = ["| " + " | ".join(header) + " |",
             "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _claims_table(synthesis: SynthesisResult) -> str:
    pairs = zip_longest(synthesis.marketing_claims, synthesis.verified_reality, fillvalue="")
    rows = [(claim or "-", reality or "-") for claim, reality in pairs]
    return _table(("Marketing claim", "Verified reality"), rows or [("-", "-")])


def _tags(synthesis: SynthesisResult) -> str:
    return "\n".join(f"- `{tag}`" for tag in synthesis.capability_tags) or "None identified."


def _matrix(security: SecurityResult) -> str:
    if not security.findings:
        return "No vulnerabilities found."
    rows = [(f.severity, f"{f.file}:{f.line}", f.description, f.mitigation) for f in security.findings]
    return _table(("Severity", "File / Line", "Description", "Mitigation"), rows)


def _actions(security: SecurityResult) -> str:
    seen, items = set(), []
    for f in security.findings:
        if f.mitigation not in seen:
            seen.add(f.mitigation)
            items.append("- [ ] " + _cell(f.mitigation))
    return "\n".join(items) or "Nothing to action."


def build_report(repo: dict, synthesis: SynthesisResult, security: SecurityResult) -> str:
    """Full Markdown dossier: header, architecture, claims vs reality, tags, matrix, actions."""
    sections = [
        f"# {repo['name']}",
        f"**Stars:** {repo['stars']} | **Link:** {repo['url']}",
        "## Architecture\n\n" + _cell(synthesis.architecture),
        "## Marketing vs Reality\n\n" + _claims_table(synthesis),
        "## Capability tags\n\n" + _tags(synthesis),
        "## Vulnerability matrix\n\n" + _matrix(security),
        "## Action items\n\n" + _actions(security),
    ]
    return "\n\n".join(sections) + "\n"


def write_report(repo: dict, synthesis: SynthesisResult, security: SecurityResult, *,
                 vault_dir: Path | str | None = None) -> Path:
    """Write the dossier into the vault; returns the report path."""
    vault = Path(vault_dir or settings.vault_dir)
    vault.mkdir(parents=True, exist_ok=True)
    path = vault / report_filename(repo["name"])
    path.write_text(build_report(repo, synthesis, security), encoding="utf-8")
    return path
