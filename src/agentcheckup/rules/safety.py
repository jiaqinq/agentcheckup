"""Safety rules.

Annotations exist so a host can gate destructive tools behind a confirmation
prompt. Missing or contradictory annotations silently disable that gate, which
is how an agent ends up deleting production data with no dialog box.
"""

from __future__ import annotations

from ..models import Finding, Severity, Tool
from .base import tool_rule

DESTRUCTIVE_VERBS = (
    "delete", "remove", "drop", "destroy", "truncate", "purge", "wipe",
    "kill", "terminate", "reset", "overwrite", "revoke",
)

EXEC_VERBS = ("exec", "execute", "shell", "run_command", "spawn", "eval", "system")

PATH_PARAMS = ("path", "file", "dir", "directory", "folder", "root", "cwd", "glob")

WRITE_VERBS = ("write", "create", "update", "edit", "patch", "put", "post", "append", "insert")


def _looks_like(tool: Tool, verbs: tuple[str, ...]) -> str | None:
    name = tool.name.lower()
    for verb in verbs:
        if name == verb or name.startswith(verb + "_") or f"_{verb}" in name:
            return verb
    return None


@tool_rule("AGT030", Severity.WARNING, "Destructive tool does not declare destructiveHint")
def destructive_without_hint(tool: Tool):
    """Hosts cannot ask "are you sure?" for a tool that does not admit it is risky."""
    verb = _looks_like(tool, DESTRUCTIVE_VERBS)
    if not verb:
        return None
    if tool.annotations.get("destructiveHint") is True:
        return None
    return Finding(
        rule="AGT030",
        severity=Severity.WARNING,
        message=f"Tool {tool.name!r} looks destructive (verb: {verb}) but sets no destructiveHint.",
        tool=tool.name,
        hint='Add "annotations": {"destructiveHint": true} so hosts can require confirmation.',
    )


@tool_rule("AGT031", Severity.WARNING, "readOnlyHint contradicts the tool name")
def readonly_contradiction(tool: Tool):
    """A wrong ``readOnlyHint: true`` is worse than no hint.

    Hosts use it to skip confirmation and to allow parallel calls.
    """
    if tool.annotations.get("readOnlyHint") is not True:
        return None
    verb = _looks_like(tool, DESTRUCTIVE_VERBS + WRITE_VERBS)
    if not verb:
        return None
    return Finding(
        rule="AGT031",
        severity=Severity.WARNING,
        message=f"Tool {tool.name!r} declares readOnlyHint: true but its name implies '{verb}'.",
        tool=tool.name,
        hint="Either the name or the annotation is wrong; hosts trust the annotation.",
    )


@tool_rule("AGT032", Severity.ERROR, "Tool exposes unconstrained command execution")
def unconstrained_exec(tool: Tool):
    """An `exec`-style tool with a free-form string is remote code execution by design.

    It is sometimes intentional (a local shell server), but it must be a
    deliberate, documented decision rather than a default.
    """
    verb = _looks_like(tool, EXEC_VERBS)
    if not verb:
        return None
    for name, spec in tool.properties().items():
        if not isinstance(spec, dict):
            continue
        if spec.get("type") != "string":
            continue
        if not any(k in spec for k in ("enum", "pattern", "const")):
            return Finding(
                rule="AGT032",
                severity=Severity.ERROR,
                message=f"Tool {tool.name!r} executes commands from an unconstrained string param {name!r}.",
                tool=tool.name,
                hint="Allow-list commands via `enum`, or drop the param and expose fixed operations.",
            )
    return None


@tool_rule("AGT033", Severity.INFO, "Filesystem parameter has no documented scope")
def unscoped_path(tool: Tool):
    """Without a stated root, the model will happily read ``/etc/shadow``.

    Documenting the sandbox root is cheap and makes the boundary testable.
    """
    for name, spec in tool.properties().items():
        if not isinstance(spec, dict):
            continue
        if not any(p in name.lower() for p in PATH_PARAMS):
            continue
        desc = str(spec.get("description", "")).lower()
        if any(k in desc for k in ("root", "sandbox", "within", "relative", "base dir", "allowed")):
            continue
        return Finding(
            rule="AGT033",
            severity=Severity.INFO,
            message=f"Tool {tool.name!r} path param {name!r} does not state its allowed root.",
            tool=tool.name,
            hint='Say e.g. "Relative to the sandbox root; absolute paths are rejected."',
        )
    return None


@tool_rule("AGT034", Severity.INFO, "Tool declares no annotations at all")
def no_annotations(tool: Tool):
    """No hints means the host must assume the worst case for every call."""
    if tool.annotations:
        return None
    return Finding(
        rule="AGT034",
        severity=Severity.INFO,
        message=f"Tool {tool.name!r} has no annotations.",
        tool=tool.name,
        hint='Declare at least {"readOnlyHint": true/false} and "destructiveHint" where relevant.',
    )
