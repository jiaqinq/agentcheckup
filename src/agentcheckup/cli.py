"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from .discovery import ConfigLocation, discover, load_servers, resolve_scopes, take_toml_skips
from .engine import Report, lint_audit, lint_servers, lint_tools
from .loader import LoadError, StdioSession, load_from_file, servers_from_config
from .models import ServerConfig, Severity
from .report import __version__, render_json, render_rule_list, render_sarif, render_text

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2

THRESHOLDS = {
    "error": Severity.ERROR,
    "warning": Severity.WARNING,
    "info": Severity.INFO,
}


def _add_output_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("text", "json", "sarif"), default="text")
    parser.add_argument(
        "--fail-on",
        choices=("error", "warning", "info", "never"),
        default="error",
        help="Exit non-zero at or above this severity (default: error).",
    )
    parser.add_argument("--min-score", type=int, default=None, help="Also fail below this score.")
    parser.add_argument("--verbose", action="store_true", help="Show extra detail per finding.")
    parser.add_argument(
        "--baseline",
        metavar="PATH",
        default=None,
        help=(
            "Withhold findings already recorded in this file and fail only on new "
            "ones. Write it with --write-baseline."
        ),
    )
    parser.add_argument(
        "--write-baseline",
        metavar="PATH",
        default=None,
        help="Record the current findings to PATH so a later run can ignore them.",
    )
    parser.add_argument(
        "--json-out",
        metavar="PATH",
        default=None,
        help="Also write the JSON report here, whatever --format says.",
    )
    parser.add_argument(
        "--sarif-out",
        metavar="PATH",
        default=None,
        help="Also write a SARIF report here. One run, three outputs.",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentcheckup",
        description="Diagnose your agent setup: tool conflicts, risky config, context budget.",
    )
    parser.add_argument("--version", action="version", version=f"agentcheckup {__version__}")
    sub = parser.add_subparsers(dest="command")

    audit = sub.add_parser(
        "audit",
        help="Audit every MCP client config found on this machine (default command).",
    )
    audit.add_argument(
        "--config",
        action="append",
        default=[],
        metavar="PATH",
        help="Extra config file to include (repeatable).",
    )
    audit.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=(
            "Seconds to wait for each server's tools/list. Default: the server's "
            "own startup_timeout_sec if its config sets one, else 25."
        ),
    )
    audit.add_argument(
        "--no-spawn",
        action="store_true",
        help="Do not start servers; check configs only. Fast, but no conflict detection.",
    )
    audit.add_argument(
        "--no-discover",
        action="store_true",
        help="Do not auto-find configs; audit only the ones passed with --config.",
    )
    audit.add_argument(
        "--client",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "Only audit configs discovered for this client (repeatable, case-insensitive "
            "substring). e.g. --client cursor --client codex"
        ),
    )
    audit.add_argument(
        "--probe",
        action="store_true",
        help=(
            "Acknowledge that servers in your config will be started. Today the audit "
            "starts them either way and only says so; --no-spawn is the way to skip."
        ),
    )
    audit.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the commands that would be started, then exit. Nothing is "
            "executed. Implies --no-spawn."
        ),
    )
    _add_output_flags(audit)

    scan = sub.add_parser("scan", help="Lint one tools/list manifest (file or live server).")
    scan.add_argument("path", nargs="?", help="JSON file containing a tools array.")
    scan.add_argument("--cmd", dest="cmd", help="Spawn this stdio server and lint its live tools/list.")
    _add_output_flags(scan)

    cfg = sub.add_parser("config", help="Audit a single client config file.")
    cfg.add_argument("path", help="e.g. claude_desktop_config.json or .vscode/mcp.json")
    _add_output_flags(cfg)

    sub.add_parser("rules", help="List every rule with its id and severity.")
    return parser


def _emit(report: Report, args: argparse.Namespace) -> None:
    # Side outputs first: CI reads them even when the human view is what printed.
    if args.json_out:
        Path(args.json_out).write_text(render_json(report), encoding="utf-8")
    if args.sarif_out:
        Path(args.sarif_out).write_text(render_sarif(report), encoding="utf-8")

    if args.format == "json":
        print(render_json(report))
    elif args.format == "sarif":
        print(render_sarif(report))
    else:
        print(render_text(report, verbose=args.verbose))


