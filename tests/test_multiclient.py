"""Two clients are two worlds.

Cursor and Codex each load only their own config. If both declare a server called
`filesystem` with different commands, the same tool name exists in two lists that
are never loaded together — that is not an unreachable duplicate, and reporting it
as an error is a false positive.

The tests below build a sandbox: a temporary directory standing in for the user's
home and appdata. No real client config is read or written.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentcheckup import discovery
from agentcheckup.conflicts import ToolRef, detect_conflicts
from agentcheckup.models import Tool


def tool(name: str, description: str = "Do a thing with a path.") -> Tool:
    return Tool.from_raw(
        {
            "name": name,
            "description": description,
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        }
    )


def ref(server: str, name: str, client: str, description: str = "") -> ToolRef:
    return ToolRef(
        server=server,
        tool=tool(name, description or "Do a thing with a path and return text."),
        client=client,
    )


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def test_same_name_in_two_clients_is_not_a_hard_collision():
    found = detect_conflicts(
        [ref("filesystem#1", "read_file", "Cursor"), ref("filesystem#2", "read_file", "Codex CLI")]
    )
    assert [c.rule for c in found] == ["AGT204"]
    assert found[0].severity.value == "info"


def test_same_name_in_one_client_is_still_a_hard_collision():
    found = detect_conflicts(
        [ref("files", "read_file", "Cursor"), ref("git", "read_file", "Cursor")]
    )
    assert [c.rule for c in found] == ["AGT201"]


def test_unknown_client_falls_back_to_the_strict_answer():
    """Refs with no client are compared as if they shared one.

    That is the conservative choice: it is better to warn twice than to silently
    downgrade a real collision when the client is simply unknown.
    """
    found = detect_conflicts([ref("a", "read_file", ""), ref("b", "read_file", "")])
    assert [c.rule for c in found] == ["AGT201"]


def test_normalised_clash_across_clients_is_informational():
    found = detect_conflicts(
        [ref("a", "readFiles", "Cursor"), ref("b", "read_files", "Codex CLI")]
    )
    assert [c.rule for c in found] == ["AGT204"]


def test_cross_client_message_names_both_clients():
    found = detect_conflicts(
        [ref("a", "read_file", "Cursor"), ref("b", "read_file", "Codex CLI")]
    )
    message = found[0].message
    assert "Cursor" in message and "Codex CLI" in message


# --------------------------------------------------------------------------- #
# End to end through a sandboxed discovery
# --------------------------------------------------------------------------- #


def make_sandbox(tmp_path: Path) -> tuple[Path, Path]:
    """A fake home + appdata with two client configs that clash by name.

    Cursor keeps its servers in ``~/.cursor/mcp.json``; Claude Desktop keeps them
    in ``%APPDATA%/Claude/claude_desktop_config.json``. Both are JSON, so this
    sandbox does not depend on ``tomllib`` being present.
    """
    home = tmp_path / "home"
    appdata = home / "AppData" / "Roaming"
    (home / ".cursor").mkdir(parents=True)
    (appdata / "Claude").mkdir(parents=True)

    (home / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"filesystem": {"command": "cursor-fs"}}}), encoding="utf-8"
    )
    (appdata / "Claude" / "claude_desktop_config.json").write_text(
        json.dumps({"mcpServers": {"filesystem": {"command": "claude-fs"}}}), encoding="utf-8"
    )
    return home, appdata


def test_discovery_marks_which_client_each_server_came_from(tmp_path, monkeypatch):
    home, appdata = make_sandbox(tmp_path)
    monkeypatch.setattr(discovery, "HOME", home)
    monkeypatch.setattr(discovery, "_appdata", lambda: appdata)

    found = discovery.discover(cwd=tmp_path / "nowhere")
    labels = {label for label, _ in found}
    assert "Cursor" in labels
    assert "Claude Desktop" in labels

    servers = []
    for label, path in found:
        servers.extend(discovery.load_servers(path, label))

    clients = {server.client for server in servers}
    assert clients == {"Cursor", "Claude Desktop"}, clients
    # Same name, different commands: both survive, and each knows its client.
    assert len(servers) == 2
