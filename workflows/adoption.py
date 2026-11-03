"""Adoption-risk workflows (design v2 step 18).

Dependency inventory + vulnerability evidence, derived only from files inside a
shallow clone and public OSV data. Nothing here imports, installs or executes
repository code, and no value is invented: unsupported inputs, missing tools and
failed queries become explicit unavailable/partial states.

shortcut: no Syft/ScanCode binaries on this host, so manifests are parsed
directly and OSV is queried over HTTP; swap the inventory for a Syft adapter and
licenses for ScanCode once those tools are pinned. Upgrade when a real SBOM tool
must supply transitive graphs.
"""
from __future__ import annotations

import json
import re
import subprocess
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from processor.clone import CloneError, cleanup, clone_repo, sanitize_dir_name
from shared import db
from shared.config import settings

OSV_API = "https://api.osv.dev/v1"
OSV_TIMEOUT_SEC = 30
MAX_QUERIES = 500          # bound OSV work per run
MAX_DETAIL_FETCHES = 200   # bound detail lookups per run
MAX_FILE_BYTES = 2_000_000

REQ_FILES = ("requirements.txt", "requirements-dev.txt", "requirements/base.txt")
LOCK_FILES = ("poetry.lock", "uv.lock")
MANIFEST_FILES = ("pyproject.toml", "setup.cfg", "setup.py")
LICENSE_PATTERN = re.compile(r"^(licen[cs]e|copying|notice)(\..*)?$", re.IGNORECASE)

# name==1.2.3, optional extras and trailing comment
_REQ_EXACT = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*(?P<version>[A-Za-z0-9][A-Za-z0-9.+_-]*)$")

# GHSA uses MODERATE; the UI and SecurityResult use MEDIUM.
SEVERITY_ALIASES = {"MODERATE": "MEDIUM"}


@dataclass
class Component:
    name: str
    version: str | None
    ecosystem: str = "PyPI"
    source: str = ""
    evidence: str = ""
    resolved: bool = False


@dataclass
class ManifestScan:
    manifests: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)


