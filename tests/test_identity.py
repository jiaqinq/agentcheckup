"""Two servers that merely share a name are not the same server.

Two defects were confirmed here:

1. `_dedupe` keyed identity on ``(command, args, url)`` and ignored ``env``. Two
   entries with the same command pointed at different backends by environment
   were merged, and one of them silently disappeared from the audit.

2. ``tools_by_server`` was keyed by the bare server name. When two configs each
   declared a server called ``filesystem``, the second assignment overwrote the
   first: its tools vanished, and no conflict between the two could be found.

Both fail silently, which is the worst kind: the report looks complete.
"""

from __future__ import annotations

from agentcheckup.engine import lint_audit
from agentcheckup.models import ServerConfig, Tool


def make_tool(name: str) -> Tool:
    return Tool.from_raw(
        {
            "name": name,
            "description": "Do a thing with a path and return text.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string", "pattern": "^.*$"}},
                "additionalProperties": False,
            },
        }
    )


# --------------------------------------------------------------------------- #
# Dedupe must look at env
# --------------------------------------------------------------------------- #


def test_servers_differing_only_by_env_are_both_kept():
    from agentcheckup.cli import _dedupe

    a = ServerConfig(name="db", command="db-mcp", env={"DB_URL": "postgres://one"})
    b = ServerConfig(name="db", command="db-mcp", env={"DB_URL": "postgres://two"})

    kept = _dedupe([a, b])
    assert len(kept) == 2, "servers with different env were merged"


def test_identical_servers_are_still_merged():
    from agentcheckup.cli import _dedupe

    a = ServerConfig(name="files", command="files-mcp", env={"ROOT": "/tmp"})
    b = ServerConfig(name="files", command="files-mcp", env={"ROOT": "/tmp"})

    assert len(_dedupe([a, b])) == 1


def test_env_order_does_not_affect_identity():
    from agentcheckup.cli import _dedupe

    a = ServerConfig(name="x", command="c", env={"A": "1", "B": "2"})
    b = ServerConfig(name="x", command="c", env={"B": "2", "A": "1"})

    assert len(_dedupe([a, b])) == 1


# --------------------------------------------------------------------------- #
# Two instances with the same name must not overwrite each other
# --------------------------------------------------------------------------- #


def test_instances_with_the_same_name_get_distinct_keys():
    from agentcheckup.cli import _assign_instances

    servers = [
        ServerConfig(name="filesystem", command="a", source="Cursor:cfg.json"),
        ServerConfig(name="filesystem", command="b", source="Codex:cfg.json"),
    ]
    _assign_instances(servers)

    keys = [s.key for s in servers]
    assert len(set(keys)) == 2, f"keys collided: {keys}"


def test_a_unique_name_keeps_its_plain_key():
    from agentcheckup.cli import _assign_instances

    servers = [ServerConfig(name="filesystem", command="a")]
    _assign_instances(servers)

    assert servers[0].key == "filesystem"


def test_tools_from_two_same_named_instances_both_survive():
    """The overwrite bug: the second server's tools used to replace the first's."""
    from agentcheckup.cli import _assign_instances

    servers = [
        ServerConfig(name="filesystem", command="a", source="Cursor:cfg.json"),
        ServerConfig(name="filesystem", command="b", source="Codex:cfg.json"),
    ]
    _assign_instances(servers)

    tools_by_server = {
        servers[0].key: [make_tool("read_file")],
        servers[1].key: [make_tool("read_file")],
    }

    report = lint_audit(servers, tools_by_server, failures={})

    assert report.tool_count == 2, "one server's tools were dropped"
    conflicts = [f for f in report.findings if f.rule == "AGT201"]
    assert conflicts, "the collision between the two instances was not reported"


def test_coverage_counts_instances_not_names():
    from agentcheckup.cli import _assign_instances

    servers = [
        ServerConfig(name="filesystem", command="a", source="A"),
        ServerConfig(name="filesystem", command="b", source="B"),
    ]
    _assign_instances(servers)

    report = lint_audit(servers, {servers[0].key: []}, failures={})
    assert report.servers_inspected == 1
    assert report.servers_unverified == 1


# --------------------------------------------------------------------------- #
# A skipped config must be announced, not swallowed
# --------------------------------------------------------------------------- #


def test_missing_tomllib_is_recorded_not_silent(monkeypatch, tmp_path):
    import sys

    from agentcheckup import discovery

    discovery.take_toml_skips()
    cfg = tmp_path / "config.toml"
    cfg.write_text("[mcp_servers.x]\ncommand = 'y'\n", encoding="utf-8")

    # Simulate Python 3.10, where tomllib does not exist.
    monkeypatch.setitem(sys.modules, "tomllib", None)
    servers = discovery._load_toml(cfg, "Codex")

    assert servers == []
    skips = discovery.take_toml_skips()
    assert skips and "3.11" in skips[0]
