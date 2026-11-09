"""Scope is not client.

Every client that supports both a user-level and a project-level config has to
decide what happens when both declare the same server name. Until 0.9.0 this
project treated the two scopes as two *clients*, so the pair was reported as
"separate clients, never loaded together" — a statement that is false for the
same client, and one that hid the fact that one entry shadows the other.

What is modelled here is deliberately narrow: only clients whose documentation
states the rule get resolved. Guessing would either hide a real collision or
invent one.
"""

from __future__ import annotations

from agentcheckup.conflicts import ToolRef, detect_conflicts
from agentcheckup.discovery import resolve_scopes
from agentcheckup.engine import lint_audit
from agentcheckup.models import ServerConfig, Severity, Tool


def server(name: str, client: str, scope: str, command: str) -> ServerConfig:
    return ServerConfig(
        name=name,
        command=command,
        client=client,
        scope=scope,
        instance=f"{name}-{scope}",
    )


def tool(name: str = "read_file", description: str = "Read a file.") -> Tool:
    return Tool.from_raw(
        {
            "name": name,
            "description": description,
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        }
    )


def ref(
    name: str,
    client: str,
    scope: str,
    description: str = "Read a file.",
    server: str | None = None,
    server_name: str | None = None,
) -> ToolRef:
    """A tool reference. ``server`` is the instance key, ``server_name`` the name."""
    instance = server or f"{client}:{scope}"
    return ToolRef(
        server=instance,
        tool=tool(name, description),
        client=client,
        scope=scope,
        server_name=server_name or instance,
    )


# --------------------------------------------------------------------------- #
# Documented precedence: Claude Code
# --------------------------------------------------------------------------- #


def test_claude_code_project_shadows_user():
    user = server("filesystem", "Claude Code", "user", "user-fs")
    project = server("filesystem", "Claude Code", "project", "project-fs")

    kept, shadowed = resolve_scopes([user, project])

    assert [s.scope for s in kept] == ["project"]
    assert len(shadowed) == 1
    loser, winner = shadowed[0]
    assert loser is user
    assert winner is project


def test_claude_code_local_beats_project():
    project = server("fs", "Claude Code", "project", "project-fs")
    local = server("fs", "Claude Code", "local", "local-fs")

    kept, shadowed = resolve_scopes([project, local])

    assert [s.scope for s in kept] == ["local"]
    assert shadowed[0][0] is project


def test_two_entries_at_the_same_scope_are_not_shadowing():
    """Same scope means a genuine duplicate, which must still be reported."""
    first = server("filesystem", "Claude Code", "user", "a")
    second = server("filesystem", "Claude Code", "user", "b")

    kept, shadowed = resolve_scopes([first, second])

    assert len(kept) == 2
    assert shadowed == []


def test_shadowing_is_per_client_not_global():
    """A project entry in one client must not shadow a user entry in another."""
    claude = server("filesystem", "Claude Code", "user", "a")
    cursor = server("filesystem", "Cursor", "project", "b")

    kept, shadowed = resolve_scopes([claude, cursor])

    assert len(kept) == 2
    assert shadowed == []


# --------------------------------------------------------------------------- #
# Undocumented precedence: everything else
# --------------------------------------------------------------------------- #


def test_cursor_scopes_are_left_alone():
    """Cursor reads both files but documents no rule for a duplicate name."""
    user = server("fs", "Cursor", "user", "a")
    project = server("fs", "Cursor", "project", "b")

    kept, shadowed = resolve_scopes([user, project])

    assert len(kept) == 2
    assert shadowed == []


def test_unknown_client_scopes_are_left_alone():
    a = server("fs", "Some New Client", "user", "a")
    b = server("fs", "Some New Client", "project", "b")

    kept, shadowed = resolve_scopes([a, b])

    assert len(kept) == 2
    assert shadowed == []


# --------------------------------------------------------------------------- #
# What the report says
# --------------------------------------------------------------------------- #


def test_shadowed_server_is_reported_as_information():
    user = server("filesystem", "Claude Code", "user", "user-fs")
    project = server("filesystem", "Claude Code", "project", "project-fs")
    kept, shadowed = resolve_scopes([user, project])

    report = lint_audit(
        kept,
        {"filesystem-project": [tool()]},
        failures={},
        shadowed=shadowed,
    )

    notes = [f for f in report.findings if f.rule == "AGT205"]
    assert len(notes) == 1
    assert notes[0].severity is Severity.INFO
    assert "user" in notes[0].message and "project" in notes[0].message
    # The shadowed entry is not a collision.
    assert not [f for f in report.findings if f.rule == "AGT201"]


def test_same_name_across_scopes_is_not_a_tool_collision():
    """The pair is a scope question, answered from the config, not from tools."""
    found = detect_conflicts(
        [
            ref("read_file", "Cursor", "user", server="filesystem#1", server_name="filesystem"),
            ref("read_file", "Cursor", "project", server="filesystem#2", server_name="filesystem"),
        ]
    )

    assert found == []


def test_undocumented_precedence_is_reported_without_any_tools():
    """`--no-spawn` has no tool lists, and the ambiguity still has to surface."""
    servers = [
        server("fs", "Cursor", "user", "a"),
        server("fs", "Cursor", "project", "b"),
    ]

    report = lint_audit(servers, tools_by_server={}, failures={})

    notes = [f for f in report.findings if f.rule == "AGT205"]
    assert len(notes) == 1
    assert notes[0].severity is Severity.INFO
    assert "user" in notes[0].message and "project" in notes[0].message


def test_resolved_precedence_does_not_also_report_ambiguity():
    """Claude Code is resolved, so it gets exactly one note, not two."""
    user = server("filesystem", "Claude Code", "user", "user-fs")
    project = server("filesystem", "Claude Code", "project", "project-fs")
    kept, shadowed = resolve_scopes([user, project])

    report = lint_audit(kept, {"filesystem-project": [tool()]}, failures={}, shadowed=shadowed)

    notes = [f for f in report.findings if f.rule == "AGT205"]
    assert len(notes) == 1
    assert "shadowed" in notes[0].message


def test_same_name_across_clients_stays_agt204():
    found = detect_conflicts(
        [ref("read_file", "Cursor", "user"), ref("read_file", "Codex CLI", "user")]
    )

    assert [c.rule for c in found] == ["AGT204"]


def test_same_client_same_scope_is_still_a_hard_collision():
    """Two servers of one client at one scope really do collide."""
    found = detect_conflicts(
        [
            ref("read_file", "Cursor", "user", server="filesystem#1"),
            ref("read_file", "Cursor", "user", server="filesystem#2"),
        ]
    )

    assert [c.rule for c in found] == ["AGT201"]
    assert found[0].severity is Severity.ERROR


def test_missing_scope_keeps_the_strict_answer():
    """A config we could not attribute keeps the old, louder behaviour."""
    a = ToolRef(server="a", tool=tool("read_file"), client="Cursor")
    b = ToolRef(server="b", tool=tool("read_file"), client="Cursor")

    assert [c.rule for c in detect_conflicts([a, b])] == ["AGT201"]


def test_different_servers_of_one_client_at_two_scopes_still_collide():
    """Only a repeated *server name* is a shadowing question.

    `github` at user scope and `docs` at project scope are two different
    servers; both load, and a shared tool name between them is a real collision.
    """
    found = detect_conflicts(
        [
            ref("search", "Cursor", "user", server="github", server_name="github"),
            ref("search", "Cursor", "project", server="docs", server_name="docs"),
        ]
    )

    assert [c.rule for c in found] == ["AGT201"]
