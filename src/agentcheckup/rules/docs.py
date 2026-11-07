"""Documentation rules.

Tool descriptions are not documentation for humans - they are the *prompt* the
model reads to decide whether and how to call the tool. Treating them as an
afterthought is the single most common reason agents pick the wrong tool.
"""

from __future__ import annotations

from ..models import Finding, Severity, Tool
from .base import tool_rule

#: Phrases that indicate the description says *when not* to use the tool.
#: Presence of any one is enough; we do not try to judge quality beyond this.
NEGATIVE_CUES = (
    "do not",
    "don't",
    "not for",
    "instead",
    "only when",
    "use this when",
    "prefer ",
    "avoid ",
    "not use",
)

MIN_DESCRIPTION = 40


@tool_rule("AGT010", Severity.ERROR, "Tool has no description")
def missing_description(tool: Tool):
    """A tool without a description is invisible to the model.

    It will still appear in the manifest and can still be called, but selection
    becomes a coin flip against every other tool.
    """
    if not tool.description.strip():
        return Finding(
            rule="AGT010",
            severity=Severity.ERROR,
            message=f"Tool {tool.name!r} has no description.",
            tool=tool.name,
            hint="One or two sentences: what it does, and what it returns.",
        )
    return None


@tool_rule("AGT011", Severity.INFO, "Tool description is too short to be useful")
def short_description(tool: Tool):
    """Under ~40 characters there is no room for the 'when' or the return shape."""
    text = tool.description.strip()
    if text and len(text) < MIN_DESCRIPTION:
        return Finding(
            rule="AGT011",
            severity=Severity.INFO,
            message=f"Tool {tool.name!r} description is {len(text)} chars.",
            tool=tool.name,
            hint="Aim for 80-200 chars: what it does, when to use it, what it returns.",
        )
    return None


@tool_rule("AGT012", Severity.INFO, "Description never says when NOT to use the tool")
def no_negative_guidance(tool: Tool):
    """Disambiguation is what separates a reliable tool set from a lucky one.

    When two tools overlap, the model needs an explicit boundary. One clause is
    usually enough: "Use this only for public repos; use `get_private_repo` for
    authenticated access."
    """
    text = tool.description.lower()
    if len(text) >= MIN_DESCRIPTION and not any(cue in text for cue in NEGATIVE_CUES):
        return Finding(
            rule="AGT012",
            severity=Severity.INFO,
            message=f"Tool {tool.name!r} description gives no disambiguation clause.",
            tool=tool.name,
            hint='Add e.g. "Use this only when ...; prefer `other_tool` for ...".',
        )
    return None


@tool_rule("AGT013", Severity.WARNING, "Input parameters are undocumented")
def undocumented_params(tool: Tool):
    """Each parameter is a decision the model has to make blind."""
    props = tool.properties()
    if not props:
        return None
    missing = [
        name
        for name, spec in props.items()
        if not (isinstance(spec, dict) and str(spec.get("description", "")).strip())
    ]
    if missing:
        preview = ", ".join(sorted(missing)[:5])
        more = "" if len(missing) <= 5 else f" (+{len(missing) - 5} more)"
        return Finding(
            rule="AGT013",
            severity=Severity.WARNING,
            message=f"Tool {tool.name!r} has {len(missing)} parameter(s) without a description: {preview}{more}.",
            tool=tool.name,
            hint="Describe format and constraints, not just the type.",
        )
    return None


@tool_rule("AGT014", Severity.INFO, "Description does not state the return shape")
def no_return_shape(tool: Tool):
    """The model plans the *next* call from what it expects back.

    Saying "returns a JSON array of {id, title}" is worth more than another
    sentence about the parameters.
    """
    text = tool.description.lower()
    cues = ("return", "returns", "output", "responds", "yields", "gives back")
    if len(text) >= MIN_DESCRIPTION and not any(c in text for c in cues):
        return Finding(
            rule="AGT014",
            severity=Severity.INFO,
            message=f"Tool {tool.name!r} description does not describe what it returns.",
            tool=tool.name,
            hint='Add "Returns ..." so the model can plan the next step.',
        )
    return None
