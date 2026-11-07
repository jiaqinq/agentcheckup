"""Client-config rules.

Most MCP incidents start here rather than in the server code: an unpinned
``npx -y`` package that silently updates, a shell wrapper that turns every arg
into a command, a filesystem server rooted at ``/``.
"""

from __future__ import annotations

import re

from ..models import Finding, ServerConfig, Severity
from .base import config_rule

SHELL_WRAPPERS = ("sh", "bash", "zsh", "cmd", "cmd.exe", "powershell", "pwsh")

DANGEROUS_FLAGS = (
    "--dangerously-skip-permissions",
    "--yolo",
    "--allow-all",
    "--no-sandbox",
    "--disable-web-security",
)

SECRET_KEY = re.compile(r"(api[_-]?key|token|secret|password|passwd|credential|private[_-]?key)", re.I)

DRIVE_ROOT = re.compile(r"^[A-Za-z]:[\\/]?$")


def _package_arg(args: list[str]) -> str | None:
    """First positional argument, skipping flags and their values."""
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in ("-y", "--yes", "-q", "--quiet"):
            continue
        if arg.startswith("-"):
            # Flags like `--registry` take a value; treat conservatively.
            if "=" not in arg and arg in ("--registry", "--cache", "--prefix", "--cwd"):
                skip_next = True
            continue
        return arg
    return None


def _is_pinned(spec: str) -> bool:
    """`pkg@1.2.3` is pinned; `pkg`, `pkg@latest`, `pkg@^1` are not."""
    if "@" not in spec:
        return False
    version = spec.rsplit("@", 1)[1]
    if not version or version in ("latest", "next", "beta", "canary"):
        return False
    return version[0].isdigit()


@config_rule("AGT101", Severity.WARNING, "npx package is not version-pinned")
def unpinned_npx(server: ServerConfig):
    """`npx -y foo` re-resolves to the latest release on every launch.

    That is a silent supply-chain dependency: the code you audited last week is
    not necessarily the code running today.
    """
    if not server.command or "npx" not in server.command.lower():
        return None
    spec = _package_arg(server.args)
    if spec and not _is_pinned(spec):
        return Finding(
            rule="AGT101",
            severity=Severity.WARNING,
            message=f"Server {server.name!r} runs unpinned npx package {spec!r}.",
            tool=server.name,
            hint=f"Pin it: npx -y {spec}@1.2.3",
        )
    return None


@config_rule("AGT102", Severity.WARNING, "uvx package is not version-pinned")
def unpinned_uvx(server: ServerConfig):
    """Same failure mode as AGT101, on the Python side."""
    if not server.command or "uvx" not in server.command.lower():
        return None
    spec = _package_arg(server.args)
    if spec and not _is_pinned(spec):
        return Finding(
            rule="AGT102",
            severity=Severity.WARNING,
            message=f"Server {server.name!r} runs unpinned uvx package {spec!r}.",
            tool=server.name,
            hint=f"Pin it: uvx {spec}==1.2.3",
        )
    return None


@config_rule("AGT103", Severity.WARNING, "Config wraps the server in a shell")
def shell_wrapper(server: ServerConfig):
    """`sh -c "..."` re-parses every argument, so any string can become a command.

    It also defeats argument escaping that the client already did for you.
    """
    if not server.command:
        return None
    base = server.command.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base in SHELL_WRAPPERS and any(a in ("-c", "/c", "/C", "-Command") for a in server.args):
        return Finding(
            rule="AGT103",
            severity=Severity.WARNING,
            message=f"Server {server.name!r} is launched through a shell wrapper ({server.command}).",
            tool=server.name,
            hint="Call the executable directly and pass args as a list.",
        )
    return None


@config_rule("AGT104", Severity.ERROR, "Filesystem server is rooted at the volume root")
def broad_fs_root(server: ServerConfig):
    """Granting the filesystem root gives the agent read-write access to everything.

    One prompt injection is then enough to reach SSH keys, browser profiles and
    every other project on the machine.
    """
    for arg in server.args:
        if arg == "/" or DRIVE_ROOT.match(arg):
            return Finding(
                rule="AGT104",
                severity=Severity.ERROR,
                message=f"Server {server.name!r} is granted the whole filesystem ({arg}).",
                tool=server.name,
                hint="Point it at a project directory instead of the volume root.",
            )
    return None


@config_rule("AGT105", Severity.WARNING, "Remote server uses plain HTTP")
def insecure_url(server: ServerConfig):
    """Tool calls carry your data and often your credentials."""
    if server.url and server.url.lower().startswith("http://"):
        return Finding(
            rule="AGT105",
            severity=Severity.WARNING,
            message=f"Server {server.name!r} uses an unencrypted http:// endpoint.",
            tool=server.name,
            hint="Use https://, or a localhost port you control.",
        )
    return None


@config_rule("AGT106", Severity.ERROR, "Config passes a permission-bypass flag")
def dangerous_flag(server: ServerConfig):
    """These flags disable the only confirmation step between the model and your disk."""
    joined = " ".join([server.command or "", *server.args])
    for flag in DANGEROUS_FLAGS:
        if flag in joined:
            return Finding(
                rule="AGT106",
                severity=Severity.ERROR,
                message=f"Server {server.name!r} is launched with {flag}.",
                tool=server.name,
                hint="Remove the flag and grant the narrowest permission that still works.",
            )
    return None


@config_rule("AGT107", Severity.WARNING, "Credentials are stored in plaintext in the config")
def plaintext_secret(server: ServerConfig):
    """Config files get committed, screenshotted and shared in issues.

    Reading from the environment keeps the secret out of the file.
    """
    hits = [k for k in server.env if SECRET_KEY.search(k)]
    if hits:
        return Finding(
            rule="AGT107",
            severity=Severity.WARNING,
            message=f"Server {server.name!r} stores credential(s) inline: {', '.join(sorted(hits)[:5])}.",
            tool=server.name,
            hint="Reference an env var (e.g. ${GITHUB_TOKEN}) instead of pasting the value.",
        )
    return None
