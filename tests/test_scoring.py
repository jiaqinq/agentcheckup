from __future__ import annotations

from agentcheckup.engine import lint_tools
from agentcheckup.models import Finding, Severity, Tool, score_findings
from agentcheckup.report import render_text


def tool(name: str, *, described_params: bool = True) -> Tool:
    prop = {"type": "string", "pattern": "^.*$"}
    if described_params:
        prop["description"] = "A path relative to the sandbox root."
    return Tool.from_raw(
        {
            "name": name,
            "description": (
                f"{name} reads one thing and returns it. Use this only for the "
                "documented case; prefer `other` otherwise. Returns a string."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"path": prop},
                "required": ["path"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        }
    )


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #


def test_info_findings_are_capped():
    """A rule that fires on nearly every tool is a preference, not a defect.

    The three official MCP servers produced 68 info findings across 18 tools.
    Charging one point each scored the reference implementations 0/100.
    """
    infos = [Finding(rule="AGT022", severity=Severity.INFO, message="x") for _ in range(68)]
    # 10 points of cap against a 360 point budget is a 3% deduction.
    assert score_findings(infos, tool_count=18) == 97


def test_info_cap_does_not_scale_with_count():
    few = [Finding(rule="AGT022", severity=Severity.INFO, message="x") for _ in range(11)]
    many = [Finding(rule="AGT022", severity=Severity.INFO, message="x") for _ in range(200)]
    assert score_findings(few, tool_count=10) == score_findings(many, tool_count=10)


def test_a_single_error_costs_half_a_one_tool_manifest():
    errors = [Finding(rule="AGT040", severity=Severity.ERROR, message="x")]
    assert score_findings(errors, tool_count=1) == 50


def test_the_same_error_hurts_less_in_a_big_manifest():
    errors = [Finding(rule="AGT040", severity=Severity.ERROR, message="x")]
    assert score_findings(errors, tool_count=10) == 95


def test_enough_errors_still_zero_the_score():
    errors = [Finding(rule="AGT040", severity=Severity.ERROR, message="x") for _ in range(20)]
    assert score_findings(errors, tool_count=10) == 0


def test_score_is_normalised_per_tool():
    """Two warnings in a two-tool manifest is the same density as ten in ten."""
    two = [Finding(rule="AGT013", severity=Severity.WARNING, message="x") for _ in range(2)]
    ten = [Finding(rule="AGT013", severity=Severity.WARNING, message="x") for _ in range(10)]
    assert score_findings(two, tool_count=2) == score_findings(ten, tool_count=10)


def test_score_never_goes_negative():
    many = [Finding(rule="AGT040", severity=Severity.ERROR, message="x") for _ in range(100)]
    assert score_findings(many, tool_count=1) == 0


def test_zero_tools_does_not_divide_by_zero():
    assert score_findings([], tool_count=0) == 100


# --------------------------------------------------------------------------- #
# report aggregation
# --------------------------------------------------------------------------- #


def test_repeated_rule_collapses_into_one_block():
    tools = [tool(f"git_op_{i}", described_params=False) for i in range(12)]
    report = lint_tools(tools)
    text = render_text(report)

    # 12 findings, but the rule is named once in the aggregated header.
    assert "(12 tools)" in text
    assert text.count("AGT013") == 1
    assert "+8 more" in text


def test_a_few_findings_stay_individual():
    tools = [tool(f"git_op_{i}", described_params=False) for i in range(3)]
    text = render_text(lint_tools(tools))
    # Below the aggregation threshold each tool gets its own line.
    assert text.count("AGT013") == 3


def test_info_findings_are_summarised_not_listed():
    tools = [tool(f"op_{i}") for i in range(6)]
    report = lint_tools(tools)
    text = render_text(report)
    if report.counts()["info"]:
        assert "NUDGES" in text
        assert "no score impact" in text


def test_clean_manifest_says_ship_it():
    report = lint_tools([tool("read_file")])
    assert report.findings == []
    assert "Ship it" in render_text(report)
