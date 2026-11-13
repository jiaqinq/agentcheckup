"""Remote (Streamable HTTP) introspection, against a real local socket.

These use ``http.server`` rather than monkeypatching ``urlopen``: the bugs worth
catching here are in the wire format (SSE framing, session headers, pagination),
and a fake transport would not exercise them.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentcheckup.http import HttpSession
from agentcheckup.loader import LoadError
from agentcheckup.models import ServerConfig

TOOLS = [
    {"name": "read_file", "description": "Read a file from disk"},
    {"name": "search", "description": "Search the workspace"},
]


class _State:
    def __init__(
        self,
        mode: str = "json",
        pages: list[list[dict]] | None = None,
        require_auth: bool = False,
        delay: float = 0.0,
        error: dict | None = None,
        notification_status: int = 202,
    ) -> None:
        self.mode = mode
        self.pages = pages if pages is not None else [TOOLS]
        self.require_auth = require_auth
        self.delay = delay
        self.error = error
        self.notification_status = notification_status
        self.requests: list[tuple[str, dict, dict]] = []
        self.session_id = "sess-123"


def _handler(state: _State):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # keep pytest output clean
            pass

        def do_POST(self) -> None:  # noqa: N802 - http.server's spelling
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            state.requests.append((payload.get("method", ""), dict(self.headers), payload))

            if state.delay:
                time.sleep(state.delay)
            if state.require_auth and not self.headers.get("Authorization"):
                self._send(401, {"error": "unauthorized"})
                return

            method = payload.get("method")
            msg_id = payload.get("id")

            if method == "initialize":
                self._reply(
                    msg_id,
                    {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "mock"}},
                    session=True,
                )
            elif method == "notifications/initialized":
                self.send_response(state.notification_status)
                if state.notification_status != 204:
                    self.send_header("Content-Length", "0")
                self.end_headers()
            elif method == "tools/list":
                if state.error is not None:
                    self._reply(msg_id, None, error=state.error)
                    return
                cursor = (payload.get("params") or {}).get("cursor")
                index = int(cursor) if cursor else 0
                page = state.pages[index] if index < len(state.pages) else []
                result: dict = {"tools": page}
                if index + 1 < len(state.pages):
                    result["nextCursor"] = str(index + 1)
                self._reply(msg_id, result)
            else:
                self._reply(msg_id, {}, error={"code": -32601, "message": "unknown method"})

        def _reply(self, msg_id, result, *, session: bool = False, error=None) -> None:
            body: dict = {"jsonrpc": "2.0", "id": msg_id}
            if error is not None:
                body["error"] = error
            else:
                body["result"] = result
            headers = {"Mcp-Session-Id": state.session_id} if session else {}
            if state.mode == "garbage":
                self._send(200, b"this is not json", content_type="text/plain")
                return
            if state.mode == "sse":
                raw = ("event: message\ndata: " + json.dumps(body) + "\n\n").encode()
                self._send(200, raw, content_type="text/event-stream", headers=headers)
            else:
                self._send(200, json.dumps(body).encode(), content_type="application/json", headers=headers)

        def _send(self, status: int, body, *, content_type: str = "application/json", headers=None) -> None:
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)

    return Handler


@contextlib.contextmanager
def mock_server(**kwargs):
    state = _State(**kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/mcp", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_reads_tools_over_json() -> None:
    with mock_server() as (url, _state):
        tools = HttpSession(url, timeout=5).list_tools()

    assert [tool.name for tool in tools] == ["read_file", "search"]


def test_reads_tools_over_sse() -> None:
    with mock_server(mode="sse") as (url, _state):
        tools = HttpSession(url, timeout=5).list_tools()

    assert [tool.name for tool in tools] == ["read_file", "search"]


def test_follows_pagination() -> None:
    pages = [[TOOLS[0]], [TOOLS[1]]]
    with mock_server(pages=pages) as (url, state):
        tools = HttpSession(url, timeout=5).list_tools()

    assert [tool.name for tool in tools] == ["read_file", "search"]
    assert [method for method, _, _ in state.requests].count("tools/list") == 2


def _lower(headers: dict) -> dict:
    """Header names are case-insensitive; urllib re-cases them on the way out."""
    return {key.lower(): value for key, value in headers.items()}


def test_repeats_session_id_after_initialize() -> None:
    with mock_server() as (url, state):
        HttpSession(url, timeout=5).list_tools()

    by_method: dict[str, list[dict]] = {}
    for method, headers, _ in state.requests:
        by_method.setdefault(method, []).append(_lower(headers))

    assert "mcp-session-id" not in by_method["initialize"][0]
    assert by_method["notifications/initialized"][0]["mcp-session-id"] == "sess-123"
    assert by_method["tools/list"][0]["mcp-session-id"] == "sess-123"


def test_sends_extra_headers() -> None:
    with mock_server() as (url, state):
        HttpSession(url, timeout=5, headers={"Authorization": "Bearer test"}).list_tools()

    assert _lower(state.requests[0][1])["authorization"] == "Bearer test"


def test_auth_failure_is_reported_as_auth() -> None:
    with mock_server(require_auth=True) as (url, _state), pytest.raises(
        LoadError, match="requires authentication"
    ):
        HttpSession(url, timeout=5).list_tools()


def test_unreachable_url(monkeypatch) -> None:
    # No wire format to exercise here, and a closed port is proxy- and
    # firewall-dependent, so this one pins the error mapping directly.
    import urllib.error
    import urllib.request

    def boom(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(LoadError, match="could not reach"):
        HttpSession("http://127.0.0.1:9/mcp", timeout=1).list_tools()


def test_timeout_is_a_deadline() -> None:
    with mock_server(delay=1.0) as (url, _state), pytest.raises(LoadError, match="timed out"):
        HttpSession(url, timeout=0.2).list_tools()


def test_jsonrpc_error_is_raised() -> None:
    with mock_server(error={"code": -32603, "message": "boom"}) as (url, _state), pytest.raises(
        LoadError, match="server returned an error"
    ):
        HttpSession(url, timeout=5).list_tools()


def test_non_json_response_is_not_silently_empty() -> None:
    with mock_server(mode="garbage") as (url, _state), pytest.raises(
        LoadError, match="response was not JSON"
    ):
        HttpSession(url, timeout=5).list_tools()


@pytest.mark.parametrize("status", [202, 204, 200])
def test_notification_ack_may_carry_no_body(status: int) -> None:
    with mock_server(notification_status=status) as (url, _state):
        tools = HttpSession(url, timeout=5).list_tools()

    assert [tool.name for tool in tools] == ["read_file", "search"]


def test_max_tools_truncates_and_marks_partial() -> None:
    with mock_server() as (url, _state):
        session = HttpSession(url, timeout=5, max_tools=1)
        tools = session.list_tools()

    assert len(tools) == 1
    assert session.partial_reason == "stopped after 1 tools"


def test_server_config_parses_headers() -> None:
    server = ServerConfig.from_raw(
        "remote",
        {"url": "https://example.test/mcp", "headers": {"Authorization": "Bearer x"}},
    )

    assert server.headers == {"Authorization": "Bearer x"}


def test_introspect_reads_a_remote_server() -> None:
    from agentcheckup.cli import _introspect

    with mock_server() as (url, _state):
        server = ServerConfig(name="remote", url=url)
        tools, failure, partial = _introspect(server, timeout=5)

    assert failure is None
    assert partial is None
    assert [tool.name for tool in tools] == ["read_file", "search"]


def test_introspect_reports_a_remote_failure() -> None:
    from agentcheckup.cli import _introspect

    with mock_server(require_auth=True) as (url, _state):
        tools, failure, partial = _introspect(ServerConfig(name="remote", url=url), timeout=5)

    assert tools == []
    assert failure is not None and "requires authentication" in failure
    assert partial is None