DEFAULT_TIMEOUT = 25.0


def _child_env(server: ServerConfig) -> dict[str, str] | None:
    """Resolve Codex's ``env_vars`` allowlist against the current environment.

    ``env_vars`` is a list of *names* to inherit; the values live in the parent
    process. They are read at spawn time, passed to the child, and never stored,
    logged or rendered — the report only ever shows names.
    """
    resolved: dict[str, str] = {}
    for name in server.env_passthrough:
        value = os.environ.get(name)
        if value is not None:
            resolved[name] = value
    resolved.update(server.env)  # an explicit env entry wins over passthrough
    return resolved or None


def _server_timeout(args: argparse.Namespace, server: ServerConfig) -> float:
    """--timeout if given, else the server's own startup_timeout_sec, else 25."""
    if args.timeout is not None:
        return args.timeout
    return server.startup_timeout or DEFAULT_TIMEOUT


DEFAULT_TIMEOUT = 25.0


def _child_env(server: ServerConfig) -> dict[str, str] | None:
    """Resolve Codex's ``env_vars`` allowlist against the current environment.

    ``env_vars`` is a list of *names* to inherit; the values live in the parent
    process. They are read at spawn time, passed to the child, and never stored,
    logged or rendered — the report only ever shows names.
    """
    resolved: dict[str, str] = {}
    for name in server.env_passthrough:
        value = os.environ.get(name)
        if value is not None:
            resolved[name] = value
    resolved.update(server.env)  # an explicit env entry wins over passthrough
    return resolved or None


def _server_timeout(args: argparse.Namespace, server: ServerConfig) -> float:
    """--timeout if given, else the server's own startup_timeout_sec, else 25."""
    if args.timeout is not None:
        return args.timeout
    return server.startup_timeout or DEFAULT_TIMEOUT


