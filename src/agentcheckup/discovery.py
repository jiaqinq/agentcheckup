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
from typing import NamedTuple

from .models import ServerConfig

HOME = Path.home()


class ConfigLocation(NamedTuple):
    """One place a client keeps its server list.

    ``client`` and ``scope`` are separate on purpose. Claude Code's project
    ``.mcp.json`` is still Claude Code — it is the same client at a different
    scope, and a name clash between the two scopes is a shadowing rule, not two
    clients that never meet.
    """

    label: str
    path: Path
    client: str
    scope: str  # "user" | "project" | "local"

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


def candidate_paths(cwd: Path | None = None) -> list[ConfigLocation]:
    """Every known config location, with a human label. May not exist."""
    cwd = cwd or Path.cwd()
    app = _platform_app_dir()
    out: list[ConfigLocation] = []

    # Desktop clients
    out.append(ConfigLocation("Claude Desktop", app / "Claude" / "claude_desktop_config.json", "Claude Desktop", "user"))
    out.append(ConfigLocation("Zed", app / "Zed" / "settings.json", "Zed", "user"))

    # Editors: per-extension globalStorage
    for editor, base in _editor_bases():
        for label, extension in VSCODE_EXTENSIONS:
            out.append(
                ConfigLocation(
                    f"{label} ({editor})",
                    base / "User" / "globalStorage" / extension / "settings" / "cline_mcp_settings.json",
                    f"{label} ({editor})",
                    "user",
                )
            )
        # VS Code 1.102+ keeps MCP servers under `mcp.servers` in settings.json.
        out.append(
            ConfigLocation(
                f"{editor} settings", base / "User" / "settings.json", f"{editor} settings", "user"
            )
        )

    # Cross-platform, user-level
    out += [
        ConfigLocation("Claude Code", HOME / ".claude.json", "Claude Code", "user"),
        ConfigLocation("Cursor", HOME / ".cursor" / "mcp.json", "Cursor", "user"),
        ConfigLocation("Zed (config dir)", HOME / ".config" / "zed" / "settings.json", "Zed (config dir)", "user"),
        ConfigLocation("Codex CLI", HOME / ".codex" / "config.toml", "Codex CLI", "user"),
        ConfigLocation("Continue", HOME / ".continue" / "config.json", "Continue", "user"),
    ]

    # Project-local. These belong to the client named in the third field, not to
    # a client of their own: `.cursor/mcp.json` is Cursor at project scope.
    out += [
        ConfigLocation("project .mcp.json", cwd / ".mcp.json", "Claude Code", "project"),
        ConfigLocation("project Cursor", cwd / ".cursor" / "mcp.json", "Cursor", "project"),
        ConfigLocation("project VS Code", cwd / ".vscode" / "mcp.json", "VS Code", "project"),
    ]

    return out


def discover(cwd: Path | None = None) -> list[ConfigLocation]:
    """Return only the configs that actually exist, deduplicated."""
    found: list[ConfigLocation] = []
    seen: set[str] = set()
    for location in candidate_paths(cwd):
        path = location.path
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.is_file():
                found.append(location)
        except OSError:
            continue
    return found



def _servers_from_block(
    block: object, source: str, client: str = "", scope: str = ""
) -> list[ServerConfig]:
    if not isinstance(block, dict):
        return []
    return [
        ServerConfig.from_raw(name, entry, source=source, client=client, scope=scope)
        for name, entry in block.items()
        if isinstance(entry, dict)
    ]


def _same_path(a: str | Path, b: str | Path) -> bool:
    """Compare two paths the way the filesystem would."""
    try:
        left = Path(str(a)).expanduser().resolve()
        right = Path(str(b)).expanduser().resolve()
    except (OSError, ValueError):
        return str(a) == str(b)
    if sys.platform == "win32":
        return str(left).lower() == str(right).lower()
    return left == right


