"""The `--timeout` flag has to actually stop the clock.

The first implementation stored `self.timeout` and never read it: `_read_until`
called `self.proc.stdout.readline()`, which blocks forever on a server that
accepts the pipe but never answers. `--timeout 5` did nothing.

Every test here runs the mock server in `tests/fixtures/mock_mcp.py`. No real MCP
server, no real config, no network.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from agentcheckup.loader import LoadError, StdioSession

MOCK = Path(__file__).resolve().parent / "fixtures" / "mock_mcp.py"
PY = sys.executable


def run(mode: str, timeout: float = 2.0, **kwargs) -> list:
    with StdioSession([PY, str(MOCK), "--mode", mode], timeout=timeout, **kwargs) as session:
        return session.list_tools()


# --------------------------------------------------------------------------- #
# The happy path still works
# --------------------------------------------------------------------------- #


def test_normal_server_returns_tools():
    tools = run("ok")
    assert {t.name for t in tools} == {"read_file", "write_file"}


# --------------------------------------------------------------------------- #
# Every stall must be bounded by the timeout
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", ["hang-start", "hang-init", "hang-list", "partial-json"])
def test_a_stalled_server_times_out(mode):
    """hang-start never reads; hang-init never answers initialize; hang-list
    never answers tools/list; partial-json writes half a line and stops.

    All four previously hung until the process was killed by hand.
    """
    started = time.monotonic()
    with pytest.raises(LoadError) as excinfo:
        run(mode, timeout=1.5)
    elapsed = time.monotonic() - started

    assert elapsed < 8, f"{mode} took {elapsed:.1f}s despite a 1.5s timeout"
    assert "timed out" in str(excinfo.value).lower()


def test_timeout_is_not_reported_as_an_empty_tool_list():
    """A timeout is a failure, not 'this server has no tools'."""
    with pytest.raises(LoadError):
        run("hang-list", timeout=1.0)


def test_a_server_that_exits_immediately_is_an_error_not_a_crash():
    with pytest.raises(LoadError) as excinfo:
        run("exit-immediately", timeout=2.0)
    assert "exited" in str(excinfo.value).lower()


def test_a_server_that_exits_mid_list_is_an_error():
    with pytest.raises(LoadError):
        run("exit-mid-list", timeout=2.0)


def test_timeout_cleans_up_the_child_process():
    """No orphans: the handle must be gone once the context manager unwinds."""
    session = StdioSession([PY, str(MOCK), "--mode", "hang-list"], timeout=1.0)
    with pytest.raises(LoadError), session:
        session.list_tools()
    assert session.proc.poll() is not None, "child process survived a timeout"


def test_one_stalled_server_does_not_block_the_next():
    """A dead server must not consume the budget of the following one."""
    with pytest.raises(LoadError):
        run("hang-list", timeout=1.0)
    assert {t.name for t in run("ok", timeout=5.0)} == {"read_file", "write_file"}


# --------------------------------------------------------------------------- #
# Pagination
# --------------------------------------------------------------------------- #


def test_single_page_has_no_cursor():
    assert len(run("ok")) == 2


def test_multiple_pages_are_merged():
    tools = run("paginated")
    assert {t.name for t in tools} == {"page0_tool", "page1_tool", "page2_tool"}


def test_empty_page_with_a_cursor_continues():
    tools = run("empty-page-then-more")
    assert {t.name for t in tools} == {"after_empty"}


def test_repeated_cursor_does_not_loop_forever():
    started = time.monotonic()
    with pytest.raises(LoadError) as excinfo:
        run("repeat-cursor", timeout=5.0)
    assert time.monotonic() - started < 10
    assert "cursor" in str(excinfo.value).lower()


def test_pagination_respects_the_timeout():
    started = time.monotonic()
    with pytest.raises(LoadError):
        run("hang-list", timeout=1.0)
    assert time.monotonic() - started < 8


# --------------------------------------------------------------------------- #
# Partial listings must be reported as partial
# --------------------------------------------------------------------------- #


def test_tool_cap_sets_partial_reason():
    with StdioSession([PY, str(MOCK), "--mode", "huge"], timeout=20.0, max_tools=10) as session:
        tools = session.list_tools()
        assert len(tools) == 10
        assert session.partial_reason and "10 tools" in session.partial_reason


def test_page_cap_sets_partial_reason():
    with StdioSession(
        [PY, str(MOCK), "--mode", "paginated", "--pages", "10"],
        timeout=20.0,
        max_pages=2,
    ) as session:
        session.list_tools()
        assert session.partial_reason and "2 pages" in session.partial_reason


def test_complete_listing_has_no_partial_reason():
    with StdioSession([PY, str(MOCK), "--mode", "ok"], timeout=10.0) as session:
        session.list_tools()
        assert session.partial_reason is None


def test_partial_is_surfaced_in_the_report():
    from agentcheckup.engine import lint_audit
    from agentcheckup.models import ServerConfig
    from agentcheckup.report import render_text

    servers = [ServerConfig(name="a", command="x"), ServerConfig(name="b", command="y")]
    report = lint_audit(
        servers,
        {"a": []},
        failures={},
        partial={"a": "stopped after 2 pages"},
    )

    assert report.servers_partial == 1
    assert "1 partial" in render_text(report)
    assert any("partial tool list" in f.message for f in report.findings)
