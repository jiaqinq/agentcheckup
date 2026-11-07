"""Load tool manifests from a file or from a live stdio server."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .models import ServerConfig, Tool

PROTOCOL_VERSION = "2025-06-18"


class LoadError(RuntimeError):
    """Raised when a manifest cannot be read or parsed."""


def tools_from_payload(payload: Any) -> list[Tool]:
    """Accept every shape people actually have lying around.

    Supported: ``{"tools": [...]}``, a bare list, a JSON-RPC envelope
    ``{"result": {"tools": [...]}}``, or a full session log with ``messages``.
    """
    if isinstance(payload, list):
        return [Tool.from_raw(item) for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("tools",):
            value = payload.get(key)
            if isinstance(value, list):
                return [Tool.from_raw(item) for item in value if isinstance(item, dict)]

        result = payload.get("result")
        if isinstance(result, dict) and isinstance(result.get("tools"), list):
            return [Tool.from_raw(item) for item in result["tools"] if isinstance(item, dict)]

        messages = payload.get("messages")
        if isinstance(messages, list):
            collected: list[Tool] = []
            for msg in messages:
                if isinstance(msg, dict):
                    collected.extend(tools_from_payload(msg))
            return collected

    raise LoadError(
        "Could not find a tools array. Expected {'tools': [...]}, a JSON-RPC "
        "'result.tools', or a bare list."
    )


def load_from_file(path: str | Path) -> list[Tool]:
    file = Path(path)
    if not file.exists():
        raise LoadError(f"No such file: {file}")
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LoadError(f"{file} is not valid JSON: {exc}") from exc
    return tools_from_payload(payload)


def servers_from_config(path: str | Path) -> list[ServerConfig]:
    """Read a client config (Claude Desktop, Cursor, VS Code, Cline)."""
    file = Path(path)
    if not file.exists():
        raise LoadError(f"No such file: {file}")
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LoadError(f"{file} is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise LoadError(f"{file} does not contain a JSON object.")

    blocks: list[tuple[str, dict]] = []
    for key in ("mcpServers", "servers", "mcp_servers"):
        value = payload.get(key)
        if isinstance(value, dict):
            blocks.append((key, value))

    if not blocks:
        raise LoadError(
            f"{file} has no server block. Expected one of: mcpServers, servers, mcp_servers."
        )

    servers: list[ServerConfig] = []
    for key, block in blocks:
        for name, entry in block.items():
            if isinstance(entry, dict):
                servers.append(ServerConfig.from_raw(name, entry, source=f"{file}:{key}"))
    return servers


class StdioSession:
    """Minimal MCP stdio client: initialize -> tools/list -> close.

    Newline-delimited JSON-RPC, per the MCP stdio transport. No SDK dependency,
    so this keeps working when the SDK's API moves.
    """

    def __init__(
        self,
        command: str | list[str],
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> None:
        """``command`` may be a shell string or an argv list.

        Prefer the list form: it sidesteps quoting entirely, which matters on
        Windows where ``shell=True`` re-parses every argument through cmd.exe.
        """
        self.command = command
        self.timeout = timeout
        self.env = env
        self._label = command if isinstance(command, str) else " ".join(command)

    def __enter__(self) -> StdioSession:
        creationflags = 0
        if sys.platform == "win32":  # keep a stray console from flashing up
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        child_env = None
        if self.env:
            child_env = {**os.environ, **self.env}

        try:
            self.proc = subprocess.Popen(
                self.command,
                shell=isinstance(self.command, str),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
                env=child_env,
            )
        except OSError as exc:
            raise LoadError(f"Could not start {self._label!r}: {exc}") from exc
        return self

    def __exit__(self, *exc_info) -> None:
        proc = getattr(self, "proc", None)
        if proc is None:
            return
        with contextlib.suppress(OSError, ValueError):
            if proc.stdin:
                proc.stdin.close()
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 - teardown must never mask the real error
            with contextlib.suppress(Exception):
                proc.kill()

    def _send(self, message: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def _read_until(self, msg_id: int) -> dict[str, Any]:
        assert self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                stderr = ""
                if self.proc.stderr:
                    try:
                        stderr = self.proc.stderr.read()[:800]
                    except Exception:  # noqa: BLE001
                        stderr = ""
                raise LoadError(
                    f"Server exited before replying to id={msg_id}. stderr: {stderr.strip() or '(empty)'}"
                )
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # servers do log to stdout sometimes
            if isinstance(message, dict) and message.get("id") == msg_id:
                if "error" in message:
                    raise LoadError(f"Server returned an error: {message['error']}")
                return message

    def list_tools(self) -> list[Tool]:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "agentcheckup", "version": "0.1.0"},
                },
            }
        )
        self._read_until(1)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        reply = self._read_until(2)
        result = reply.get("result") or {}
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise LoadError("Server replied to tools/list without a tools array.")
        return [Tool.from_raw(item) for item in tools if isinstance(item, dict)]
