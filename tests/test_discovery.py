from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agentcheckup.discovery import candidate_paths, discover, load_servers


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def server(name: str = "s") -> dict:
    return {"command": "python", "args": [f"{name}.py"]}


# --------------------------------------------------------------------------- #
# path table
# --------------------------------------------------------------------------- #


def test_every_editor_gets_the_extension_paths():
    labels = [location.label for location in candidate_paths(Path("/tmp/x"))]
    joined = " ".join(labels)
    for expected in ("Cline", "Roo Code", "Kilo Code", "Zed", "Codex CLI", "Claude Code"):
        assert expected in joined, f"{expected} missing from {labels}"


def test_paths_are_absolute_and_unique():
    # Use the real cwd: a POSIX-looking literal is not absolute on Windows, which
    # would make this test assert something about the test, not the code.
    paths = [location.path for location in candidate_paths(Path.cwd())]
    assert all(p.is_absolute() for p in paths)
    assert len(paths) == len(set(paths))


def test_discovery_finds_project_local_config(tmp_path):
    cfg = write_json(tmp_path / ".mcp.json", {"mcpServers": {"demo": server()}})
    assert cfg in [location.path for location in discover(cwd=tmp_path)]


def test_discovery_ignores_missing_paths(tmp_path):
    # A fresh temp dir has no client configs; discovery must return nothing
    # rather than raising or inventing paths.
    found = [
        location.path for location in discover(cwd=tmp_path)
        if tmp_path in location.path.parents
    ]
    assert found == []


# --------------------------------------------------------------------------- #
# config shapes
# --------------------------------------------------------------------------- #


def test_top_level_mcp_servers(tmp_path):
    cfg = write_json(tmp_path / "a.json", {"mcpServers": {"one": server()}})
    assert [s.name for s in load_servers(cfg)] == ["one"]


@pytest.mark.parametrize("key", ["mcpServers", "servers", "mcp_servers", "context_servers"])
def test_all_top_level_keys_are_accepted(tmp_path, key):
    cfg = write_json(tmp_path / "a.json", {key: {"one": server()}})
    assert [s.name for s in load_servers(cfg)] == ["one"]


def test_vscode_nested_mcp_servers(tmp_path):
    # VS Code 1.102+ settings.json puts servers under `mcp.servers`.
    cfg = write_json(tmp_path / "settings.json", {"mcp": {"servers": {"vsc": server()}}})
    assert [s.name for s in load_servers(cfg)] == ["vsc"]


def test_zed_context_servers(tmp_path):
    cfg = write_json(tmp_path / "settings.json", {"context_servers": {"zed": server()}})
    assert [s.name for s in load_servers(cfg)] == ["zed"]


def test_claude_code_project_servers_load_only_for_that_project(tmp_path):
    """`projects` entries are local scope: they apply only in that directory.

    The previous version loaded every project's servers into one audit and
    prefixed their names to keep them apart. That invented servers the user does
    not have, and inflated both the manifest and the token estimate.
    """
    cfg = write_json(
        tmp_path / "claude.json",
        {
            "mcpServers": {"global": server("a")},
            "projects": {"/home/me/proj": {"mcpServers": {"local": server("b")}}},
        },
    )

    elsewhere = {s.name for s in load_servers(cfg, "Claude Code", cwd=tmp_path)}
    assert elsewhere == {"global"}

    inside = {
        s.name
        for s in load_servers(cfg, "Claude Code", cwd=Path("/home/me/proj"))
    }
    assert inside == {"global", "local"}


def test_claude_code_project_servers_are_marked_local_scope(tmp_path):
    cfg = write_json(
        tmp_path / "claude.json",
        {"projects": {"/home/me/proj": {"mcpServers": {"local": server("b")}}}},
    )
    servers = load_servers(cfg, "Claude Code", cwd=Path("/home/me/proj"))
    assert [s.scope for s in servers] == ["local"]



def test_codex_toml_is_parsed(tmp_path):
    if sys.version_info < (3, 11):
        pytest.skip("tomllib is stdlib from 3.11")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[mcp_servers.demo]\ncommand = "npx"\nargs = ["-y", "pkg@1.0.0"]\n',
        encoding="utf-8",
    )
    servers = load_servers(cfg, "Codex CLI")
    assert [s.name for s in servers] == ["demo"]
    assert servers[0].command == "npx"


def test_env_and_url_are_read(tmp_path):
    cfg = write_json(
        tmp_path / "a.json",
        {
            "mcpServers": {
                "remote": {"url": "https://example.test/sse"},
                "local": {"command": "uvx", "args": ["pkg"], "env": {"TOKEN": "x"}},
            }
        },
    )
    by_name = {s.name: s for s in load_servers(cfg)}
    assert by_name["remote"].url == "https://example.test/sse"
    assert by_name["local"].env == {"TOKEN": "x"}


# --------------------------------------------------------------------------- #
# robustness
# --------------------------------------------------------------------------- #


def test_broken_json_is_skipped(tmp_path):
    cfg = tmp_path / "bad.json"
    cfg.write_text("{not json", encoding="utf-8")
    assert load_servers(cfg) == []


def test_non_object_payload_is_skipped(tmp_path):
    cfg = write_json(tmp_path / "list.json", [])
    assert load_servers(cfg) == []


def test_missing_file_returns_empty(tmp_path):
    assert load_servers(Path(tmp_path) / "nope.json") == []


def test_entry_that_is_not_an_object_is_ignored(tmp_path):
    cfg = write_json(tmp_path / "a.json", {"mcpServers": {"ok": server(), "bad": "string"}})
    assert [s.name for s in load_servers(cfg)] == ["ok"]