def _servers_from_payload(
    payload: dict, tag: str, client: str = "", scope: str = "", cwd: Path | None = None
) -> list[ServerConfig]:
    """Pull every server map out of one config document.

    Three shapes exist in the wild and all three are load-bearing:

    - top level: ``{"mcpServers": {...}}`` - Claude Desktop, Claude Code, Cursor
    - nested under ``mcp``: ``{"mcp": {"servers": {...}}}`` - VS Code settings.json
    - per project: ``{"projects": {"/path": {"mcpServers": {...}}}}`` - Claude Code

    The per-project shape is **local scope**: those servers load only when Claude
    Code runs in that directory. Loading every project's entries into one audit
    invented servers the user does not have, so only the entry matching ``cwd``
    is read. When ``cwd`` is not listed, none of them apply.
    """
    servers: list[ServerConfig] = []

    for key in SERVER_BLOCKS:
        servers.extend(_servers_from_block(payload.get(key), tag, client, scope))

    mcp = payload.get("mcp")
    if isinstance(mcp, dict):
        for key in ("servers", "mcpServers"):
            servers.extend(_servers_from_block(mcp.get(key), f"{tag} [mcp]", client, scope))

    projects = payload.get("projects")
    if isinstance(projects, dict):
        here = cwd or Path.cwd()
        for project_path, project in projects.items():
            if not isinstance(project, dict):
                continue
            if not _same_path(project_path, here):
                continue
            servers.extend(
                _servers_from_block(
                    project.get("mcpServers"), f"{tag} :: {project_path}", client, "local"
                )
            )

    return servers


def _load_json(
    path: Path, label: str, client: str = "", scope: str = "", cwd: Path | None = None
) -> list[ServerConfig]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    return _servers_from_payload(payload, f"{label} ({path})", client, scope, cwd)



#: TOML files that could not be read, with the reason. A config we skipped must
#: be announced: silently returning nothing makes a Codex user on Python 3.10
#: believe they have no servers configured.
TOML_SKIPPED: list[str] = []


def take_toml_skips() -> list[str]:
    """Drain the skip log so a caller can report it once."""
    taken = list(TOML_SKIPPED)
    TOML_SKIPPED.clear()
    return taken


def _load_toml(
    path: Path, label: str, client: str = "", scope: str = ""
) -> list[ServerConfig]:
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
                servers.append(
                    ServerConfig.from_raw(
                        name, entry, source=tag, client=client, scope=scope
                    )
                )
    return servers


#: Documented scope precedence per client, highest first.
#:
#: Only clients whose documentation states the rule appear here. Cursor and VS
#: Code both read a user file and a workspace file but document no rule for a
#: duplicate name, so they are deliberately absent: guessing would either hide a
#: real collision or invent one. The caller reports the ambiguity instead.
#:
#: Claude Code: "When the same server is defined in more than one place, Claude
#: Code connects to it once, using the definition from the highest-precedence
#: source. The entire server entry from that source is used; fields are not
#: merged across scopes." Order: Local > Project > User.
SCOPE_PRECEDENCE: dict[str, tuple[str, ...]] = {
    "Claude Code": ("local", "project", "user"),
}


def resolve_scopes(
    servers: list[ServerConfig],
) -> tuple[list[ServerConfig], list[tuple[ServerConfig, ServerConfig]]]:
    """Drop servers shadowed by a higher-precedence scope of the same client.

    Returns ``(kept, shadowed)`` where ``shadowed`` pairs each dropped server with
    the one that wins. Two entries at the *same* scope are not shadowing — that
    is a genuine duplicate and stays in the list, so it can still be reported.
    """
    groups: dict[tuple[str, str], list[ServerConfig]] = {}
    for server in servers:
        groups.setdefault((server.client, server.name), []).append(server)

    dropped: set[int] = set()
    shadowed: list[tuple[ServerConfig, ServerConfig]] = []

    for (client, _name), group in groups.items():
        order = SCOPE_PRECEDENCE.get(client)
        if not order or len(group) < 2:
            continue
        ranked = [server for server in group if server.scope in order]
        if len(ranked) < 2:
            continue
        ranked.sort(key=lambda server: order.index(server.scope))
        winner = ranked[0]
        winner_rank = order.index(winner.scope)
        for loser in ranked[1:]:
            if order.index(loser.scope) > winner_rank:
                dropped.add(id(loser))
                shadowed.append((loser, winner))

    kept = [server for server in servers if id(server) not in dropped]
    return kept, shadowed


def load_servers(
    path: Path,
    label: str = "",
    *,
    client: str | None = None,
    scope: str = "",
    cwd: Path | None = None,
) -> list[ServerConfig]:
    """Read servers from one config, whatever format it is in.

    ``client`` and ``scope`` are passed in by discovery, which knows both. A
    caller that only has a path gets ``client=label`` and an empty scope, which
    is the pre-scope behaviour: no precedence is assumed for it.
    """
    label = label or path.name
    client = label if client is None else client
    if path.suffix.lower() == ".toml":
        return _load_toml(path, label, client, scope)
    return _load_json(path, label, client, scope, cwd)

