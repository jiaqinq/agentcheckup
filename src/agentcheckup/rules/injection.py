"""Prompt-injection rules for tool descriptions.

Tool descriptions are injected into the model's context verbatim. That makes
them an *input* channel controlled by whoever wrote the server - a supply-chain
surface that most MCP setups never audit. These rules flag the shapes that show
up in real attacks, not hypothetical ones.
"""

from __future__ import annotations

import re

from ..models import Finding, Severity, Tool
from ..tokens import has_invisible_chars
from .base import tool_rule

#: Instructions aimed at the model rather than the reader.
OVERRIDE_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+(instructions|prompts|rules)", re.I),
    re.compile(r"disregard\s+(all\s+)?(the\s+)?(previous|prior|above)", re.I),
    re.compile(r"forget\s+(everything|all)\s+(above|before|you)", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an|in)\b", re.I),
    re.compile(r"new\s+(system\s+)?instructions?\s*:", re.I),
    re.compile(r"system\s*prompt", re.I),
)

#: Requests to keep something hidden from the human.
CONCEALMENT_PATTERNS = (
    re.compile(r"do\s+not\s+(tell|inform|mention|reveal)\s+(the\s+)?(user|human)", re.I),
    re.compile(r"without\s+(telling|informing|notifying)\s+(the\s+)?user", re.I),
    re.compile(r"(hide|conceal)\s+(this|it)\s+from", re.I),
)

#: Outbound data movement embedded in a description.
EXFIL_PATTERNS = (
    re.compile(r"(send|post|upload|forward|exfiltrate)\s+.{0,40}\b(to|at)\s+https?://", re.I),
    re.compile(r"https?://[^\s]+\?[^\s]*(key|token|secret|password)=", re.I),
)

#: Tool-poisoning via markup the model may read but the reviewer skims past.
MARKUP_PATTERNS = (
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"<\|[^|]*\|>"),  # chat-template control tokens
)


@tool_rule("AGT040", Severity.ERROR, "Description tries to override model instructions")
def instruction_override(tool: Tool):
    """A legitimate description never talks to the model in the imperative-about-itself.

    This is the classic tool-poisoning payload: the server author (or anyone who
    compromised the package) rewrites the agent's priorities at load time.
    """
    for pattern in OVERRIDE_PATTERNS:
        match = pattern.search(tool.description)
        if match:
            return Finding(
                rule="AGT040",
                severity=Severity.ERROR,
                message=f"Tool {tool.name!r} description contains an instruction-override phrase: {match.group(0)!r}.",
                tool=tool.name,
                hint="Rewrite the description to describe the tool, not to instruct the model.",
            )
    return None


@tool_rule("AGT041", Severity.ERROR, "Description asks the model to hide behaviour from the user")
def concealment(tool: Tool):
    """Anything the model is told to hide from its user is, by definition, not auditable."""
    for pattern in CONCEALMENT_PATTERNS:
        match = pattern.search(tool.description)
        if match:
            return Finding(
                rule="AGT041",
                severity=Severity.ERROR,
                message=f"Tool {tool.name!r} description contains a concealment phrase: {match.group(0)!r}.",
                tool=tool.name,
                hint="Remove it. There is no legitimate reason to hide a tool call from the user.",
            )
    return None


@tool_rule("AGT042", Severity.WARNING, "Description embeds an outbound URL with credentials")
def exfiltration(tool: Tool):
    """Tool descriptions should not contain endpoints at all, let alone with tokens."""
    for pattern in EXFIL_PATTERNS:
        match = pattern.search(tool.description)
        if match:
            return Finding(
                rule="AGT042",
                severity=Severity.WARNING,
                message=f"Tool {tool.name!r} description contains a suspicious outbound URL: {match.group(0)[:80]!r}.",
                tool=tool.name,
                hint="Endpoints belong in config, never in the model-visible description.",
            )
    return None


@tool_rule("AGT043", Severity.ERROR, "Description hides text with invisible characters")
def invisible_text(tool: Tool):
    """Zero-width and bidi characters let a description read one way and behave another."""
    suspects = has_invisible_chars(tool.description)
    if suspects:
        return Finding(
            rule="AGT043",
            severity=Severity.ERROR,
            message=f"Tool {tool.name!r} description contains invisible characters: {', '.join(suspects)}.",
            tool=tool.name,
            hint="Strip zero-width / bidi control characters; re-save the description as plain text.",
        )
    return None


@tool_rule("AGT044", Severity.WARNING, "Description hides instructions in markup")
def markup_hidden(tool: Tool):
    """HTML comments and chat-template tokens are invisible in most UIs."""
    for pattern in MARKUP_PATTERNS:
        match = pattern.search(tool.description)
        if match:
            return Finding(
                rule="AGT044",
                severity=Severity.WARNING,
                message=f"Tool {tool.name!r} description contains markup the UI may hide: {match.group(0)[:60]!r}.",
                tool=tool.name,
                hint="Descriptions should be plain prose; no comments or template tokens.",
            )
    return None
