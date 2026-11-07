# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Rule ids are permanent: once shipped, an id never changes meaning. New rules get
new ids, and removing a rule is a breaking change.

## [Unreleased]

## [0.4.2] - 2026-11-07

Three claims the tool made that it had not earned. All were found by an external
review of the README and the report text, not by a bug report.

### Fixed

- **`AGT201` no longer asserts what the client does.** The hint said "the client
  keeps one and the other is unreachable". No client was ever tested; the
  behaviour differs between clients and some namespace the tools instead. The
  message now says the call can reach either one and that clients resolve it
  differently, which is true without a test.
- **README no longer claims "No network calls, ever."** agentcheckup makes none
  of its own, but `audit` starts every server in your config, and those processes
  can do whatever they were written to do. The claim now names that boundary and
  points at `--no-spawn`.
- **README said 27 config locations; there are 26.** Both languages.

## [0.4.1] - 2026-11-07

Both fixes came out of an external fact-check of the project, not from a bug
report: the repository has no users yet, so nothing surfaced them in the field.

### Fixed

- **`AGT105` was used by two unrelated rules.** "Server did not return a tool
  list" (suite) and "Remote server uses plain HTTP" (config) shared the id, with
  different severities. Rule ids are the tool's public API — people put them in
  suppression lists — so two checks under one name is worse than either check
  being wrong. The config rule is now `AGT108`; `AGT105` keeps the meaning every
  document and the README already gave it.
- **README pointed the GitHub Action at `@v0.3.0`**, a tag that no longer exists.
  Anyone copying the snippet got a resolution failure. Now `@v0.4.1`.
- `docs/rules.md` listed `AGT105` twice and described the suite rule as a
  warning when it had been downgraded to info.

### Added

- `tests/test_registry.py`: ids are unique across all three registries, well
  formed, and — for every rule that constructs its own `Finding` — the severity
  emitted matches the severity registered. That last check is the one that would
  have caught the duplicate before it shipped.

## [0.4.0] - 2026-11-07

Calibration release, driven by the first run against real servers rather than
fixtures. Installing `mcp-server-fetch`, `mcp-server-git` and `mcp-server-time`
and auditing all three produced **Grade F, 0/100, 89 findings across 18 tools**.
A tool that scores the official reference implementations zero is a tool nobody
trusts, so the scoring and the report both changed.

### Changed

- **Score is normalised per tool.** Budget is 20 points per tool; a flat
  subtraction punished manifests for being large and scored the official servers
  0/100. Calibrated against four real inputs: clean 100, official servers 87,
  a collision-plus-token config 79, deliberately broken 36.
- **Info findings are capped at 10 points total.** `AGT022` fired on 18 of 18
  official tools and `AGT023` on 17 of 18 — a rule that fires on everything is a
  preference, not a defect, and charging one point each buried the two findings
  that mattered.
- **Repeated findings collapse.** Twelve tools missing parameter descriptions now
  print as one line naming all twelve instead of twelve near-identical blocks.
  Info findings are summarised one line per rule. The official-server report went
  from 40 lines to 18.
- **`AGT011` (short description) is now `info`.** Short is a nudge; *missing* is
  `AGT010`'s error.
- **`AGT105` (server did not return a tool list) is now `info`.** It means "not
  checked", not "your config is wrong" — it fired on a machine without `npx` and
  dragged the score down for an environment issue.
- **`AGT107` (plaintext credentials) is now `warning`.** It was `info`, which
  under the new model made a stored token cost nothing.

### Added

- `tests/test_scoring.py`: score calibration, per-tool normalisation, info cap,
  and aggregation behaviour, including the "12 findings print as one block" case.
- README section documenting the score model with the four calibration inputs.

### Notes

- Conflict detection produced **zero false positives** across the 18 real tools
  from the three official servers. *(Corrected in 0.4.4: that measurement was
  vacuous — those 18 tools contained no conflicts, so there was nothing to get
  wrong. A real benchmark replaced it.)*

## [0.3.0] - 2026-11-07

