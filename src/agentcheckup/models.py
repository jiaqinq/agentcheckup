"""Core data model for agentcheckup.

Everything here is deliberately dependency-free so the package keeps working
across MCP spec revisions without chasing an SDK release.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"error": 3, "warning": 2, "info": 1}[self.value]


@dataclass(frozen=True)
class Finding:
    """A single lint result.

    ``rule`` is a stable id (AGT0xx) so CI configs and suppressions never break
    when wording changes.
    """

    rule: str
    severity: Severity
    message: str
    tool: str | None = None
    hint: str | None = None
    where: str | None = None

    @property
    def fingerprint(self) -> str:
        """Stable identity for baselines.

        Built from rule, tool, where and message. Severity is excluded on
        purpose: escalating a rule must not orphan every baseline entry, and the
        point of a baseline is "this existed before", not "this looked the same".
        """
        material = "|".join(
            [self.rule, self.tool or "", self.where or "", self.message]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.tool:
            out["tool"] = self.tool
        if self.hint:
            out["hint"] = self.hint
        if self.where:
            out["where"] = self.where
        return out


@dataclass
class Tool:
    """One entry from ``tools/list``."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> Tool:
        schema = data.get("inputSchema") or data.get("input_schema") or {}
        if not isinstance(schema, dict):
            schema = {}
        annotations = data.get("annotations") or {}
        if not isinstance(annotations, dict):
            annotations = {}
        description = data.get("description") or ""
        if not isinstance(description, str):
            description = str(description)
        return cls(
            name=str(data.get("name", "")),
            description=description,
            input_schema=schema,
            annotations=annotations,
            raw=data,
        )

    def properties(self) -> dict[str, Any]:
        props = self.input_schema.get("properties")
        return props if isinstance(props, dict) else {}

    def required(self) -> list[str]:
        req = self.input_schema.get("required")
        if not isinstance(req, list):
            return []
        return [str(x) for x in req]


@dataclass
class ServerConfig:
    """A server entry lifted from an MCP client config file."""

    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    source: str | None = None
    #: Unique key for this *instance*. Two configs can both declare a server
    #: called `filesystem`; they are different instances and must not share a
    #: slot in `tools_by_server`, or one silently overwrites the other.
    instance: str | None = None
    #: Which client this server was declared in (Cursor, Codex CLI, ...). Two
    #: clients never load each other's config, so a name clash between them is
    #: not a runtime collision.
    client: str = ""
    #: Where within that client: ``user``, ``project``, ``local`` or ``explicit``.
    #: Scope is not the same thing as client — Claude Code's project ``.mcp.json``
    #: is still Claude Code, and it shadows the user-level entry of the same name
    #: rather than colliding with it.
    scope: str = ""
    #: Codex's ``env_vars``: names to inherit from the parent environment. The
    #: values are never stored or printed here — only the names, which are not
    #: secrets by themselves.
    env_passthrough: list[str] = field(default_factory=list)
    #: Codex's ``startup_timeout_sec``. Used as this server's deadline when the
    #: caller did not pass an explicit --timeout.
    startup_timeout: float | None = None

    @property
    def key(self) -> str:
        return self.instance or self.name

    @classmethod
    def from_raw(
        cls,
        name: str,
        data: dict[str, Any],
        source: str | None = None,
        client: str = "",
        scope: str = "",
    ) -> ServerConfig:
        args = data.get("args") or []
        if not isinstance(args, list):
            args = [str(args)]
        env = data.get("env") or {}
        if not isinstance(env, dict):
            env = {}
        env_vars = data.get("env_vars") or []
        if not isinstance(env_vars, list):
            env_vars = []
        startup = data.get("startup_timeout_sec")
        if not isinstance(startup, (int, float)) or startup <= 0:
            startup = None
        return cls(
            name=name,
            command=data.get("command"),
            args=[str(a) for a in args],
            env={str(k): str(v) for k, v in env.items()},
            url=data.get("url") or data.get("serverUrl"),
            source=source,
            client=client,
            scope=scope,
            env_passthrough=[str(name) for name in env_vars if str(name).strip()],
            startup_timeout=float(startup) if startup else None,
        )


def grade_for(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


#: Points charged against a manifest's budget.
#:
#: ``info`` is capped rather than free: a rule that fires on 18 of 18 tools in
#: the official MCP servers is expressing a preference, but a report full of
#: nudges should not still earn an A either.
SEVERITY_WEIGHT = {Severity.ERROR: 10, Severity.WARNING: 3, Severity.INFO: 1}

#: Info findings can cost at most this many points in total.
INFO_CAP = 10

#: Points of budget granted per tool.
BUDGET_PER_TOOL = 20


def score_findings(findings: list[Finding], tool_count: int = 1) -> int:
    """Score 0-100, normalised per tool so a big manifest is not punished for size.

    Calibrated against four real cases rather than invented: the three official
    MCP servers (18 tools, 12 warnings, 77 nudges) land at 87; a manifest with a
    hard collision, an unpinned package and a plaintext token lands at 79; the
    deliberately broken fixture lands at 35; a clean manifest at 100.

    A flat subtraction scored the official servers 0/100, which tells the reader
    nothing and makes the tool look broken.
    """
    penalty = sum(SEVERITY_WEIGHT[f.severity] for f in findings)
    infos = sum(1 for f in findings if f.severity is Severity.INFO)
    if infos:
        # Replace the per-finding info charge with the capped one.
        penalty += min(infos, INFO_CAP) - infos
    budget = BUDGET_PER_TOOL * max(tool_count, 1)
    return round(100 * max(0.0, 1 - penalty / budget))
