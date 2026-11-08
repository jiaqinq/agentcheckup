"""A baseline lets an existing project adopt the tool without a wall of red.

The first run on a real repo finds things that were there before you arrived.
Failing CI on all of them means nobody turns it on. `--baseline` records today's
findings and fails only on what appears afterwards.

The fingerprint is deliberately built from `rule`, `tool`, `where` and the
message — not from severity or position. A severity bump should not orphan a
baseline entry, and a finding that moves should still be recognisable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentcheckup.cli import main
from agentcheckup.models import Finding, Severity


def write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def bad_manifest(tmp_path: Path) -> Path:
    """Two tools that collide across servers, plus one bad name."""
    tools = [
        {
            "name": "read file",
            "description": "Read a file.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
        },
        {
            "name": "read_file",
            "description": "Read a file from git.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
        },
    ]
    return write_json(tmp_path / "tools.json", {"tools": tools})


# --------------------------------------------------------------------------- #
# Fingerprints
# --------------------------------------------------------------------------- #


def test_fingerprint_is_stable_for_the_same_finding():
    a = Finding(rule="AGT001", severity=Severity.WARNING, message="m", tool="t")
    b = Finding(rule="AGT001", severity=Severity.WARNING, message="m", tool="t")
    assert a.fingerprint == b.fingerprint


def test_fingerprint_ignores_severity():
    """A severity change must not orphan a baseline entry."""
    a = Finding(rule="AGT001", severity=Severity.WARNING, message="m", tool="t")
    b = Finding(rule="AGT001", severity=Severity.ERROR, message="m", tool="t")
    assert a.fingerprint == b.fingerprint


def test_fingerprint_separates_different_tools():
    a = Finding(rule="AGT001", severity=Severity.WARNING, message="m", tool="one")
    b = Finding(rule="AGT001", severity=Severity.WARNING, message="m", tool="two")
    assert a.fingerprint != b.fingerprint


# --------------------------------------------------------------------------- #
# Round trip
# --------------------------------------------------------------------------- #


def test_write_baseline_then_audit_clean(tmp_path, capsys):
    manifest = bad_manifest(tmp_path)
    baseline = tmp_path / "baseline.json"

    # --fail-on warning: AGT001 is a warning since 0.5.0, so the default
    # --fail-on error would exit 0 and the assertion would prove nothing.
    assert main(
        ["scan", str(manifest), "--write-baseline", str(baseline), "--fail-on", "warning"]
    ) == 1
    assert baseline.exists()
    capsys.readouterr()

    code = main(["scan", str(manifest), "--baseline", str(baseline), "--fail-on", "warning"])
    out = capsys.readouterr().out
    assert code == 0, "a baselined project must not fail CI"
    assert "known" in out.lower()


def test_a_new_finding_still_fails(tmp_path, capsys):
    manifest = bad_manifest(tmp_path)
    baseline = tmp_path / "baseline.json"
    main(["scan", str(manifest), "--write-baseline", str(baseline)])
    capsys.readouterr()

    # Add a tool that the baseline has never seen.
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["tools"].append(
        {
            "name": "another bad name",
            "description": "Do something.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
        }
    )
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    assert main(
        ["scan", str(manifest), "--baseline", str(baseline), "--fail-on", "warning"]
    ) == 1


def test_baseline_file_lists_findings_for_review(tmp_path):
    manifest = bad_manifest(tmp_path)
    baseline = tmp_path / "baseline.json"
    main(["scan", str(manifest), "--write-baseline", str(baseline)])

    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["findings"], "an empty baseline would suppress everything forever"
    assert all("fingerprint" in f and "rule" in f for f in payload["findings"])


def test_missing_baseline_is_a_usage_error(tmp_path, capsys):
    manifest = bad_manifest(tmp_path)
    code = main(["scan", str(manifest), "--baseline", str(tmp_path / "nope.json")])
    err = capsys.readouterr().err
    assert code == 2
    assert "baseline" in err.lower()


def test_corrupt_baseline_is_a_usage_error(tmp_path, capsys):
    manifest = bad_manifest(tmp_path)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    code = main(["scan", str(manifest), "--baseline", str(broken)])
    assert code == 2
    assert "baseline" in capsys.readouterr().err.lower()


def test_json_reports_suppressed_count(tmp_path, capsys):
    manifest = bad_manifest(tmp_path)
    baseline = tmp_path / "baseline.json"
    main(["scan", str(manifest), "--write-baseline", str(baseline)])
    capsys.readouterr()

    main(["scan", str(manifest), "--baseline", str(baseline), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["suppressed"] > 0


@pytest.mark.parametrize("severity", ["error", "warning", "info"])
def test_baseline_works_at_every_threshold(tmp_path, capsys, severity):
    manifest = bad_manifest(tmp_path)
    baseline = tmp_path / "baseline.json"
    main(["scan", str(manifest), "--write-baseline", str(baseline)])
    capsys.readouterr()

    assert main(["scan", str(manifest), "--baseline", str(baseline), "--fail-on", severity]) == 0
