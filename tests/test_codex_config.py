"""Codex's config shape, verified against a real file (copied, never modified).

Three things the real file had that the loader did not understand:

- ``env_vars``: a list of environment variable **names** to inherit from the
  parent process. Not a table of values, and disjoint from ``env``. Ignoring it
  meant a server that needs a key from the environment started without it.
- ``startup_timeout_sec``: a per-server deadline the client itself respects.
- ``env``: already supported, and still wins over passthrough.

The fixture is the real *structure* with fake values; no real path, key or token
is stored in the repository.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agentcheckup import cli
from agentcheckup.models import ServerConfig

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "codex_config.toml"


def load() -> dict[str, ServerConfig]:
    servers = cli.load_servers(FIXTURE, "Codex CLI")
    return {server.name: server for server in servers}


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_all_servers_are_parsed():
    assert set(load()) == {"files", "slow", "plain"}


def test_env_vars_is_a_name_list_not_a_value_table():
    files = load()["files"]
    assert files.env_passthrough == ["FILES_API_KEY", "FILES_REGION"]
    assert files.env == {"FILES_MODE": "readonly"}


def test_startup_timeout_is_read():
    assert load()["files"].startup_timeout == 90.0


def test_missing_startup_timeout_is_none():
    assert load()["plain"].startup_timeout is None


def test_env_vars_absent_is_an_empty_list():
    assert load()["plain"].env_passthrough == []


def test_client_label_is_recorded():
    assert {server.client for server in load().values()} == {"Codex CLI"}


# --------------------------------------------------------------------------- #
# Passthrough resolution
# --------------------------------------------------------------------------- #


def test_passthrough_reads_from_the_parent_environment(monkeypatch):
    monkeypatch.setenv("FILES_API_KEY", "value-from-parent")
    monkeypatch.setenv("FILES_REGION", "eu-west-1")

    env = cli._child_env(load()["files"])

    assert env["FILES_API_KEY"] == "value-from-parent"
    assert env["FILES_REGION"] == "eu-west-1"


def test_explicit_env_wins_over_passthrough(monkeypatch):
    monkeypatch.setenv("FILES_MODE", "from-parent")
    env = cli._child_env(load()["files"])
    assert env["FILES_MODE"] == "readonly"


def test_missing_passthrough_names_are_skipped(monkeypatch):
    monkeypatch.delenv("DEFINITELY_NOT_SET_IN_PARENT", raising=False)
    env = cli._child_env(load()["slow"])
    assert env is None, "a server with nothing to pass should get no env override"


def test_no_env_at_all_returns_none():
    assert cli._child_env(load()["plain"]) is None


# --------------------------------------------------------------------------- #
# Per-server timeout
# --------------------------------------------------------------------------- #


def namespace(timeout=None) -> argparse.Namespace:
    return argparse.Namespace(timeout=timeout)


def test_explicit_timeout_wins():
    assert cli._server_timeout(namespace(5.0), load()["files"]) == 5.0


def test_startup_timeout_is_used_when_no_flag_given():
    assert cli._server_timeout(namespace(), load()["files"]) == 90.0


def test_default_applies_when_neither_is_set():
    assert cli._server_timeout(namespace(), load()["plain"]) == cli.DEFAULT_TIMEOUT


# --------------------------------------------------------------------------- #
# Secrets must never reach the report
# --------------------------------------------------------------------------- #


def test_passthrough_values_do_not_appear_in_the_dry_run(tmp_path, capsys, monkeypatch):
    """The dry run prints names, never values."""
    monkeypatch.setenv("FILES_API_KEY", "sk-should-never-be-printed-000000")

    code = cli.main(
        ["audit", "--no-discover", "--config", str(FIXTURE), "--dry-run", "--client", "codex"]
    )
    out = capsys.readouterr()

    assert code == 0
    assert "sk-should-never-be-printed-000000" not in out.out
    assert "sk-should-never-be-printed-000000" not in out.err


@pytest.mark.parametrize("field", ["env_passthrough", "startup_timeout"])
def test_new_fields_have_safe_defaults(field):
    plain = ServerConfig(name="x", command="y")
    value = getattr(plain, field)
    assert value == ([] if field == "env_passthrough" else None)
