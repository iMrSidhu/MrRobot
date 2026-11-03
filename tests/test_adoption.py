"""Adoption workflow: manifest parsing, OSV matching states, report shape.

Offline by design: OSV is a fake transport here. The live-pin check is the
opt-in smoke script, not this suite.
"""
from pathlib import Path

from workflows.adoption import (
    build_report,
    collect_licenses,
    collect_manifests,
    parse_lockfile,
    parse_pyproject,
    parse_requirement_lines,
    query_osv,
    Component,
)


def test_requirements_exact_pins_and_unresolved():
    text = """
# comment
requests==2.31.0
jinja2==3.1.2  # pinned
flask>=2.0
-e git+https://example.com/x#egg=x
-r other.txt
"""
    resolved, unresolved = parse_requirement_lines(text, "requirements.txt")
    assert [(c.name, c.version) for c in resolved] == [("requests", "2.31.0"), ("jinja2", "3.1.2")]
    assert all(c.resolved for c in resolved)
    assert [u["name"] for u in unresolved] == ["flask"]


def test_poetry_and_uv_lock_parse_packages():
    text = """
[[package]]
name = "flask"
version = "3.0.0"

[[package]]
name = "werkzeug"
version = "3.0.1"
"""
    components = parse_lockfile(text, "poetry.lock")
    assert [(c.name, c.version) for c in components] == [("flask", "3.0.0"), ("werkzeug", "3.0.1")]


def test_pyproject_pep621_poetry_and_optional_deps():
    text = """
[project]
dependencies = ["requests==2.31.0", "click>=8"]
[project.optional-dependencies]
dev = ["pytest==8.0.0"]
[tool.poetry.dependencies]
python = "^3.11"
toml = "0.10.2"
"""
    resolved, unresolved = parse_pyproject(text, "pyproject.toml")
    assert {c.name for c in resolved} == {"requests", "pytest", "toml"}
    assert {u["name"] for u in unresolved} == {"click"}
    assert all(u["name"] != "python" for u in unresolved)


def test_collect_manifests_dedupes_and_scans_nested_pyproject(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    nested = tmp_path / "pkg"
    nested.mkdir()
    (nested / "pyproject.toml").write_text(
        '[project]\ndependencies = ["jinja2==3.1.2"]\n', encoding="utf-8"
    )
    scan = collect_manifests(tmp_path)
    assert sorted(scan.manifests) == ["pkg/pyproject.toml", "requirements-dev.txt", "requirements.txt"]
    assert sorted(c.name for c in scan.components) == ["jinja2", "requests"]


def test_collect_manifests_reports_unsupported_inputs(tmp_path: Path):
    (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()\n", encoding="utf-8")
    scan = collect_manifests(tmp_path)
    assert scan.components == []
    assert any("setup.py" in entry for entry in scan.skipped)


def _fake_http(detail_severity="HIGH"):
    def http(url, payload, timeout=30):
        if url.endswith("/querybatch"):
            return {"results": [{"vulns": [{"id": "GHSA-aaaa-bbbb-cccc"}]},
                                {"vulns": []},
                                {"vulns": []}]}
        return {
            "id": "GHSA-aaaa-bbbb-cccc",
            "aliases": ["CVE-2024-0001"],
            "summary": "Example advisory",
            "database_specific": {"severity": detail_severity},
            "affected": [{"ranges": [{"type": "ECOSYSTEM",
                                      "events": [{"introduced": "0"}, {"fixed": "3.1.6"}]}]}],
        }
    return http


def test_query_osv_matches_exact_versions_and_keeps_evidence():
    components = [
        Component("jinja2", "3.1.2", source="requirements.txt", evidence="jinja2==3.1.2", resolved=True),
        Component("requests", "2.31.0", source="requirements.txt", evidence="requests==2.31.0", resolved=True),
        Component("flask", None, source="requirements.txt", evidence="flask>=2", resolved=False),
    ]
    result = query_osv(components, http=_fake_http("MODERATE"))
    assert result["state"] == "available"
    assert result["queried"] == 2  # unresolved pin never queried
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["package"] == "jinja2"
    assert finding["severity"] == "MEDIUM"  # GHSA MODERATE normalised
    assert finding["severity_raw"] == "MODERATE"
    assert finding["aliases"] == ["CVE-2024-0001"]
    assert finding["fixed_versions"] == ["3.1.6"]


def test_query_osv_failure_is_unavailable_not_zero():
    def boom(url, payload, timeout=30):
        raise OSError("network down")

    components = [Component("jinja2", "3.1.2", resolved=True)]
    result = query_osv(components, http=boom)
    assert result["state"] == "unavailable"
    assert result["findings"] == []
    assert "network down" in result["error"]


def test_query_osv_without_pins_is_unavailable():
    result = query_osv([Component("flask", None, resolved=False)])
    assert result["state"] == "unavailable"
    assert result["queried"] == 0


def test_collect_licenses_reads_files_and_declared_strings(tmp_path: Path):
    (tmp_path / "LICENSE").write_text("Apache License 2.0", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nlicense = "MIT"\n', encoding="utf-8"
    )
    licenses = collect_licenses(tmp_path)
    assert [f["file"] for f in licenses["files"]] == ["LICENSE"]
    assert licenses["declared"] == ["MIT"]
    assert licenses["state"] == "partial"  # no ScanCode on this host
    assert "unavailable" in licenses["tool"]


def test_build_report_states_unknowns_without_inventing_results():
    scan = collect_manifests(Path("."))  # no manifest in the repo root of a test run
    report = build_report(
        {"id": 1, "name": "owner/repo", "url": "https://example.com/repo.git"},
        None,
        scan,
        {"state": "unavailable", "findings": [], "queried": 0, "error": "no exact versions"},
        {"state": "partial", "tool": "scancode: unavailable", "files": [], "declared": [], "note": ""},
    )
    assert report["schema"] == "adoption/1"
    assert report["vulnerabilities"]["state"] == "unavailable"
    assert report["repo"]["sha"] is None
    assert len(report["unknowns"]) >= 3
    assert any("not a security certification" in line for line in report["limitations"])
