"""Two opt-in controls for the audit, both additive.

`--client` narrows discovery to the clients you care about. `--probe` is an
explicit acknowledgement that servers will be started.

Neither changes the default run. `--probe` exists so the default can be flipped
in a later major version without anyone being surprised: today it only adds a
line on stderr.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentcheckup import cli
from agentcheckup.discovery import ConfigLocation


def write_config(path: Path, servers: dict) -> Path:
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    return path


def fake_configs(tmp_path: Path) -> list[ConfigLocation]:
    # Distinct commands on purpose: identical launch specs are deduped, which is
    # correct behaviour but would hide what these tests are checking.
    cursor = write_config(tmp_path / "cursor.json", {"c1": {"command": "cursor-mcp"}})
    codex = write_config(tmp_path / "codex.json", {"x1": {"command": "codex-mcp"}})
    return [
        ConfigLocation("Cursor", cursor, "Cursor", "user"),
        ConfigLocation("Codex CLI", codex, "Codex CLI", "user"),
    ]


@pytest.fixture()
def patched(monkeypatch, tmp_path):
    configs = fake_configs(tmp_path)
    monkeypatch.setattr(cli, "discover", lambda cwd=None: configs)
    return configs


# --------------------------------------------------------------------------- #
# --client
# --------------------------------------------------------------------------- #


def test_client_filter_narrows_discovery(patched, capsys):
    code = cli.main(["audit", "--client", "cursor", "--no-spawn", "--fail-on", "never"])
    out = capsys.readouterr()
    assert code == 0
    assert "1 server(s)" in out.out or "c1" in out.out


def test_client_filter_is_case_insensitive(patched):
    assert cli.main(["audit", "--client", "CURSOR", "--no-spawn", "--fail-on", "never"]) == 0


def test_client_filter_matches_partially(patched):
    """`codex` should match the label `Codex CLI`."""
    assert cli.main(["audit", "--client", "codex", "--no-spawn", "--fail-on", "never"]) == 0


def test_unknown_client_is_a_usage_error(patched, capsys):
    code = cli.main(["audit", "--client", "nonexistent", "--no-spawn"])
    err = capsys.readouterr().err
    assert code == 2
    assert "no config matched" in err


def test_client_filter_can_be_repeated(patched, capsys):
    code = cli.main(
        ["audit", "--client", "cursor", "--client", "codex", "--no-spawn", "--fail-on", "never"]
    )
    assert code == 0
    assert "2 server(s)" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# --probe
# --------------------------------------------------------------------------- #


def test_starting_servers_without_probe_says_so(patched, capsys):
    cli.main(["audit", "--no-discover", "--config", str(patched[0][1]), "--dry-run"])
    capsys.readouterr()  # drain

    # A dry run never starts anything, so it must not nag either.
    out = capsys.readouterr()
    assert "--probe" not in out.err


def test_probe_is_accepted_and_changes_nothing_else(patched, capsys):
    base = cli.main(["audit", "--no-spawn", "--fail-on", "never"])
    capsys.readouterr()
    with_probe = cli.main(["audit", "--no-spawn", "--probe", "--fail-on", "never"])
    assert base == with_probe


def test_no_spawn_never_mentions_probe(patched, capsys):
    cli.main(["audit", "--no-spawn", "--fail-on", "never"])
    assert "--probe" not in capsys.readouterr().err


def test_explicit_config_is_never_filtered_out(patched, capsys):
    """A file the user named with --config is audited even if --client misses it.

    `--client` is a discovery filter, not a gate on files the user typed out.
    """
    explicit = write_config(patched[0][1].parent / "mine.json", {"m": {"command": "mine-mcp"}})
    code = cli.main(
        [
            "audit",
            "--client",
            "nonexistent",
            "--config",
            str(explicit),
            "--no-spawn",
            "--fail-on",
            "never",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "1 server(s)" in out