Distribution release. The tool worked; nobody could reach it from CI.

### Added

- **GitHub Action** (`action.yml`). Installs from its own checkout, so pinning
  the action version pins the tool version and a PyPI release is not required.
  Inputs: `config`, `fail-on`, `min-score`, `sarif-file`, `args`. Outputs:
  `score`, `grade`, `findings`, `exit-code` — published even when the gate fails,
  so a workflow can gate on score without parsing the log.
- `--json-out PATH` and `--sarif-out PATH`. One run now yields the human report,
  machine-readable JSON and SARIF, instead of re-spawning every server to get a
  second format.
- Config discovery covers **27 paths**: Claude Desktop, Claude Code, Cursor,
  VS Code, Cline, Roo Code, Kilo Code, Windsurf, Zed, Codex CLI, Continue, plus
  project-local files.
- VS Code's `mcp.servers` nesting and Zed's `context_servers` key are read.
- Codex CLI's TOML config is parsed via `tomllib` on Python 3.11+, and skipped
  rather than adding a dependency on 3.10.
- `docs/github-action.md`.

### Changed

- Cline, Roo Code and Kilo Code paths are generated for every editor flavour on
  every OS. Previously they were hardcoded Windows-only, so macOS and Linux users
  got no Cline coverage at all.

### Fixed

- `discover()` walked a hardcoded Windows branch for extension paths; it now
  derives from one platform table.

## [0.2.0] - 2026-11-07

Repositioned from "MCP manifest linter" to "agent setup doctor". The manifest
rules were already there; what was missing was the one question no other tool
answers: *what happens when five servers are loaded at once?*

### Added

- **Cross-server conflict detection** (`AGT201`–`AGT203`). Hard name collisions,
  normalised-name collisions, and description overlap between tools from
  different servers. No embeddings, no network — token Jaccard with a shared-head-
  noun guard to keep the false-positive rate usable.
- **`agentcheckup` with no arguments** now audits everything it can find: Claude
  Desktop, Claude Code (including per-project `mcpServers`), Cursor, Windsurf,
  Cline, and project-local `.mcp.json` / `.cursor/mcp.json` / `.vscode/mcp.json`.
- **`audit` subcommand** with `--config`, `--no-discover`, `--no-spawn`, `--timeout`.
- `AGT105` for servers that fail to start or cannot be introspected over stdio.
  Reported and skipped, never fatal.
- `StdioSession` accepts an argv list and an `env` dict, so servers are launched
  without shell quoting (which matters on Windows) and with the environment their
  config declares.
- `discovery` module with config discovery and Claude Code's nested project layout.
- Report splits findings into **CONFLICTS** and **RISKS** sections for `audit`.

### Changed

- Renamed from `mcplint` to `agentcheckup`; rule prefix `MCP` → `AGT`.
- `Report` carries `server_count`; JSON output includes it.
- The text header for `audit` reports servers, tools and tokens on one line.

### Fixed

- Plural stemming treated `files` as an `-es` plural and produced `fil`, so
  `read_file` and `read_files` were not recognised as the same word.
- Conflict scoring was name-weighted enough that two tools with 71% description
  overlap scored 0.543 and slipped under a 0.55 threshold. Description overlap is
  now a primary signal, because that is what the model actually reads.

## [0.1.0] - 2026-11-07

First release. 32 rules, three output formats, two input modes.

### Added

- `scan` for saved manifests (`{"tools": [...]}`, a bare list, a JSON-RPC
  `result.tools` envelope, or a session log with `messages`) and for live stdio
  servers via `--cmd`.
- `config` to audit MCP client config files (`mcpServers`, `servers`,
  `mcp_servers`).
- `rules` to list every rule with its id and severity.
- 32 rules across naming, documentation, schema, safety, injection, and config.
- Output formats: `text`, `json`, `sarif` (SARIF 2.1.0 for GitHub code scanning).
- `--fail-on error|warning|info|never` and `--min-score N` for CI gates.
- Manifest token estimation, reported on every run.
- Zero runtime dependencies. Python 3.10+.
