"""A controllable MCP stdio server for tests.

Each mode reproduces one failure the loader must survive. Nothing here touches a
real server, a real config or the network — it reads stdin, writes stdout, and
sometimes misbehaves on purpose.

    python tests/fixtures/mock_mcp.py --mode ok
"""

from __future__ import annotations

import argparse
import json
import sys
import time


def reply(msg_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


def tool(name: str, description: str = "Do a thing and return it.") -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "A path."}},
            "required": ["path"],
            "additionalProperties": False,
        },
    }


TOOLS = [tool("read_file"), tool("write_file")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="ok")
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--delay", type=float, default=30.0)
    args = parser.parse_args()

    mode = args.mode

    if mode == "exit-immediately":
        return 0

    if mode == "hang-start":
        # Never reads stdin, never replies. The loader must give up on its own.
        time.sleep(args.delay)
        return 0

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")
        msg_id = message.get("id")

        if method == "initialize":
            if mode == "hang-init":
                time.sleep(args.delay)
                return 0
            reply(
                msg_id,
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mock", "version": "0"},
                },
            )

        elif method == "notifications/initialized":
            continue

        elif method == "tools/list":
            if mode == "hang-list":
                time.sleep(args.delay)
                return 0

            if mode == "partial-json":
                # Half a message, then nothing. readline() never returns a line.
                sys.stdout.write('{"jsonrpc": "2.0", "id": 2, "resu')
                sys.stdout.flush()
                time.sleep(args.delay)
                return 0

            if mode == "paginated":
                cursor = (message.get("params") or {}).get("cursor")
                page = int(cursor) if cursor else 0
                if page >= args.pages:
                    reply(msg_id, {"tools": []})
                    continue
                result = {"tools": [tool(f"page{page}_tool")]}
                if page + 1 < args.pages:
                    result["nextCursor"] = str(page + 1)
                reply(msg_id, result)

            elif mode == "repeat-cursor":
                # Always hands back the same cursor: a loader that trusts it loops.
                reply(msg_id, {"tools": [tool("looping")], "nextCursor": "same"})

            elif mode == "empty-page-then-more":
                cursor = (message.get("params") or {}).get("cursor")
                if cursor == "2":
                    reply(msg_id, {"tools": [tool("after_empty")]})
                else:
                    reply(msg_id, {"tools": [], "nextCursor": "2"})

            elif mode == "huge":
                reply(msg_id, {"tools": [tool(f"bulk_{i}") for i in range(5000)]})

            elif mode == "exit-mid-list":
                sys.stdout.write("")
                return 0

            else:
                reply(msg_id, {"tools": TOOLS})

        elif msg_id is not None:
            reply(msg_id, {})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
