"""Load tool manifests from a remote MCP server over Streamable HTTP.

This mirrors :class:`agentcheckup.loader.StdioSession` but talks to a URL instead
of a subprocess. No SDK, no ``requests`` — just :mod:`urllib`, because the
package's whole point is having zero runtime dependencies.

The transport here is the one the spec actually shipped: POST a JSON-RPC message,
read either a JSON body or an ``text/event-stream`` body back, and echo the
``Mcp-Session-Id`` header the server hands us after ``initialize``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .loader import PROTOCOL_VERSION, LoadError
from .models import Tool


def _client_version() -> str:
    from .report import __version__

    return __version__


class HttpSession:
    """Minimal MCP Streamable HTTP client: initialize -> tools/list -> close.

    One deadline covers the whole exchange, exactly like :class:`StdioSession`,
    so a server cannot buy itself extra time by answering every request slowly.
    """

    def __init__(
        self,
        url: str,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
        max_pages: int = 50,
        max_tools: int = 10_000,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.extra_headers = {str(k): str(v) for k, v in (headers or {}).items()}
        self.max_pages = max_pages
        self.max_tools = max_tools
        self.partial_reason: str | None = None
        self._session_id: str | None = None

    # -- context manager (mirrors StdioSession) ---------------------------- #

    def __enter__(self) -> HttpSession:
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    # -- transport --------------------------------------------------------- #

    def _post(
        self,
        method: str,
        params: dict[str, Any] | None,
        *,
        msg_id: int | None,
        deadline: float,
    ) -> dict[str, Any] | None:
        """Send one JSON-RPC request and return its reply (or None for a 202)."""
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if msg_id is not None:
            payload["id"] = msg_id
        if params is not None:
            payload["params"] = params

        request_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": f"agentcheckup/{_client_version()}",
        }
        request_headers.update(self.extra_headers)
        if self._session_id:
            request_headers["Mcp-Session-Id"] = self._session_id

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data, headers=request_headers, method="POST"
        )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LoadError(
                f"{method}: timed out after {self.timeout:g}s waiting for {self.url}"
            )
        try:
            resp = urllib.request.urlopen(req, timeout=remaining)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            if exc.code in (401, 403):
                raise LoadError(
                    f"{method}: HTTP {exc.code} — the remote server requires "
                    f"authentication (an API key or token)."
                ) from exc
            raise LoadError(f"{method}: HTTP {exc.code} {body}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError) or "timed out" in str(reason):
                raise LoadError(
                    f"{method}: timed out after {self.timeout:g}s waiting for {self.url}"
                ) from exc
            raise LoadError(
                f"{method}: could not reach {self.url}: {reason}"
            ) from exc
        except TimeoutError as exc:
            raise LoadError(
                f"{method}: timed out after {self.timeout:g}s waiting for {self.url}"
            ) from exc

        # Capture the session id the server created, so later calls belong to it.
        sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid

        status = resp.status
        if status in (202, 204):
            resp.close()
            return None

        ctype = resp.headers.get("Content-Type", "") or ""
        raw = resp.read()
        resp.close()
        if not raw.strip():
            # A notification acknowledgement is allowed to carry no body at all.
            return None

        if "text/event-stream" in ctype:
            reply = _parse_sse(raw, msg_id)
        else:
            try:
                reply = json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                snippet = raw.decode("utf-8", "replace")[:120]
                raise LoadError(
                    f"{method}: response was not JSON: {snippet!r}"
                ) from None

        if not isinstance(reply, dict):
            raise LoadError(f"{method}: response was not a JSON object.")
        if "error" in reply:
            raise LoadError(f"{method}: server returned an error: {reply['error']}")
        return reply

    def list_tools(self) -> list[Tool]:
        """initialize, then page through tools/list until nextCursor runs out."""
        self.partial_reason = None
        deadline = time.monotonic() + self.timeout

        self._post(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agentcheckup", "version": _client_version()},
            },
            msg_id=1,
            deadline=deadline,
        )
        # Notification: no reply expected, and a well-behaved server answers 202.
        self._post("notifications/initialized", None, msg_id=None, deadline=deadline)

        tools: list[Tool] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        msg_id = 2

        while True:
            params: dict[str, Any] = {"cursor": cursor} if cursor else {}
            reply = self._post("tools/list", params, msg_id=msg_id, deadline=deadline)
            if not isinstance(reply, dict):
                raise LoadError("Server replied to tools/list without a result.")
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


def _parse_sse(raw: bytes, want_id: int | None) -> dict[str, Any] | None:
    """Pull the JSON-RPC reply out of an ``text/event-stream`` body.

    Each event is a blank-line-delimited block of ``data:`` lines. We return the
    first object whose ``id`` matches (or the first object at all when we sent a
    notification and expect no id back).
    """
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    for block in text.split("\n\n"):
        data_parts: list[str] = []
        for line in block.splitlines():
            if line.startswith("data:"):
                data_parts.append(line[5:].lstrip())
        if not data_parts:
            continue
        try:
            obj = json.loads("\n".join(data_parts))
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if want_id is None:
            return obj
        if obj.get("id") == want_id:
            return obj
    return None
