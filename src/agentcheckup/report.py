"""Render a Report as text, JSON, or SARIF."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from . import rules as _rules
from .engine import Report
from .models import Finding, Severity

__version__ = "0.10.0"

SARIF_LEVEL = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "note",
}

INVISIBLE = frozenset("\u200b\u200c\u200d\u2060\ufeff")


def display(text: str) -> str:
    """Make invisible characters visible in terminal output.

    A finding about hidden text is useless if the report itself renders it
    invisibly - the reviewer would see an empty-looking name and move on.
    """
    out: list[str] = []
    for ch in text:
        if ch in INVISIBLE or unicodedata.category(ch) == "Cf":
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def _rule_metadata() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rule in [*_rules.TOOL_RULES, *_rules.SUITE_RULES, *_rules.CONFIG_RULES]:
        out.append(
            {
                "id": rule.id,
                "name": rule.id,
                "shortDescription": {"text": rule.title},
                "defaultConfiguration": {"level": SARIF_LEVEL[rule.severity]},
            }
        )
    return sorted(out, key=lambda r: r["id"])


def _finding_lines(findings: list[Finding], verbose: bool) -> list[str]:
    out: list[str] = []
    for finding in findings:
        target = f"  [{display(finding.tool)}]" if finding.tool else ""
        out.append(f"    {finding.rule}  {finding.message}{target}")
        if finding.hint:
            out.append(f"            fix: {finding.hint}")
        if verbose and finding.where:
            out.append(f"            at:  {finding.where}")
    return out


def rule_title(rule_id: str) -> str:
    for rule in [*_rules.TOOL_RULES, *_rules.SUITE_RULES, *_rules.CONFIG_RULES]:
        if rule.id == rule_id:
            return rule.title
    return ""


def _nudge_lines(findings: list[Finding]) -> list[str]:
    """Collapse info findings into one line per rule.

    Measured on the three official MCP servers: 68 info findings across 18 tools,
    most from rules that fire on nearly every tool. Printed individually they
    bury the two findings that matter, and a report nobody reads is a report
    nobody acts on.
    """
    by_rule: dict[str, list[Finding]] = {}
    for finding in findings:
        by_rule.setdefault(finding.rule, []).append(finding)

    out: list[str] = []
    for rule, group in sorted(by_rule.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        title = rule_title(rule) or group[0].message
        out.append(f"    {rule}  {title}  ({len(group)})")
        names = [display(f.tool) for f in group if f.tool]
        if names:
            preview = ", ".join(names[:3])
            if len(names) > 3:
                preview += f", +{len(names) - 3} more"
            out.append(f"            {preview}")
    return out


#: A rule that fires on this many tools is one root cause, not N problems.
AGGREGATE_AT = 5


def _serious_lines(findings: list[Finding], verbose: bool) -> list[str]:
    """Individual findings, except for rules that repeat: those collapse.

    The official git server produced 12 identical "parameter has no description"
    warnings, one per tool. Twelve near-identical lines hide everything else,
    while one line naming all twelve tools is both shorter and more actionable.
    """
    by_rule: dict[str, list[Finding]] = {}
    for finding in findings:
        by_rule.setdefault(finding.rule, []).append(finding)

    ordered = sorted(
        by_rule.items(),
        key=lambda kv: (-kv[1][0].severity.rank, -len(kv[1]), kv[0]),
    )

    out: list[str] = []
    for rule, group in ordered:
        if len(group) < AGGREGATE_AT:
            out.extend(_finding_lines(group, verbose))
            continue

        title = rule_title(rule) or group[0].message
        out.append(f"    {rule}  {title}  ({len(group)} tools)")
        names = [display(f.tool) for f in group if f.tool]
        if names:
            preview = ", ".join(names[:4])
            if len(names) > 4:
                preview += f", +{len(names) - 4} more"
            out.append(f"            {preview}")
        hint = next((f.hint for f in group if f.hint), "")
        if hint:
            out.append(f"            fix: {hint}")
    return out


def render_text(report: Report, verbose: bool = False) -> str:
    lines: list[str] = []
    if report.kind == "audit":
        lines.append(
            f"agentcheckup {__version__}  |  {report.server_count} server(s)  |  "
            f"{report.tool_count} tool(s)  |  ~{report.tokens:,} tokens per request"
        )
    elif report.kind == "config":
        lines.append(f"agentcheckup {__version__}  |  {report.tool_count} server(s)")
    else:
        lines.append(
            f"agentcheckup {__version__}  |  {report.tool_count} tool(s)  |  "
            f"~{report.tokens:,} tokens per request"
        )
    if report.source:
        lines.append(f"source: {report.source}")

    if report.suppressed:
        lines.append(f"baseline: {report.suppressed} known finding(s) withheld")

    if report.kind == "audit" and report.server_count:
        detail = f"{report.servers_unverified} unverified"
        if report.servers_partial:
            detail = f"{report.servers_partial} partial, {detail}"
        lines.append(
            f"coverage: {report.servers_inspected}/{report.server_count} server(s) "
            f"inspected ({report.coverage:.0%}), {detail}"
        )

    counts = report.counts()
    summary = "  ".join(f"{counts[s.value]} {s.value}" for s in Severity if counts[s.value])
    lines.append("")
    lines.append(
        f"  Grade {report.grade:<2}   Score {report.score:>3}/100   "
        f"{summary if summary else 'clean'}"
    )
    lines.append("")

    if not report.findings:
        lines.append("  No findings. Ship it.")
        return "\n".join(lines)

    ordered = report.sorted_findings()
    serious = [f for f in ordered if f.severity is not Severity.INFO]
    nudges = [f for f in ordered if f.severity is Severity.INFO]

    if report.kind == "audit":
        # Two sections, because they answer different questions: "will my agent
        # pick the wrong tool?" and "is my setup unsafe?".
        conflicts = [f for f in serious if f.rule.startswith("AGT2")]
        risks = [f for f in serious if not f.rule.startswith("AGT2")]
        if conflicts:
            lines.append(f"  CONFLICTS ({len(conflicts)})")
            lines.extend(_finding_lines(conflicts, verbose))
            lines.append("")
        if risks:
            lines.append(f"  RISKS ({len(risks)})")
            lines.extend(_serious_lines(risks, verbose))
    else:
        for severity in (Severity.ERROR, Severity.WARNING):
            group = [f for f in serious if f.severity is severity]
            if not group:
                continue
            lines.append(f"  {severity.value.upper()}")
            lines.extend(_serious_lines(group, verbose))

    if nudges:
        rules = len({f.rule for f in nudges})
        lines.append("")
        lines.append(f"  NUDGES ({len(nudges)} across {rules} rule(s), no score impact)")
        lines.extend(_nudge_lines(nudges))

    lines.append("")
    lines.append("  Rule docs: https://github.com/jiaqinq/agentcheckup#rules")
    return "\n".join(lines)


def render_json(report: Report) -> str:
    payload = {
        "version": __version__,
        "source": report.source,
        "server_count": report.server_count,
        "tool_count": report.tool_count,
        "servers_inspected": report.servers_inspected,
        "servers_unverified": report.servers_unverified,
        "servers_partial": report.servers_partial,
        "suppressed": report.suppressed,
        "coverage": round(report.coverage, 3),
        "estimated_tokens": report.tokens,
        "score": report.score,
        "grade": report.grade,
        "counts": report.counts(),
        "findings": [f.as_dict() for f in report.sorted_findings()],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


#: Placeholder artifact for reports that did not come from one file.
SARIF_FALLBACK_URI = "mcp-tools.json"


def _sarif_uri(source: str) -> str:
    """Turn a report source into a URI reference a SARIF consumer can resolve.

    The schema types ``artifactLocation.uri`` as ``uri-reference``, and a Windows
    path is not one: backslashes are not path separators in a URI, and a drive
    letter reads as a scheme. GitHub code scanning then cannot map the result to
    a file, which is the whole point of uploading SARIF.

    Absolute paths outside the working tree keep only their file name — a path
    the consumer cannot see is worse than a short one it can.
    """
    text = (source or "").strip()
    if not text or text.startswith("cmd:") or text.endswith("config(s)"):
        return SARIF_FALLBACK_URI

    # A backslash is not a URI path separator on any platform, so normalise it
    # before asking Path what this is. On POSIX a backslash is an ordinary
    # filename character, which is exactly why this cannot be left to Path.
    text = text.replace("\\", "/")

    try:
        path = Path(text)
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(Path.cwd().resolve())
            except ValueError:
                path = Path(path.name)
        elif len(text) > 2 and text[1] == ":" and text[0].isalpha():
            # A Windows path on a POSIX host: Path will not call it absolute,
            # and the drive letter would read as a URI scheme.
            path = Path(text.rsplit("/", 1)[-1])
    except (OSError, ValueError):
        return SARIF_FALLBACK_URI
    return path.as_posix()


def render_sarif(report: Report) -> str:
    """SARIF 2.1.0 so findings show up in GitHub code scanning for free."""
    uri = _sarif_uri(report.source)
    results: list[dict[str, Any]] = []
    for finding in report.sorted_findings():
        result: dict[str, Any] = {
            "ruleId": finding.rule,
            "level": SARIF_LEVEL[finding.severity],
            "message": {"text": finding.message + (f" ({finding.tool})" if finding.tool else "")},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": uri},
                        "region": {"startLine": 1, "startColumn": 1},
                    }
                }
            ],
        }
        if finding.hint:
            # No `fixes`: a fix must name edits to a file, and this tool never
            # edits one. An empty array is schema-legal and says nothing.
            result["properties"] = {"hint": finding.hint}
        results.append(result)

    payload = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "agentcheckup",
                        "version": __version__,
                        "informationUri": "https://github.com/jiaqinq/agentcheckup",
                        "rules": _rule_metadata(),
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def render_rule_list() -> str:
    lines = ["Tool rules", "----------"]
    for rule in sorted(_rules.TOOL_RULES, key=lambda r: r.id):
        lines.append(f"  {rule.id}  {rule.severity.value:<7}  {rule.title}")
    lines.append("")
    lines.append("Suite rules (need the whole manifest)")
    lines.append("------------------------------------")
    for rule in sorted(_rules.SUITE_RULES, key=lambda r: r.id):
        lines.append(f"  {rule.id}  {rule.severity.value:<7}  {rule.title}")
    lines.append("")
    lines.append("Config rules")
    lines.append("------------")
    for rule in sorted(_rules.CONFIG_RULES, key=lambda r: r.id):
        lines.append(f"  {rule.id}  {rule.severity.value:<7}  {rule.title}")
    return "\n".join(lines)
