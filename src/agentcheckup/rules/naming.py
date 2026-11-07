"""Naming rules: the cheapest class of bug to catch and the easiest to fix."""

from __future__ import annotations

import re

from ..models import Finding, Severity, Tool
from .base import tool_rule

ALLOWED = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


@tool_rule(
    "AGT001",
    Severity.ERROR,
    "Tool name is not a valid MCP identifier",
)
def name_charset(tool: Tool):
    """MCP tool names must be 1-64 chars of [A-Za-z0-9_-].

    Anything else is rejected by strict clients and silently mangled by others,
    which turns into a "tool not found" bug the model cannot recover from.
    """
    if not tool.name:
        return Finding(
            rule="AGT001",
            severity=Severity.ERROR,
            message="Tool has an empty name.",
            hint="Every tool needs a non-empty `name`.",
        )
    if not ALLOWED.match(tool.name):
        return Finding(
            rule="AGT001",
            severity=Severity.ERROR,
            message=f"Tool name {tool.name!r} contains characters outside [A-Za-z0-9_-] or exceeds 64 chars.",
            tool=tool.name,
            hint="Rename to something like `read_file` or `search-docs`.",
        )
    return None


@tool_rule(
    "AGT002",
    Severity.INFO,
    "Tool name is not snake_case",
)
def name_style(tool: Tool):
    """Consistent casing measurably helps tool selection.

    Models see the whole manifest at once; mixed `readFile` / `read_file` /
    `ReadFile` makes near-duplicate names harder to disambiguate.
    """
    if tool.name and not SNAKE.match(tool.name):
        return Finding(
            rule="AGT002",
            severity=Severity.INFO,
            message=f"Tool name {tool.name!r} is not snake_case.",
            tool=tool.name,
            hint="Prefer `read_file` over `readFile` / `ReadFile`.",
        )
    return None


#: Prefixes that are almost always a server/domain name rather than a verb.
#: Deliberately a closed list: a "first segment has >= 3 chars" heuristic fires
#: on legitimate names like ``search_docs_by_tag`` and the false positives make
#: the whole report untrustworthy.
SERVER_PREFIXES = frozenset(
    {
        "github", "gitlab", "jira", "slack", "notion", "linear", "sentry",
        "postgres", "mysql", "sqlite", "redis", "mongo", "elastic",
        "browser", "playwright", "chrome", "puppeteer",
        "filesystem", "files", "fs", "shell", "docker", "k8s", "kubernetes",
        "google", "gmail", "calendar", "drive", "aws", "s3", "azure", "gcp",
    }
)


@tool_rule(
    "AGT003",
    Severity.INFO,
    "Tool name encodes the server name as a prefix",
)
def name_redundant_prefix(tool: Tool):
    """`github_get_issue` inside the `github` server wastes context.

    The client already namespaces by server, so the prefix is pure overhead on
    every single request.
    """
    head = tool.name.split("_", 1)[0].lower()
    if tool.name.count("_") >= 2 and head in SERVER_PREFIXES:
        return Finding(
            rule="AGT003",
            severity=Severity.INFO,
            message=f"Tool name {tool.name!r} repeats the server/domain name as a prefix.",
            tool=tool.name,
            hint="The client already namespaces by server; drop the prefix to save context.",
        )
    return None
