"""Run rules over a manifest and produce a report object."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import rules as _rules  # noqa: F401 - side effect: registers rules
from .conflicts import ToolRef, lint_conflicts
from .discovery import SCOPE_PRECEDENCE
from .models import Finding, ServerConfig, Severity, Tool, grade_for, score_findings
from .tokens import manifest_tokens


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    tool_count: int = 0
    tokens: int = 0
    source: str = ""
    kind: str = "tools"
    server_count: int = 0
    #: How much of the manifest was actually observed. A server whose tools were
    #: never listed is *unverified*, not clean, and the two must not look alike.
    servers_inspected: int = 0
    servers_unverified: int = 0
    #: Servers that answered but whose tool list was cut short (page or tool cap,
    #: or a mid-listing failure). Their tools were seen, but not all of them.
    servers_partial: int = 0
    #: Findings withheld because a baseline already recorded them.
    suppressed: int = 0

    @property
    def coverage(self) -> float:
        """Share of configured servers whose tool list was actually read."""
        if not self.server_count:
            return 1.0
        return self.servers_inspected / self.server_count

    @property
    def score(self) -> int:
        return score_findings(self.findings, tool_count=self.tool_count)

    @property
    def grade(self) -> str:
        return grade_for(self.score)

    def counts(self) -> dict[str, int]:
        counter = Counter(f.severity.value for f in self.findings)
        return {s.value: counter.get(s.value, 0) for s in Severity}

    def sorted_findings(self) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (-f.severity.rank, f.rule, f.tool or "", f.message),
        )

    def conflicts(self) -> list[Finding]:
        """Cross-server findings, reported in their own section."""
        return [f for f in self.sorted_findings() if f.rule.startswith("AGT2")]

    def risks(self) -> list[Finding]:
        return [f for f in self.sorted_findings() if not f.rule.startswith("AGT2")]

    def worst(self) -> Severity | None:
        if not self.findings:
            return None
        return max((f.severity for f in self.findings), key=lambda s: s.rank)

    def exceeding(self, threshold: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity.rank >= threshold.rank]


def _tool_findings(tools: list[Tool]) -> list[Finding]:
    findings: list[Finding] = []

    # Suite-level: duplicate names make selection non-deterministic.
    seen: dict[str, int] = {}
    for tool in tools:
        seen[tool.name] = seen.get(tool.name, 0) + 1
    for name, count in seen.items():
        if name and count > 1:
            findings.append(
                Finding(
                    rule="AGT004",
                    severity=Severity.ERROR,
                    message=f"Tool name {name!r} appears {count} times.",
                    tool=name,
                    hint="Names must be unique; clients keep only one of them.",
                )
            )

    for tool in tools:
        for rule in _rules.TOOL_RULES:
            findings.extend(rule.check(tool))

    return findings


def _server_findings(servers: list[ServerConfig]) -> list[Finding]:
    findings: list[Finding] = []
    for server in servers:
        for rule in _rules.CONFIG_RULES:
            findings.extend(rule.check(server))
    return findings


def lint_tools(tools: list[Tool], source: str = "") -> Report:
    return Report(
        findings=_tool_findings(tools),
        tool_count=len(tools),
        tokens=manifest_tokens(tools),
        source=source,
    )


def lint_servers(servers: list[ServerConfig], source: str = "") -> Report:
    return Report(
        findings=_server_findings(servers),
        tool_count=len(servers),
        tokens=0,
        source=source,
        kind="config",
    )


def _scope_findings(
    servers: list[ServerConfig],
    shadowed: list[tuple[ServerConfig, ServerConfig]],
) -> list[Finding]:
    """Report same-name servers that live at two scopes of one client.

    Two cases, and they are different:

    - **Resolved.** The client documents its precedence (Claude Code), so
      ``resolve_scopes`` already dropped the loser. The note explains why that
      server's tools are missing from the manifest.
    - **Unresolved.** The client reads both files but documents no rule for a
      duplicate name (Cursor, VS Code). One probably wins; saying which would be
      a guess, so this is a note rather than an error — and it is emitted from
      the config alone, so it still appears under ``--no-spawn``.

    Either way it is information: the config is doing what the client tells it to.
    """
    out: list[Finding] = []

    for loser, winner in shadowed:
        out.append(
            Finding(
                rule="AGT205",
                severity=Severity.INFO,
                message=(
                    f"Server {loser.name!r} at {loser.scope} scope is shadowed by the "
                    f"{winner.scope}-scope definition in {winner.client}: only one is "
                    f"loaded, so its tools are not part of this manifest."
                ),
                tool=loser.name,
                hint=(
                    "Not a problem — it is how the client resolves a duplicate name. "
                    "Remove the unused entry if it is stale."
                ),
            )
        )

    groups: dict[tuple[str, str], list[ServerConfig]] = {}
    for server in servers:
        groups.setdefault((server.client, server.name), []).append(server)

    for (client, name), group in groups.items():
        if len(group) < 2 or client in SCOPE_PRECEDENCE:
            continue
        scopes = sorted({server.scope for server in group if server.scope})
        if len(scopes) < 2:
            continue
        out.append(
            Finding(
                rule="AGT205",
                severity=Severity.INFO,
                message=(
                    f"Server {name!r} is defined at {', '.join(scopes)} scope in "
                    f"{client}. One of them is probably the one that loads, but "
                    f"{client} documents no rule for a duplicate name."
                ),
                tool=name,
                hint=(
                    "Check the client's own server list. If both load, this is a hard "
                    "collision; otherwise delete the entry you do not use."
                ),
            )
        )

    return out


def _scope_findings(
    servers: list[ServerConfig],
    shadowed: list[tuple[ServerConfig, ServerConfig]],
) -> list[Finding]:
    """Report same-name servers that live at two scopes of one client.

    Two cases, and they are different:

    - **Resolved.** The client documents its precedence (Claude Code), so
      ``resolve_scopes`` already dropped the loser. The note explains why that
      server's tools are missing from the manifest.
    - **Unresolved.** The client reads both files but documents no rule for a
      duplicate name (Cursor, VS Code). One probably wins; saying which would be
      a guess, so this is a note rather than an error — and it is emitted from
      the config alone, so it still appears under ``--no-spawn``.

    Either way it is information: the config is doing what the client tells it to.
    """
    out: list[Finding] = []

    for loser, winner in shadowed:
        out.append(
            Finding(
                rule="AGT205",
                severity=Severity.INFO,
                message=(
                    f"Server {loser.name!r} at {loser.scope} scope is shadowed by the "
                    f"{winner.scope}-scope definition in {winner.client}: only one is "
                    f"loaded, so its tools are not part of this manifest."
                ),
                tool=loser.name,
                hint=(
                    "Not a problem — it is how the client resolves a duplicate name. "
                    "Remove the unused entry if it is stale."
                ),
            )
        )

    groups: dict[tuple[str, str], list[ServerConfig]] = {}
    for server in servers:
        groups.setdefault((server.client, server.name), []).append(server)

    for (client, name), group in groups.items():
        if len(group) < 2 or client in SCOPE_PRECEDENCE:
            continue
        scopes = sorted({server.scope for server in group if server.scope})
        if len(scopes) < 2:
            continue
        out.append(
            Finding(
                rule="AGT205",
                severity=Severity.INFO,
                message=(
                    f"Server {name!r} is defined at {', '.join(scopes)} scope in "
                    f"{client}. One of them is probably the one that loads, but "
                    f"{client} documents no rule for a duplicate name."
                ),
                tool=name,
                hint=(
                    "Check the client's own server list. If both load, this is a hard "
                    "collision; otherwise delete the entry you do not use."
                ),
            )
        )

    return out


def lint_audit(
    servers: list[ServerConfig],
    tools_by_server: dict[str, list[Tool]],
    failures: dict[str, str] | None = None,
    source: str = "",
    partial: dict[str, str] | None = None,
    shadowed: list[tuple[ServerConfig, ServerConfig]] | None = None,
) -> Report:
    """The full check: config risk + per-server tool quality + cross-server conflicts."""
    failures = failures or {}
    partial = partial or {}
    shadowed = shadowed or []
    findings = _server_findings(servers)
    findings.extend(_scope_findings(servers, shadowed))

    client_of = {server.key: server.client for server in servers}
    scope_of = {server.key: server.scope for server in servers}
    name_of = {server.key: server.name for server in servers}

    refs: list[ToolRef] = []
    for server_name, tools in tools_by_server.items():
        findings.extend(_tool_findings(tools))
        refs.extend(
            ToolRef(
                server=server_name,
                tool=tool,
                client=client_of.get(server_name, ""),
                scope=scope_of.get(server_name, ""),
                server_name=name_of.get(server_name, ""),
            )
            for tool in tools
        )

    findings.extend(lint_conflicts(refs))

    for server_name, reason in sorted(partial.items()):
        findings.append(
            Finding(
                rule="AGT105",
                severity=Severity.INFO,
                message=f"Server {server_name!r} returned a partial tool list: {reason}",
                tool=server_name,
                hint="Collisions involving the missing tools were not checked.",
            )
        )

    for server_name, reason in sorted(failures.items()):
        findings.append(
            Finding(
                rule="AGT105",
                severity=Severity.INFO,
                message=f"Server {server_name!r} did not return a tool list: {reason}",
                tool=server_name,
                hint="Check that the command runs standalone; unreachable servers are unaudited.",
            )
        )

    all_tools = [tool for tools in tools_by_server.values() for tool in tools]
    inspected = sum(1 for server in servers if server.key in tools_by_server)
    partial_count = sum(1 for server in servers if server.key in partial)
    return Report(
        findings=findings,
        tool_count=len(all_tools),
        tokens=manifest_tokens(all_tools),
        source=source,
        kind="audit",
        server_count=len(servers),
        servers_inspected=inspected,
        servers_unverified=len(servers) - inspected,
        servers_partial=partial_count,
    )