def _apply_baseline(report: Report, args: argparse.Namespace) -> Report | None:
    """Write and/or apply a baseline. Returns None when the file is unusable.

    A baseline is how an existing project adopts the tool at all: the first run
    on a real repo finds things that predate you, and failing CI on all of them
    means nobody turns it on.
    """
    write_path = getattr(args, "write_baseline", None)
    if write_path:
        payload = {
            "version": 1,
            "findings": [
                {
                    "fingerprint": finding.fingerprint,
                    "rule": finding.rule,
                    "severity": finding.severity.value,
                    "tool": finding.tool,
                    "message": finding.message,
                }
                for finding in report.findings
            ],
        }
        try:
            Path(write_path).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            print(f"agentcheckup: cannot write baseline {write_path}: {exc}", file=sys.stderr)
            return None
        print(
            f"agentcheckup: recorded {len(report.findings)} finding(s) in {write_path}",
            file=sys.stderr,
        )

    read_path = getattr(args, "baseline", None)
    if not read_path:
        return report

    try:
        payload = json.loads(Path(read_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"agentcheckup: cannot read baseline {read_path}: {exc}", file=sys.stderr)
        return None

    entries = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        print(
            f"agentcheckup: {read_path} is not a baseline file (no findings array).",
            file=sys.stderr,
        )
        return None

    known = {
        entry.get("fingerprint") for entry in entries if isinstance(entry, dict)
    }
    kept = [finding for finding in report.findings if finding.fingerprint not in known]
    report.suppressed = len(report.findings) - len(kept)
    report.findings = kept
    return report


def _exit_code(report: Report, fail_on: str, min_score: int | None) -> int:
    if min_score is not None and report.score < min_score:
        return EXIT_FINDINGS
    if fail_on == "never":
        return EXIT_OK
    return EXIT_FINDINGS if report.exceeding(THRESHOLDS[fail_on]) else EXIT_OK


def _dedupe(servers: list[ServerConfig]) -> list[ServerConfig]:
    """The same server is often declared in several configs.

    Spawning it twice would double its tools and invent conflicts that do not
    exist, so identity is the launch spec, not the name.

    ``env`` is part of that spec. Two entries with the same command but different
    environment variables can point at different backends; merging them dropped
    one from the audit entirely. Values are compared in-process and never
    rendered, so nothing secret is hashed, stored or printed.
    """
    seen: set[tuple] = set()
    out: list[ServerConfig] = []
    for server in servers:
        key = (
            (server.command or "").lower(),
            tuple(a.lower() for a in server.args),
            (server.url or "").lower(),
            tuple(sorted(server.env.items())),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(server)
    return out


def _assign_instances(servers: list[ServerConfig]) -> None:
    """Give every server a key that is unique within this run.

    Names are only unique per config file. When two configs both declare
    ``filesystem``, they get ``filesystem#1`` and ``filesystem#2`` so their tools
    occupy separate slots and a collision between them is visible.
    """
    counts: dict[str, int] = {}
    for server in servers:
        counts[server.name] = counts.get(server.name, 0) + 1

    used: dict[str, int] = {}
    for server in servers:
        if counts[server.name] == 1:
            server.instance = server.name
            continue
        used[server.name] = used.get(server.name, 0) + 1
        server.instance = f"{server.name}#{used[server.name]}"


_SECRETISH = re.compile(r"(token|secret|password|passwd|api[_-]?key|credential|auth)", re.I)

#: Common credential prefixes, plus long opaque strings. The point is to catch
#: the value that follows `--api-key`, not the flag name itself.
_TOKENLIKE = re.compile(r"^(sk-|ghp_|gho_|ghs_|xox[bpas]-|AKIA|eyJ)[A-Za-z0-9_.-]{8,}$")


def _looks_like_secret(text: str) -> bool:
    if _TOKENLIKE.match(text):
        return True
    return len(text) >= 32 and re.fullmatch(r"[A-Za-z0-9_\-]+", text) is not None


def _display(text: str) -> str:
    """Quote an argument for reading, not for re-execution.

    shlex.quote is POSIX-shaped and produces `'"'"'` noise on Windows, which is
    where most of these configs live. This only has to be unambiguous to a human.
    """
    if not text or any(ch.isspace() for ch in text):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def _redact(argv: list[str]) -> str:
    """Render a command line with credentials masked.

    ``--dry-run`` exists so a user can see what would be executed before allowing
    it; printing the token in that preview would defeat the point. The value is
    masked, not the flag, so `--api-key <redacted>` still says what is happening.
    """
    shown: list[str] = []
    redact_next = False
    for arg in argv:
        text = str(arg)
        if redact_next:
            shown.append("<redacted>")
            redact_next = False
            continue
        if _SECRETISH.search(text):
            if "=" in text:
                key = text.split("=", 1)[0]
                shown.append(f"{key}=<redacted>")
            else:
                shown.append(_display(text))
                redact_next = True
            continue
        shown.append("<redacted>" if _looks_like_secret(text) else _display(text))
    return " ".join(shown)


def _run_audit(args: argparse.Namespace) -> int:
    configs = [] if args.no_discover else discover()

    # --client filters *discovered* configs. A file the user named with --config
    # is audited regardless: they already said they wanted it.
    if args.client:
        wanted = [name.lower() for name in args.client]
        configs = [
            location
            for location in configs
            if any(name in location.label.lower() for name in wanted)
        ]
        if not configs and not args.config:
            print(
                f"agentcheckup: no config matched --client {', '.join(args.client)}. "
                "Omit the flag to audit everything that was found.",
                file=sys.stderr,
            )
            return EXIT_USAGE

    for extra in args.config:
        path = Path(extra)
        if not path.is_file():
            print(f"agentcheckup: no such config file: {path}", file=sys.stderr)
            return EXIT_USAGE
        configs.append(ConfigLocation("explicit", path, "explicit", "explicit"))

    if not configs:
        print(
            "agentcheckup: no MCP client config found.\n"
            "Looked for Claude Desktop, Claude Code, Cursor, Windsurf, Cline and\n"
            "project-local .mcp.json / .cursor/mcp.json / .vscode/mcp.json.\n"
            "Point it at one explicitly: agentcheckup audit --config path/to/config.json",
            file=sys.stderr,
        )
        return EXIT_USAGE

    servers: list[ServerConfig] = []
    for location in configs:
        servers.extend(
            load_servers(
                location.path,
                location.label,
                client=location.client,
                scope=location.scope,
            )
        )

    for note in take_toml_skips():
        print(f"agentcheckup: could not read TOML config {note}", file=sys.stderr)

    servers = _dedupe(servers)
    _assign_instances(servers)
    servers, shadowed = resolve_scopes(servers)
    # Renumber: a server that was `filesystem#2` because a shadowed twin existed
    # is the only one left, and should be reported under its own name.
    _assign_instances(servers)

    if not servers:
        print("agentcheckup: configs found, but none declare an MCP server.", file=sys.stderr)
        return EXIT_USAGE

    if getattr(args, "dry_run", False):
        print(f"Would start {len(servers)} server(s) from {len(configs)} config(s):")
        print()
        for server in servers:
            if not server.command:
                print(f"  {server.name:20} (url) {server.url or ''} — not started")
                continue
            print(f"  {server.name:20} {_redact([server.command, *server.args])}")
        print()
        print("Nothing was executed.")
        print("Re-run without --dry-run to probe them, or add --no-spawn to audit")
        print("the configuration only.")
        return EXIT_OK

    if not args.no_spawn and not getattr(args, "dry_run", False) and not args.probe:
        print(
            f"agentcheckup: starting {len(servers)} server(s) from your config. "
            "Pass --probe to acknowledge, --dry-run to see the commands, or "
            "--no-spawn to audit the config only.",
            file=sys.stderr,
        )

    tools_by_server: dict[str, list] = {}
    failures: dict[str, str] = {}
    partial: dict[str, str] = {}

    if args.no_spawn:
        # Config-only mode: no tools, so no tool or conflict findings.
        for server in servers:
            failures[server.key] = "not started (--no-spawn)"
    else:
        for server in servers:
            if not server.command:
                failures[server.key] = "remote server (url); cannot be introspected over stdio"
                continue
            argv = [server.command, *server.args]
            try:
                with StdioSession(
                    argv, timeout=_server_timeout(args, server), env=_child_env(server)
                ) as session:
                    tools_by_server[server.key] = session.list_tools()
                    if session.partial_reason:
                        partial[server.key] = session.partial_reason
            except LoadError as exc:
                failures[server.key] = str(exc).splitlines()[0][:200]

    report = lint_audit(
        servers,
        tools_by_server,
        failures={} if args.no_spawn else failures,
        source=f"{len(configs)} config(s)",
        partial=partial,
        shadowed=shadowed,
    )
    report = _apply_baseline(report, args)
    if report is None:
        return EXIT_USAGE
    _emit(report, args)
    return _exit_code(report, args.fail_on, args.min_score)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # `agentcheckup` with no arguments is the whole point: one command, full audit.
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version")):
        argv = ["audit", *argv]

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "rules":
        print(render_rule_list())
        return EXIT_OK

    if args.command == "audit":
        return _run_audit(args)

    try:
        if args.command == "scan":
            if bool(args.path) == bool(args.cmd):
                parser.error("scan needs exactly one of: a JSON path, or --cmd")
            if args.cmd:
                with StdioSession(args.cmd) as session:
                    tools = session.list_tools()
                report = lint_tools(tools, source=f"cmd: {args.cmd}")
            else:
                path = Path(args.path)
                report = lint_tools(load_from_file(path), source=str(path))
        else:
            path = Path(args.path)
            report = lint_servers(servers_from_config(path), source=str(path))
    except LoadError as exc:
        print(f"agentcheckup: {exc}", file=sys.stderr)
        return EXIT_USAGE

    report = _apply_baseline(report, args)
    if report is None:
        return EXIT_USAGE
    _emit(report, args)
    return _exit_code(report, args.fail_on, args.min_score)


if __name__ == "__main__":
    raise SystemExit(main())
