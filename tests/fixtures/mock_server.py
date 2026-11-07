"""A minimal stdio MCP server used to test the live ``--cmd`` path.

Implements just enough of the protocol to answer ``initialize`` and
``tools/list``. Kept dependency-free on purpose: the test must not need the
official SDK, because then a broken SDK release would look like a broken linter.

Profiles exist so a demo can stand up two servers that collide with each other -
that is the whole point of the conflict detector, and it needs two real
processes to be honest about it.
"""

from __future__ import annotations

import argparse
import json
import sys

READ_FILE_GOOD = (
    "Read a UTF-8 text file from the sandbox and return its contents. "
    "Use this only for files under the project root; prefer `list_dir` first. "
    "Returns the file body as a string."
)

PATH_PROP = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path relative to the sandbox root.",
            "pattern": "^.*$",
        }
    },
    "required": ["path"],
    "additionalProperties": False,
}

PROFILES: dict[str, list[dict]] = {
    "default": [
        {
            "name": "read_file",
            "description": READ_FILE_GOOD,
            "inputSchema": PATH_PROP,
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
        {
            "name": "drop_table",
            "description": "Drops a table.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    ],
    # Two servers, both exposing `read_file` with nearly the same wording.
    # A hard collision the model cannot resolve.
    "files": [
        {
            "name": "read_file",
            "description": (
                "Read a text file from the local filesystem and return its contents. "
                "Use this only for files under the sandbox root; prefer `list_dir` first. "
                "Returns the file body as a string."
            ),
            "inputSchema": PATH_PROP,
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
        {
            "name": "list_dir",
            "description": (
                "List entries in one directory under the sandbox root. "
                "Use this only when you need names before calling `read_file`. "
                "Returns a JSON array of {name, type} objects."
            ),
            "inputSchema": PATH_PROP,
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
    ],
    "git": [
        {
            "name": "read_file",
            "description": (
                "Read a file as it exists in a git revision and return its contents. "
                "Use this only for committed content; prefer `git_show` for diffs. "
                "Returns the file body as a string."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository-relative path.",
                        "pattern": "^.*$",
                    },
                    "rev": {
                        "type": "string",
                        "description": "Commit SHA, branch or tag.",
                        "pattern": "^[A-Za-z0-9._/-]+$",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
        {
            "name": "git_status",
            "description": (
                "Show the working tree status. Use this only when you need to know "
                "what is modified; prefer `git_log` for history. Returns a list of entries."
            ),
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
    ],
}


def send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="default", choices=sorted(PROFILES))
    args = parser.parse_args()
    tools = PROFILES[args.profile]

    # Some servers log to stdout; the client must tolerate that. Emit a line of
    # noise before the handshake so the test actually covers it.
    sys.stdout.write(f"mock server starting (profile={args.profile})\n")
    sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = message.get("method")
        msg_id = message.get("id")

        if method == "initialize":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": f"mock-{args.profile}", "version": "0.0.1"},
                    },
                }
            )
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}})
        elif msg_id is not None:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"unknown method {method}"},
                }
            )


if __name__ == "__main__":
    main()
