"""Input schema rules.

The schema is the contract. A loose contract does not fail loudly - it produces
a plausible-looking wrong call, which is far more expensive to debug.
"""

from __future__ import annotations

from ..models import Finding, Severity, Tool
from .base import tool_rule

#: Verbs that imply unbounded input size.
UNBOUNDED_HINTS = ("query", "sql", "text", "content", "body", "data", "html", "code")


@tool_rule("AGT020", Severity.ERROR, "inputSchema is not an object schema")
def schema_not_object(tool: Tool):
    """MCP requires ``{"type": "object", ...}``.

    Providers that emit ``{"type": "array"}`` or omit ``type`` break client-side
    validation in strict implementations.
    """
    schema = tool.input_schema
    if not schema:
        return Finding(
            rule="AGT020",
            severity=Severity.ERROR,
            message=f"Tool {tool.name!r} has no inputSchema.",
            tool=tool.name,
            hint='Use {"type": "object", "properties": {}} for a no-argument tool.',
        )
    if schema.get("type") != "object":
        return Finding(
            rule="AGT020",
            severity=Severity.ERROR,
            message=f"Tool {tool.name!r} inputSchema type is {schema.get('type')!r}, expected 'object'.",
            tool=tool.name,
            hint="MCP tool arguments are always a JSON object.",
        )
    return None


@tool_rule("AGT021", Severity.WARNING, "Required references an undeclared property")
def required_unknown(tool: Tool):
    """A dangling ``required`` entry makes every call fail validation client-side."""
    props = tool.properties()
    unknown = [r for r in tool.required() if r not in props]
    if unknown:
        return Finding(
            rule="AGT021",
            severity=Severity.WARNING,
            message=f"Tool {tool.name!r} requires undeclared property/properties: {', '.join(unknown)}.",
            tool=tool.name,
            hint="Every name in `required` must exist under `properties`.",
        )
    return None


@tool_rule("AGT022", Severity.INFO, "Schema allows undeclared properties")
def additional_properties_open(tool: Tool):
    """Models happily invent extra keys when the schema permits it.

    ``additionalProperties: false`` turns a silent wrong-argument bug into a
    visible validation error.
    """
    if tool.input_schema and tool.input_schema.get("additionalProperties") is not False:
        return Finding(
            rule="AGT022",
            severity=Severity.INFO,
            message=f"Tool {tool.name!r} schema does not set additionalProperties: false.",
            tool=tool.name,
            hint="Closing the schema stops the model from inventing extra keys.",
        )
    return None


@tool_rule("AGT023", Severity.INFO, "Parameter has no enum or format constraint")
def unconstrained_string(tool: Tool):
    """Free-form strings are the main source of retry loops.

    A ``format`` (date-time, uri, email) or an ``enum`` costs one line and
    removes an entire failure class.
    """
    offenders: list[str] = []
    for name, spec in tool.properties().items():
        if not isinstance(spec, dict):
            continue
        if spec.get("type") != "string":
            continue
        if not any(k in spec for k in ("enum", "format", "pattern", "const")):
            offenders.append(name)
    if offenders:
        preview = ", ".join(sorted(offenders)[:5])
        more = "" if len(offenders) <= 5 else f" (+{len(offenders) - 5} more)"
        return Finding(
            rule="AGT023",
            severity=Severity.INFO,
            message=f"Tool {tool.name!r} has unconstrained string param(s): {preview}{more}.",
            tool=tool.name,
            hint="Add `enum`, `format` or `pattern` where the value space is finite.",
        )
    return None


@tool_rule("AGT024", Severity.INFO, "Array parameter has no size bound")
def unbounded_array(tool: Tool):
    """Without ``maxItems`` a single call can blow the context window."""
    offenders = [
        name
        for name, spec in tool.properties().items()
        if isinstance(spec, dict)
        and spec.get("type") == "array"
        and "maxItems" not in spec
    ]
    if offenders:
        return Finding(
            rule="AGT024",
            severity=Severity.INFO,
            message=f"Tool {tool.name!r} array param(s) without maxItems: {', '.join(sorted(offenders)[:5])}.",
            tool=tool.name,
            hint="Set `maxItems` and document the cap in the description.",
        )
    return None


@tool_rule("AGT025", Severity.WARNING, "Parameter name is ambiguous")
def ambiguous_param_name(tool: Tool):
    """`data`, `value`, `arg`, `input`, `options` tell the model nothing.

    The model has to infer the expected shape from the type alone, which is
    exactly where hallucinated payloads come from.
    """
    vague = {"data", "value", "arg", "args", "input", "param", "options", "obj", "thing"}
    hits = [n for n in tool.properties() if n.lower() in vague]
    if hits:
        return Finding(
            rule="AGT025",
            severity=Severity.WARNING,
            message=f"Tool {tool.name!r} has ambiguous param name(s): {', '.join(sorted(hits))}.",
            tool=tool.name,
            hint="Name the payload for what it is: `markdown_body`, `filter_expression`.",
        )
    return None
