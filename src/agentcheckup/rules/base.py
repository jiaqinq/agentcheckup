"""Rule protocol and registry.

Adding a rule should be a single small file plus a decorator - that is the
whole point, because the fastest way to grow an OSS project is to leave obvious
room for other people's pull requests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple, Protocol

from ..models import Finding, Severity


class Rule(Protocol):
    id: str
    severity: Severity
    title: str

    def check(self, subject):  # noqa: ANN001 - Tool or ServerConfig
        ...


TOOL_RULES: list[Rule] = []
CONFIG_RULES: list[Rule] = []


class SuiteRule(NamedTuple):
    """A rule that needs the whole manifest, so it cannot live in a single file."""

    id: str
    severity: Severity
    title: str


#: Documented here so ``agentcheckup rules`` and the SARIF catalogue stay complete.
SUITE_RULES: list[SuiteRule] = [
    SuiteRule("AGT004", Severity.ERROR, "Tool name is duplicated"),
    SuiteRule("AGT105", Severity.INFO, "Server did not return a tool list"),
    SuiteRule("AGT201", Severity.ERROR, "Same tool name exposed by two servers"),
    SuiteRule("AGT202", Severity.WARNING, "Two servers expose the same name once normalised"),
    SuiteRule("AGT203", Severity.WARNING, "Two servers expose overlapping tools"),
]


def _make_rule(
    rule_id: str,
    sev: Severity,
    rule_title: str,
    fn: Callable,
    doc: str | None,
) -> Rule:
    class _FnRule:
        def check(self, subject):  # noqa: ANN001
            result = fn(subject)
            if result is None:
                return []
            if isinstance(result, Finding):
                return [result]
            return list(result)

    _FnRule.id = rule_id
    _FnRule.severity = sev
    _FnRule.title = rule_title
    _FnRule.__doc__ = doc or fn.__doc__
    return _FnRule()


def tool_rule(rule_id: str, severity: Severity, title: str) -> Callable:
    """Register a tool-level rule.

    The decorated function takes a :class:`Tool` and returns either a single
    :class:`Finding`, an iterable of them, or ``None``.
    """

    def decorator(fn: Callable) -> Callable:
        TOOL_RULES.append(_make_rule(rule_id, severity, title, fn, fn.__doc__))
        return fn

    return decorator


def config_rule(rule_id: str, severity: Severity, title: str) -> Callable:
    """Register a client-config level rule (operates on ServerConfig)."""

    def decorator(fn: Callable) -> Callable:
        CONFIG_RULES.append(_make_rule(rule_id, severity, title, fn, fn.__doc__))
        return fn

    return decorator
