"""Guards on the rule registry itself.

Rule ids are the public API of this tool: people put them in suppression lists,
CI thresholds and issue reports. A duplicate id silently gives two unrelated
checks the same name, which is worse than either check being wrong.

This file exists because that happened: `AGT105` was used for both "server did
not return a tool list" (suite) and "remote server uses plain HTTP" (config).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentcheckup.rules import CONFIG_RULES, SUITE_RULES, TOOL_RULES

SRC = Path(__file__).resolve().parents[1] / "src" / "agentcheckup"

ALL_RULES = [*TOOL_RULES, *SUITE_RULES, *CONFIG_RULES]


def test_rule_ids_are_unique():
    ids = [rule.id for rule in ALL_RULES]
    duplicates = {rule_id for rule_id in ids if ids.count(rule_id) > 1}
    assert not duplicates, f"duplicate rule ids: {sorted(duplicates)}"


def test_rule_ids_are_well_formed():
    for rule in ALL_RULES:
        assert re.fullmatch(r"AGT\d{3}", rule.id), rule.id


def test_every_rule_has_a_title():
    for rule in ALL_RULES:
        assert rule.title.strip(), f"{rule.id} has no title"


def test_no_rule_is_registered_twice_across_groups():
    """A tool rule and a config rule must not share an id either."""
    groups = {
        "tool": {r.id for r in TOOL_RULES},
        "suite": {r.id for r in SUITE_RULES},
        "config": {r.id for r in CONFIG_RULES},
    }
    for a, left in groups.items():
        for b, right in groups.items():
            if a >= b:
                continue
            overlap = left & right
            assert not overlap, f"{a} and {b} share {sorted(overlap)}"


@pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: r.id)
def test_emitted_severity_matches_the_registry(rule):
    """Catch a rule whose Finding says WARNING while the registry says INFO.

    Without this, a severity change in one place silently disagrees with the
    other, and the report and the score stop matching the docs.
    """
    pattern = re.compile(
        r'rule="' + re.escape(rule.id) + r'",\s*severity=Severity\.(\w+)'
    )
    emitted: set[str] = set()
    for path in SRC.rglob("*.py"):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            emitted.add(match.group(1))

    if not emitted:
        pytest.skip("severity is passed indirectly for this rule")

    expected = rule.severity.name
    assert emitted == {expected}, (
        f"{rule.id} is registered as {expected} but emits {sorted(emitted)}"
    )


# --------------------------------------------------------------------------- #
# Conflict rules pass their severity into a helper rather than writing it as a
# literal, so the parametrised test above skips them. Check them by behaviour.
# --------------------------------------------------------------------------- #


def _conflict_ref(server: str, name: str, description: str):
    from agentcheckup.conflicts import ToolRef
    from agentcheckup.models import Tool

    tool = Tool.from_raw(
        {
            "name": name,
            "description": description,
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        }
    )
    return ToolRef(server=server, tool=tool)


def test_conflict_rules_emit_their_registered_severity():
    from agentcheckup.conflicts import detect_conflicts

    registry = {rule.id: rule.severity for rule in SUITE_RULES}

    cases = {
        "AGT201": (
            _conflict_ref("a", "read_file", "Read a file and return its contents."),
            _conflict_ref("b", "read_file", "Read a file from a revision."),
        ),
        "AGT202": (
            _conflict_ref("a", "readFiles", "Read a file and return its contents."),
            _conflict_ref("b", "read_files", "Read a file from a revision."),
        ),
        "AGT203": (
            _conflict_ref(
                "a",
                "search_public",
                "Search public repositories by keyword and return matching repository names.",
            ),
            _conflict_ref(
                "b",
                "search_private",
                "Search private repositories by keyword and return matching repository names.",
            ),
        ),
    }

    for rule_id, (a, b) in cases.items():
        found = [c for c in detect_conflicts([a, b]) if c.rule == rule_id]
        assert found, f"{rule_id} did not fire for its own case"
        assert found[0].severity is registry[rule_id], (
            f"{rule_id} emits {found[0].severity.name} but is registered as "
            f"{registry[rule_id].name}"
        )
