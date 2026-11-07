from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentcheckup.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_scan_good_manifest_exits_zero(capsys):
    code = main(["scan", str(FIXTURES / "good_tools.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "Grade A" in out


def test_scan_bad_manifest_exits_one(capsys):
    code = main(["scan", str(FIXTURES / "bad_tools.json")])
    assert code == 1


def test_fail_on_never_always_exits_zero():
    assert main(["scan", str(FIXTURES / "bad_tools.json"), "--fail-on", "never"]) == 0


def test_fail_on_info_catches_infos(capsys):
    assert main(["scan", str(FIXTURES / "bad_tools.json"), "--fail-on", "info"]) == 1


def test_min_score_gate(capsys):
    assert main(["scan", str(FIXTURES / "bad_tools.json"), "--fail-on", "never", "--min-score", "90"]) == 1
    assert main(["scan", str(FIXTURES / "good_tools.json"), "--min-score", "90"]) == 0


def test_json_output_is_parseable(capsys):
    main(["scan", str(FIXTURES / "bad_tools.json"), "--format", "json", "--fail-on", "never"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool_count"] == 7


def test_sarif_output_is_parseable(capsys):
    main(["scan", str(FIXTURES / "bad_tools.json"), "--format", "sarif", "--fail-on", "never"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["runs"][0]["tool"]["driver"]["name"] == "agentcheckup"


def test_config_subcommand(capsys):
    code = main(["config", str(FIXTURES / "claude_desktop_config.json")])
    assert code == 1


def test_rules_subcommand_lists_ids(capsys):
    assert main(["rules"]) == 0
    out = capsys.readouterr().out
    assert "AGT040" in out
    assert "AGT104" in out


def test_missing_file_exits_two(capsys):
    code = main(["scan", str(FIXTURES / "nope.json")])
    err = capsys.readouterr().err
    assert code == 2
    assert "agentcheckup:" in err


def test_scan_requires_exactly_one_source():
    with pytest.raises(SystemExit) as exc:
        main(["scan"])
    assert exc.value.code == 2


def test_json_out_and_sarif_out_are_written(capsys, tmp_path):
    json_out = tmp_path / "report.json"
    sarif_out = tmp_path / "report.sarif"
    code = main(
        [
            "scan",
            str(FIXTURES / "bad_tools.json"),
            "--fail-on",
            "never",
            "--json-out",
            str(json_out),
            "--sarif-out",
            str(sarif_out),
        ]
    )
    assert code == 0
    assert json.loads(json_out.read_text(encoding="utf-8"))["grade"] == "F"
    assert json.loads(sarif_out.read_text(encoding="utf-8"))["version"] == "2.1.0"
    # The human view still prints; side outputs are additive, not a replacement.
    assert "Grade F" in capsys.readouterr().out


def test_side_outputs_are_written_even_when_the_gate_fails(tmp_path):
    json_out = tmp_path / "report.json"
    code = main(["scan", str(FIXTURES / "bad_tools.json"), "--json-out", str(json_out)])
    assert code == 1
    assert json_out.is_file()


# --------------------------------------------------------------------------- #
# --dry-run and coverage
# --------------------------------------------------------------------------- #


def _write_config(tmp_path: Path, servers: dict) -> Path:
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    return path


def test_dry_run_does_not_start_anything(tmp_path, capsys):
    marker = tmp_path / "SHOULD_NOT_EXIST"
    cfg = _write_config(
        tmp_path,
        {
            "marker": {
                "command": "python",
                "args": ["-c", f"open(r'{marker}','w').write('x')"],
            }
        },
    )

    code = main(["audit", "--no-discover", "--config", str(cfg), "--dry-run"])

    assert code == 0
    assert not marker.exists(), "dry-run started a process"
    assert "Nothing was executed" in capsys.readouterr().out


def test_dry_run_redacts_credentials_but_keeps_the_flag(tmp_path, capsys):
    cfg = _write_config(
        tmp_path,
        {
            "gh": {
                "command": "npx",
                "args": ["-y", "server", "--api-key", "sk-abcdefghijklmnopqrstuvwxyz123456"],
            }
        },
    )

    main(["audit", "--no-discover", "--config", str(cfg), "--dry-run"])
    out = capsys.readouterr().out

    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in out
    assert "--api-key" in out
    assert "<redacted>" in out


def test_coverage_counts_servers_that_never_answered():
    from agentcheckup.engine import lint_audit
    from agentcheckup.models import ServerConfig

    servers = [
        ServerConfig(name="a", command="x"),
        ServerConfig(name="b", command="y"),
        ServerConfig(name="c", command="z"),
    ]
    report = lint_audit(servers, tools_by_server={"a": []}, failures={})

    assert report.server_count == 3
    assert report.servers_inspected == 1
    assert report.servers_unverified == 2
    assert report.coverage == pytest.approx(1 / 3)


def test_coverage_appears_in_text_and_json(tmp_path, capsys):
    from agentcheckup.engine import lint_audit
    from agentcheckup.models import ServerConfig
    from agentcheckup.report import render_json, render_text

    servers = [ServerConfig(name="a", command="x"), ServerConfig(name="b", command="y")]
    report = lint_audit(servers, tools_by_server={"a": []}, failures={})

    assert "1/2 server(s) inspected" in render_text(report)
    payload = json.loads(render_json(report))
    assert payload["servers_unverified"] == 1
    assert payload["coverage"] == 0.5
