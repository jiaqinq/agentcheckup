"""SARIF has to be usable by the consumer it is written for.

The point of `--format sarif` is GitHub code scanning. That means
`artifactLocation.uri` must be a URI reference, and the schema types it as one:
forward slashes, no drive letter. A Windows path passed straight through is not
a URI reference, so the upload cannot map a result to a file — the one thing the
format exists to do.
"""

from __future__ import annotations

import json

from agentcheckup.engine import Report
from agentcheckup.models import Finding, Severity
from agentcheckup.report import render_sarif


def report_for(source: str) -> Report:
    return Report(
        findings=[
            Finding(
                rule="AGT201",
                severity=Severity.ERROR,
                message="Tool name 'read_file' is exposed by two servers.",
                hint="Rename one.",
            )
        ],
        source=source,
    )


def uri_of(source: str) -> str:
    payload = json.loads(render_sarif(report_for(source)))
    return payload["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
        "artifactLocation"
    ]["uri"]


def test_windows_paths_become_forward_slashes():
    assert uri_of("tests\\fixtures\\bad_tools.json") == "tests/fixtures/bad_tools.json"


def test_relative_path_is_preserved():
    assert uri_of("tests/fixtures/bad_tools.json") == "tests/fixtures/bad_tools.json"


def test_absolute_path_inside_the_tree_is_relativised(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "cfg" / "mcp.json"
    target.parent.mkdir()
    target.write_text("{}", encoding="utf-8")

    assert uri_of(str(target)) == "cfg/mcp.json"


def test_absolute_path_outside_the_tree_keeps_only_its_name(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = elsewhere / "mcp.json"
    target.write_text("{}", encoding="utf-8")
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    assert uri_of(str(target)) == "mcp.json"


def test_audit_source_is_not_a_path():
    """`audit` reports "3 config(s)", which is a description, not a file."""
    assert uri_of("3 config(s)") == "mcp-tools.json"


def test_cmd_source_is_not_a_path():
    assert uri_of("cmd: npx -y some-server") == "mcp-tools.json"


def test_empty_source_falls_back():
    assert uri_of("") == "mcp-tools.json"


def test_no_uri_contains_a_backslash():
    for source in (
        "tests\\fixtures\\bad_tools.json",
        "C:\\Users\\someone\\AppData\\Roaming\\Claude\\claude_desktop_config.json",
        "cmd: npx -y server",
        "2 config(s)",
    ):
        assert "\\" not in uri_of(source)


def test_result_carries_no_empty_fixes_array():
    """A fix must name edits to a file; this tool never edits one."""
    payload = json.loads(render_sarif(report_for("a.json")))
    result = payload["runs"][0]["results"][0]
    assert "fixes" not in result
    assert result["properties"]["hint"] == "Rename one."


def test_document_keeps_its_required_top_level_shape():
    payload = json.loads(render_sarif(report_for("a.json")))
    assert payload["version"] == "2.1.0"
    assert payload["runs"][0]["tool"]["driver"]["name"] == "agentcheckup"
    assert payload["runs"][0]["results"][0]["level"] == "error"
