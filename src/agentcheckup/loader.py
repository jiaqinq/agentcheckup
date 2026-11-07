"""Load tool manifests from a file or from a live stdio server."""

from __future__ import annotations

import collections
import contextlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
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
    """Minimal MCP stdio client: initialize -> tools/list (paged) -> close.

    Newline-delimited JSON-RPC, per the MCP stdio transport. No SDK dependency,
    so this keeps working when the SDK's API moves.

    Reads happen on a background thread and land in a queue, because
    ``stdout.readline()`` blocks forever on a server that holds the pipe open and
    never answers. With a queue, ``timeout`` is a real deadline instead of a
    stored number nobody reads.
    """

    def __init__(
        self,
        command: str | list[str],
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
        max_pages: int = 50,
        max_tools: int = 10_000,
    ) -> None:
        """``command`` may be a shell string or an argv list.

        Prefer the list form: it sidesteps quoting entirely, which matters on
        Windows where ``shell=True`` re-parses every argument through cmd.exe.
        """
        self.command = command
        self.timeout = timeout
        self.env = env
        self.max_pages = max_pages
        self.max_tools = max_tools
        self._label = command if isinstance(command, str) else " ".join(command)

        #: Set when a page or tool cap stopped the listing early. A partial list
        #: must not be reported as a complete one.
        self.partial_reason: str | None = None
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stderr: collections.deque[str] = collections.deque(maxlen=40)
        self._eof = False

    # -- process lifecycle -------------------------------------------------- #

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

        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()
        return self

    def _pump_stdout(self) -> None:
        stream = self.proc.stdout
        try:
            for line in stream:
                self._queue.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._queue.put(None)  # EOF sentinel

    def _pump_stderr(self) -> None:
        stream = self.proc.stderr
        try:
            for line in stream:
                self._stderr.append(line.rstrip())
        except (OSError, ValueError):
            pass

    def __exit__(self, *exc_info) -> None:
        proc = getattr(self, "proc", None)
        if proc is None:
            return
        with contextlib.suppress(OSError, ValueError):
            if proc.stdin:
                proc.stdin.close()
        try:
            proc.terminate()
            proc.wait(timeout=1.5)
        except Exception:  # noqa: BLE001 - teardown must never mask the real error
            with contextlib.suppress(Exception):
                proc.kill()
                proc.wait(timeout=1.5)

    # -- protocol ----------------------------------------------------------- #

    def _send(self, message: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise LoadError(f"Server closed its stdin: {exc}") from exc

    def _stderr_tail(self) -> str:
        tail = " | ".join(self._stderr)[-800:]
        return tail.strip() or "(empty)"

    def _read_until(self, msg_id: int, deadline: float) -> dict[str, Any]:
        """Read messages until one matches ``msg_id``, or the deadline passes."""
        while True:
            if self._eof:
                raise LoadError(
                    f"Server exited before replying to id={msg_id}. "
                    f"stderr: {self._stderr_tail()}"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LoadError(
                    f"Server timed out after {self.timeout:g}s waiting for "
                    f"id={msg_id}. stderr: {self._stderr_tail()}"
                )
            try:
                line = self._queue.get(timeout=remaining)
            except queue.Empty:
                raise LoadError(
                    f"Server timed out after {self.timeout:g}s waiting for "
                    f"id={msg_id}. stderr: {self._stderr_tail()}"
                ) from None

            if line is None:
                self._eof = True
                continue
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
        """initialize, then page through tools/list until nextCursor runs out.

        One deadline covers the whole exchange: a server cannot buy itself extra
        time by answering every request slowly.
        """
        self.partial_reason = None
        deadline = time.monotonic() + self.timeout

        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "agentcheckup", "version": _client_version()},
                },
            }
        )
        self._read_until(1, deadline)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        tools: list[Tool] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        msg_id = 2

        while True:
            params: dict[str, Any] = {"cursor": cursor} if cursor else {}
            self._send(
                {"jsonrpc": "2.0", "id": msg_id, "method": "tools/list", "params": params}
            )
            reply = self._read_until(msg_id, deadline)
            result = reply.get("result") or {}
            page = result.get("tools") if isinstance(result, dict) else None
            if not isinstance(page, list):
                raise LoadError("Server replied to tools/list without a tools array.")

            tools.extend(Tool.from_raw(item) for item in page if isinstance(item, dict))

            if len(tools) > self.max_tools:
                tools = tools[: self.max_tools]
                self.partial_reason = f"stopped after {self.max_tools} tools"
                break

            cursor = result.get("nextCursor")
            if not cursor:
                break
            if cursor in seen_cursors:
                raise LoadError(
                    f"Server repeated cursor {cursor!r}; pagination would never end."
                )
            seen_cursors.add(cursor)

            if len(seen_cursors) >= self.max_pages:
                self.partial_reason = f"stopped after {self.max_pages} pages"
                break
            msg_id += 1

        return tools


def _client_version() -> str:
    from .report import __version__

    return __version__
