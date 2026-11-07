"""Naming rules: the cheapest class of bug to catch and the easiest to fix."""

from __future__ import annotations

import re

from ..models import Finding, Severity, Tool
from .base import tool_rule

# The specification says names SHOULD be 1-128 characters of
# [A-Za-z0-9_.-]. Dots are included: `admin.tools.list` is an example the
# spec itself uses, so rejecting it produced a false error on a legal name.
ALLOWED = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


@tool_rule(
    "AGT001",
    Severity.WARNING,
    "Tool name is outside the characters the spec suggests",
)
def name_charset(tool: Tool):
    """The spec says tool names SHOULD be 1-128 chars of [A-Za-z0-9_.-].

    SHOULD, not MUST: a name outside that set is a portability risk rather than
    a protocol violation, so this is a warning. Strict clients reject such names
    and lenient ones mangle them, which surfaces as a "tool not found" the model
    cannot recover from.
    """
    if not tool.name:
        return Finding(
            rule="AGT001",
            severity=Severity.WARNING,
            message="Tool has an empty name.",
            hint="Every tool needs a non-empty `name`.",
        )
    if not ALLOWED.match(tool.name):
        return Finding(
            rule="AGT001",
            severity=Severity.WARNING,
            message=(
                f"Tool name {tool.name!r} is outside the suggested "
                f"[A-Za-z0-9_.-] set or exceeds 128 chars."
            ),
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
