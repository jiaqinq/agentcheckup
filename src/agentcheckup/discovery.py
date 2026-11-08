"""Find MCP client configs without asking the user where they are.

Every client invented its own filename, its own nesting and its own idea of where
"user config" lives. The point of ``agentcheckup`` is that you type one word and it
finds them, so this module is the difference between "a linter" and "a doctor".

Coverage is the whole product here. A client we cannot find is a client we cannot
diagnose, so the path table below is deliberately explicit rather than clever.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .models import ServerConfig

HOME = Path.home()

#: Keys that hold a server map at the top level of a config file.
SERVER_BLOCKS = ("mcpServers", "servers", "mcp_servers", "context_servers")

#: VS Code extension ids that store MCP servers in globalStorage.
VSCODE_EXTENSIONS = (
    ("Cline", "saoudrizwan.claude-dev"),
    ("Roo Code", "rooveterinaryinc.roo-cline"),
    ("Kilo Code", "kilocode.kilo-code"),
)


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))


def _platform_app_dir() -> Path:
    """Where GUI apps keep per-user data on this OS."""
    if sys.platform == "win32":
        return _appdata()
    if sys.platform == "darwin":
        return HOME / "Library" / "Application Support"
    return HOME / ".config"


def _editor_bases() -> list[tuple[str, Path]]:
    """VS Code and its forks, which share the globalStorage layout."""
    root = _platform_app_dir()
    return [
        ("VS Code", root / "Code"),
        ("Cursor", root / "Cursor"),
        ("VSCodium", root / "VSCodium"),
        ("Windsurf", root / "Windsurf"),
    ]


def candidate_paths(cwd: Path | None = None) -> list[tuple[str, Path]]:
    """Every known config location, with a human label. May not exist."""
    cwd = cwd or Path.cwd()
    app = _platform_app_dir()
    out: list[tuple[str, Path]] = []

    # Desktop clients
    out.append(("Claude Desktop", app / "Claude" / "claude_desktop_config.json"))
    out.append(("Zed", app / "Zed" / "settings.json"))

    # Editors: per-extension globalStorage
    for editor, base in _editor_bases():
        for label, extension in VSCODE_EXTENSIONS:
            out.append(
                (
                    f"{label} ({editor})",
                    base / "User" / "globalStorage" / extension / "settings" / "cline_mcp_settings.json",
                )
            )
        # VS Code 1.102+ keeps MCP servers under `mcp.servers` in settings.json.
        out.append((f"{editor} settings", base / "User" / "settings.json"))

    # Cross-platform, user-level
    out += [
        ("Claude Code", HOME / ".claude.json"),
        ("Cursor", HOME / ".cursor" / "mcp.json"),
        ("Zed (config dir)", HOME / ".config" / "zed" / "settings.json"),
        ("Codex CLI", HOME / ".codex" / "config.toml"),
        ("Continue", HOME / ".continue" / "config.json"),
    ]

    # Project-local
    out += [
        ("project .mcp.json", cwd / ".mcp.json"),
        ("project Cursor", cwd / ".cursor" / "mcp.json"),
        ("project VS Code", cwd / ".vscode" / "mcp.json"),
    ]

    return out


def discover(cwd: Path | None = None) -> list[tuple[str, Path]]:
    """Return only the configs that actually exist, deduplicated."""
    found: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for label, path in candidate_paths(cwd):
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.is_file():
                found.append((label, path))
        except OSError:
            continue
    return found


def _servers_from_block(block: object, source: str, client: str = "") -> list[ServerConfig]:
    if not isinstance(block, dict):
        return []
    return [
        ServerConfig.from_raw(name, entry, source=source, client=client)
        for name, entry in block.items()
        if isinstance(entry, dict)
    ]


def _servers_from_payload(payload: dict, tag: str, client: str = "") -> list[ServerConfig]:
    """Pull every server map out of one config document.

    Three shapes exist in the wild and all three are load-bearing:

    - top level: ``{"mcpServers": {...}}`` - Claude Desktop, Claude Code, Cursor
    - nested under ``mcp``: ``{"mcp": {"servers": {...}}}`` - VS Code settings.json
    - per project: ``{"projects": {"/path": {"mcpServers": {...}}}}`` - Claude Code
    """
    servers: list[ServerConfig] = []

    for key in SERVER_BLOCKS:
        servers.extend(_servers_from_block(payload.get(key), tag, client))

    mcp = payload.get("mcp")
    if isinstance(mcp, dict):
        for key in ("servers", "mcpServers"):
            servers.extend(_servers_from_block(mcp.get(key), f"{tag} [mcp]", client))

    projects = payload.get("projects")
    if isinstance(projects, dict):
        for project_path, project in projects.items():
            if not isinstance(project, dict):
                continue
            nested = _servers_from_block(
                project.get("mcpServers"), f"{tag} :: {project_path}", client
            )
            # Prefix so two projects exposing the same server name stay distinct.
            for server in nested:
                server.name = f"{Path(str(project_path)).name}:{server.name}"
            servers.extend(nested)

    return servers


def _load_json(path: Path, label: str) -> list[ServerConfig]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    return _servers_from_payload(payload, f"{label} ({path})", client=label)


#: TOML files that could not be read, with the reason. A config we skipped must
#: be announced: silently returning nothing makes a Codex user on Python 3.10
#: believe they have no servers configured.
TOML_SKIPPED: list[str] = []


def take_toml_skips() -> list[str]:
    """Drain the skip log so a caller can report it once."""
    taken = list(TOML_SKIPPED)
    TOML_SKIPPED.clear()
    return taken


def _load_toml(path: Path, label: str) -> list[ServerConfig]:
    """Codex CLI keeps its servers in TOML, not JSON.

    ``tomllib`` is stdlib from 3.11. On 3.10 the file cannot be read and the
    zero-dependency promise rules out pulling in ``tomli``, so the skip is
    recorded and reported rather than swallowed.
    """
    try:
        import tomllib
    except ImportError:
        TOML_SKIPPED.append(f"{path} (needs Python 3.11+ for tomllib)")
        return []

    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        TOML_SKIPPED.append(f"{path} ({exc})")
        return []
    if not isinstance(payload, dict):
        return []

    tag = f"{label} ({path})"
    servers: list[ServerConfig] = []
    block = payload.get("mcp_servers") or payload.get("mcpServers")
    if isinstance(block, dict):
        for name, entry in block.items():
            if isinstance(entry, dict):
                servers.append(ServerConfig.from_raw(name, entry, source=tag))
    return servers


def load_servers(path: Path, label: str = "") -> list[ServerConfig]:
    """Read servers from one config, whatever format it is in."""
    label = label or path.name
    if path.suffix.lower() == ".toml":
        return _load_toml(path, label)
    return _load_json(path, label)