def _read(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def parse_requirement_lines(text: str, source: str) -> tuple[list[Component], list[dict]]:
    """Return exact pins and unresolved specs from a pip requirements file."""
    resolved: list[Component] = []
    unresolved: list[dict] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http:", "https:", "file:")):
            continue
        match = _REQ_EXACT.match(line)
        if match:
            resolved.append(
                Component(
                    name=match.group("name"),
                    version=match.group("version"),
                    source=source,
                    evidence=line,
                    resolved=True,
                )
            )
        else:
            name = re.split(r"[<>=!~;\[\s]", line, 1)[0]
            unresolved.append({"name": name, "spec": line, "source": source,
                               "reason": "not pinned to an exact version"})
    return resolved, unresolved


def parse_lockfile(text: str, source: str) -> list[Component]:
    """poetry.lock / uv.lock: both are TOML arrays of [[package]] name+version."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    out: list[Component] = []
    for pkg in data.get("package", []):
        if not isinstance(pkg, dict):
            continue
        name, version = pkg.get("name"), pkg.get("version")
        if isinstance(name, str) and isinstance(version, str):
            out.append(Component(name=name, version=version, source=source,
                                 evidence=f"[[package]] {name} {version}", resolved=True))
    return out


def parse_pyproject(text: str, source: str) -> tuple[list[Component], list[dict]]:
    """PEP 621 and Poetry dependency tables: only `==` pins are exact."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return [], []
    project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
    specs: list[str] = []
    for key in ("dependencies",):
        specs.extend(s for s in project.get(key, []) if isinstance(s, str))
    optional = project.get("optional-dependencies", {})
    if isinstance(optional, dict):
        for items in optional.values():
            specs.extend(s for s in items if isinstance(s, str))
    poetry = data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
    poetry_deps = poetry.get("dependencies", {}) if isinstance(poetry, dict) else {}
    if isinstance(poetry_deps, dict):
        for name, spec in poetry_deps.items():
            if name.lower() == "python":
                continue
            if isinstance(spec, str):
                specs.append(f"{name}{spec}" if spec and spec[0] in "<>=!~^" else f"{name}=={spec}")
            elif isinstance(spec, dict) and isinstance(spec.get("version"), str):
                specs.append(f"{name}{spec['version']}")
    resolved: list[Component] = []
    unresolved: list[dict] = []
    for spec in specs:
        match = _REQ_EXACT.match(spec.strip())
        if match:
            resolved.append(Component(name=match.group("name"), version=match.group("version"),
                                      source=source, evidence=spec, resolved=True))
        else:
            unresolved.append({"name": re.split(r"[<>=!~;\[\s]", spec, 1)[0], "spec": spec,
                               "source": source, "reason": "range, not an exact pin"})
    return resolved, unresolved


def declared_licenses(text: str) -> list[str]:
    """License strings declared in pyproject metadata (evidence, not classification)."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    out: list[str] = []
    project = data.get("project", {})
    if isinstance(project, dict):
        license_value = project.get("license")
        if isinstance(license_value, str):
            out.append(license_value)
        elif isinstance(license_value, dict) and isinstance(license_value.get("text"), str):
            out.append(license_value["text"])
    poetry = data.get("tool", {}).get("poetry", {})
    if isinstance(poetry, dict) and isinstance(poetry.get("license"), str):
        out.append(poetry["license"])
    return out


def collect_manifests(root: Path) -> ManifestScan:
    scan = ManifestScan()
    for rel in REQ_FILES:
        path = root / rel
        if not path.is_file():
            continue
        text = _read(path)
        if text is None:
            scan.skipped.append(f"{rel} (unreadable or over size limit)")
            continue
        scan.manifests.append(rel)
        resolved, unresolved = parse_requirement_lines(text, rel)
        scan.components.extend(resolved)
        scan.unresolved.extend(unresolved)

    for rel in LOCK_FILES:
        path = root / rel
        if not path.is_file():
            continue
        text = _read(path)
        if text is None:
            scan.skipped.append(f"{rel} (unreadable or over size limit)")
            continue
        components = parse_lockfile(text, rel)
        if components:
            scan.manifests.append(rel)
            scan.components.extend(components)
        else:
            scan.skipped.append(f"{rel} (no parseable packages)")

    pyprojects = [p for p in [root / "pyproject.toml"] if p.is_file()]
    nested = sorted(root.glob("*/pyproject.toml")) + sorted(root.glob("*/*/pyproject.toml"))
    pyprojects += [p for p in nested if p.is_file()][:10]
    for path in pyprojects:
        rel = path.relative_to(root).as_posix()
        text = _read(path)
        if text is None:
            scan.skipped.append(f"{rel} (unreadable or over size limit)")
            continue
        resolved, unresolved = parse_pyproject(text, rel)
        scan.manifests.append(rel)
        scan.components.extend(resolved)
        scan.unresolved.extend(unresolved)

    for rel in MANIFEST_FILES:
        if (root / rel).is_file() and rel not in scan.manifests:
            scan.skipped.append(f"{rel} (executable/legacy metadata, not parsed)")

    seen: set[tuple[str, str | None]] = set()
    unique: list[Component] = []
    for component in scan.components:
        key = (component.name.lower(), component.version)
        if key in seen:
            continue
        seen.add(key)
        unique.append(component)
    scan.components = unique
    return scan


def _http_json(url: str, payload: dict | None, timeout: int = OSV_TIMEOUT_SEC) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"content-type": "application/json", "accept": "application/json"},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def query_osv(components: list[Component], http=_http_json) -> dict:
    """Return {state, findings, queried, error}. Never reports 0 vulns on failure."""
    pinned = [c for c in components if c.resolved and c.version][:MAX_QUERIES]
    if not pinned:
        return {"state": "unavailable", "findings": [], "queried": 0,
                "error": "no exact versions to query"}
    queries = [{"package": {"name": c.name, "ecosystem": c.ecosystem}, "version": c.version}
               for c in pinned]
    try:
        batch = http(f"{OSV_API}/querybatch", {"queries": queries})
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {"state": "unavailable", "findings": [], "queried": len(queries),
                "error": f"OSV query failed: {exc}"}

    results = batch.get("results", []) if isinstance(batch, dict) else []
    ids: list[tuple[str, Component]] = []
    for component, result in zip(pinned, results):
        for vuln in (result or {}).get("vulns", []) or []:
            vuln_id = vuln.get("id")
            if isinstance(vuln_id, str):
                ids.append((vuln_id, component))

    findings: list[dict] = []
    seen_ids: set[str] = set()
    detail_errors = 0
    for vuln_id, component in ids:
        key = f"{vuln_id}:{component.name}@{component.version}"
        if key in seen_ids:
            continue
        seen_ids.add(key)
        detail: dict = {}
        if len(seen_ids) <= MAX_DETAIL_FETCHES:
            try:
                detail = http(f"{OSV_API}/vulns/{vuln_id}", None)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                detail_errors += 1
        affected = detail.get("affected", []) if isinstance(detail, dict) else []
        fixed: list[str] = []
        severities: list[str] = []
        top_specific = detail.get("database_specific") if isinstance(detail, dict) else None
        if isinstance(top_specific, dict) and top_specific.get("severity"):
            severities.append(str(top_specific["severity"]).upper())
        for entry in affected if isinstance(affected, list) else []:
            if not isinstance(entry, dict):
                continue
            database_specific = entry.get("database_specific") or {}
            if isinstance(database_specific, dict) and database_specific.get("severity"):
                severities.append(str(database_specific["severity"]).upper())
            for rng in entry.get("ranges", []) or []:
                if not isinstance(rng, dict):
                    continue
                for event in rng.get("events", []) or []:
                    if isinstance(event, dict) and event.get("fixed"):
                        fixed.append(str(event["fixed"]))
        findings.append({
            "id": vuln_id,
            "aliases": [a for a in detail.get("aliases", []) if isinstance(a, str)],
            "summary": detail.get("summary") or "",
            "severity": SEVERITY_ALIASES.get(severities[0], severities[0]) if severities else "UNKNOWN",
            "severity_raw": severities[0] if severities else None,
            "package": component.name,
            "version": component.version,
            "fixed_versions": sorted(set(fixed)),
            "published": detail.get("published"),
            "modified": detail.get("modified") or (detail.get("database_specific") or {}).get("modified") or None,
            "source": f"OSV {vuln_id}",
            "detail_available": bool(detail),
        })

    state = "available" if detail_errors == 0 else "partial"
    error = None
    if detail_errors:
        error = f"{detail_errors} advisory detail lookup(s) failed; rows show IDs without summaries"
    if len(ids) > MAX_DETAIL_FETCHES:
        state = "partial"
        error = f"detail lookups capped at {MAX_DETAIL_FETCHES} of {len(ids)} matches"
    return {"state": state, "findings": findings, "queried": len(queries), "error": error}


def collect_licenses(root: Path) -> dict:
    """Declared/license-file evidence only; ScanCode is absent on this host."""
    files: list[dict] = []
    declared: list[str] = []
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        if not path.is_file() or not LICENSE_PATTERN.match(path.name):
            continue
        text = _read(path)
        if text is None:
            continue
        head = " ".join(text.split())[:400]
        files.append({"file": path.name, "excerpt": head})
    for pyproject in [root / "pyproject.toml", *sorted(root.glob("*/pyproject.toml"))]:
        if pyproject.is_file():
            text = _read(pyproject)
            if text:
                declared.extend(declared_licenses(text))
    return {
        "state": "partial",
        "tool": "scancode: unavailable",
        "files": files,
        "declared": sorted(set(declared)),
        "note": "License text and declared strings are evidence only; no SPDX classification was run.",
    }


def build_report(repo: dict, sha: str | None, scan: ManifestScan, vulns: dict, licenses: dict) -> dict:
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    unknowns: list[str] = []
    if not scan.manifests:
        unknowns.append("No supported manifest or lockfile found; dependency coverage is zero.")
    if scan.unresolved:
        unknowns.append(f"{len(scan.unresolved)} declared dependencies are not exact pins and were not queried.")
    if not sha:
        unknowns.append("Pinned commit SHA could not be read from the clone.")
    if vulns["state"] != "available":
        unknowns.append("Vulnerability matching did not complete for every component.")
    if not licenses["files"]:
        unknowns.append("No license file found at the repository root.")

    return {
        "schema": "adoption/1",
        "repo": {
            "id": repo["id"],
            "name": repo["name"],
            "url": repo["url"],
            "sha": sha,
            "collected_at": collected_at,
        },
        "tools": {
            "inventory": "manifest parser (Syft unavailable on host)",
            "vulnerabilities": f"OSV API ({vulns['state']})",
            "licenses": licenses["tool"],
        },
        "sbom": {
            "components": [
                {"name": c.name, "version": c.version, "ecosystem": c.ecosystem,
                 "source": c.source, "evidence": c.evidence}
                for c in scan.components
            ],
            "manifests": scan.manifests,
            "skipped_inputs": scan.skipped,
            "unresolved": scan.unresolved,
        },
        "vulnerabilities": vulns,
        "licenses": licenses,
        "coverage": {
            "components": len(scan.components),
            "queried": vulns["queried"],
            "manifests": len(scan.manifests),
            "exact_pins": sum(1 for c in scan.components if c.resolved),
        },
        "unknowns": unknowns,
        "limitations": [
            "Only the repository's own manifests are read; installed environments and transitive "
            "graphs not present in a lockfile are out of scope.",
            "Advisory matches do not imply exploitability in any deployed environment.",
            "This is evidence, not a security certification or legal advice.",
        ],
    }


def _head_sha(root: Path) -> str | None:
    try:
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def run_adoption(repo: dict, *, cache_dir: str | Path | None = None,
                 db_path: str | Path | None = None, http=_http_json) -> dict:
    """Clone, inventory, query OSV, persist artifact, record the path. Raises CloneError."""
    root_dir = Path(cache_dir or settings.repo_cache_dir)
    dest = clone_repo(repo["url"], repo["name"], dest_root=root_dir)
    try:
        sha = _head_sha(dest)
        scan = collect_manifests(dest)
        vulns = query_osv(scan.components, http=http)
        licenses = collect_licenses(dest)
        report = build_report(repo, sha, scan, vulns, licenses)
    finally:
        cleanup(dest)

    artifact = root_dir / f"{sanitize_dir_name(repo['name'])}.adoption.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(report, indent=2), encoding="utf-8")

    conn = db.connect(db_path or settings.db_path)
    try:
        db.init_db(conn)
        db.set_adoption_path(conn, repo["id"], str(artifact))
        db.add_event(conn, repo["id"], "ADOPTION_DONE",
                     f"{repo['name']}: adoption report at {artifact.name}",
                     {"components": report["coverage"]["components"],
                      "findings": len(report["vulnerabilities"]["findings"])})
    finally:
        conn.close()
    return report


__all__ = [
    "CloneError", "Component", "ManifestScan", "build_report", "collect_licenses",
    "collect_manifests", "parse_lockfile", "parse_pyproject", "parse_requirement_lines",
    "query_osv", "run_adoption",
]
