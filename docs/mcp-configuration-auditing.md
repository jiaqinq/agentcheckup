# Auditing MCP server configuration

**Short answer:** most MCP risks are visible in the config file, not at runtime.
`agentcheckup` reads the configs your clients already have, applies 37 rules, and
tells you which settings are worth changing.

```bash
# Configuration only — starts nothing
agentcheckup audit --no-spawn
```

## Which clients it finds

26 locations on a normal machine, across 12 client families:

| Client | Where it looks |
|---|---|
| Claude Desktop | `%APPDATA%/Claude/claude_desktop_config.json` (Windows), `~/Library/Application Support/Claude/` (macOS), `~/.config/Claude/` (Linux) |
| Claude Code | `~/.claude.json`, plus per-project `projects[*].mcpServers` |
| Codex CLI | `~/.codex/config.toml` |
| Cursor | `~/.cursor/mcp.json`, `%APPDATA%/Cursor/User/settings.json` |
| VS Code / VSCodium / Windsurf | `User/settings.json` with `mcp.servers` |
| Cline / Roo Code / Kilo Code | `User/globalStorage/<extension>/settings/cline_mcp_settings.json` |
| Zed | `%APPDATA%/Zed/settings.json`, `~/.config/zed/settings.json` |
| Continue | `~/.continue/config.json` |
| Project-local | `.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json` |

Four JSON shapes are handled, because clients disagree about nesting:

```jsonc
{"mcpServers": {...}}                    // Claude Desktop, Cursor, Claude Code
{"servers": {...}}                       // VS Code, some forks
{"mcp": {"servers": {...}}}              // VS Code settings.json
{"projects": {"/path": {"mcpServers": {...}}}}   // Claude Code, per project
```

Codex uses TOML, not JSON. On Python 3.10 `tomllib` does not exist, so that config
is skipped — and the skip is **announced on stderr** rather than swallowed. A
silent skip makes a Codex user believe they have no servers configured.

```bash
# Narrow to the clients you care about
agentcheckup audit --client cursor --client codex
```

## The config rules

| Rule | Severity | What it catches |
|---|---|---|
| `AGT101` | warning | `npx` package without a pinned version |
| `AGT102` | warning | `uvx` package without a pinned version |
| `AGT103` | warning | Config wraps the server in a shell (`sh -c`, `cmd /c`) |
| `AGT104` | error | Filesystem server rooted at a volume root |
| `AGT105` | info | Server did not return a tool list (unreachable, unaudited) |
| `AGT106` | error | Permission-bypass flag (`--yolo`, `--dangerously-skip-permissions`) |
| `AGT107` | warning | Credential stored in plaintext in the config |
| `AGT108` | warning | Remote server over plain `http://` |

### Why `AGT104` is an error and `AGT101` is only a warning

An unpinned `npx` package means the next install may run different code. Annoying,
but the server still works and you can pin it later.

A filesystem server rooted at `/` or a drive root means one prompt injection
reaches SSH keys, browser profiles and every other project on the machine. That is
not a style issue, so it is not a warning.

### Why `AGT105` is info, not an error

A server that will not start is *unverified*, not *broken*. It might need a
credential you have not exported yet, or be a remote endpoint that cannot be
introspected over stdio. Reporting it as an error trains people to ignore errors.

The report says how many servers were actually inspected:

```
coverage: 2/3 server(s) inspected (67%), 1 unverified
```

**A server that never answered is not a clean server**, and the two must not look
alike.

## What "auditing" does not mean here

- **No CVE scanning.** This is not a vulnerability scanner. It reads your config
  and your tool definitions; it does not compare package versions against advisory
  databases.
- **No runtime protection.** It does not sit between your agent and the servers.
- **No credential validation.** It detects a token written in plaintext; it does
  not tell you whether the token is valid or over-scoped.

If you need those, they are different tools with different threat models.

## A note on what gets executed

`audit` starts the servers in your config, because `tools/list` is the only way to
see the tool manifest. That is a real decision with real consequences: a server
process can do whatever it was written to do.

```bash
agentcheckup audit --dry-run   # print the commands, run nothing
agentcheckup audit --no-spawn  # audit the config only
agentcheckup audit --probe     # explicit "yes, start them"
```

## See also

- [Conflict detection](mcp-tool-conflict-detection.md)
- [Token cost of the tool manifest](mcp-tool-manifest-token-cost.md)
- [Rule reference](rules.md) · [Repository](https://github.com/jiaqinq/agentcheckup)
