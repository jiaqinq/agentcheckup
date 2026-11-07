# Use agentcheckup as a GitHub Action

```yaml
name: agentcheckup

on: [push, pull_request]

permissions:
  contents: read

jobs:
  diagnose:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: wanjiaqing/agentcheckup@main
        with:
          config: .mcp.json
          fail-on: warning
```

The action installs agentcheckup from its own checkout, so the version you pin in
`uses:` is the version you get. No PyPI release required, no `pip install` step.

## Inputs

| Input | Default | Notes |
|---|---|---|
| `config` | `""` | Config file(s), comma or newline separated. Empty = auto-discover. |
| `fail-on` | `error` | `error` / `warning` / `info` / `never`. |
| `min-score` | `""` | Also fail below this score. Empty disables it. |
| `sarif-file` | `""` | Write SARIF here for `upload-sarif`. Empty disables it. |
| `args` | `""` | Extra arguments, e.g. `--no-spawn --timeout 40`. |

## Outputs

| Output | Example | Notes |
|---|---|---|
| `score` | `74` | 0-100 |
| `grade` | `C` | A-F |
| `findings` | `3` | Total findings |
| `exit-code` | `1` | 0 clean, 1 findings, 2 usage error |

Outputs are published even when the gate fails, so you can gate on score without
parsing the log:

```yaml
      - uses: wanjiaqing/agentcheckup@main
        id: doctor
        with:
          config: .mcp.json
          fail-on: never

      - if: steps.doctor.outputs.score < 70
        run: echo "::warning::agentcheckup score dropped to ${{ steps.doctor.outputs.score }}"
```

## SARIF, for code scanning

```yaml
permissions:
  contents: read
  security-events: write   # required by upload-sarif

steps:
  - uses: actions/checkout@v4
  - uses: wanjiaqing/agentcheckup@main
    with:
      config: .mcp.json
      sarif-file: agentcheckup.sarif
      fail-on: never
  - uses: github/codeql-action/upload-sarif@v4
    with:
      sarif_file: agentcheckup.sarif
```

Without `security-events: write` the upload fails with
`Resource not accessible by integration`. That is not an agentcheckup error, but
it is the one people hit first.

## Auto-discovery inside CI

Empty `config` makes the action look for the same 27 config locations it looks
for locally. On a fresh runner that usually finds nothing, and agentcheckup exits
`2` with a clear message rather than passing silently.

For CI, pass the config explicitly:

```yaml
      - uses: wanjiaqing/agentcheckup@main
        with:
          config: |
            .mcp.json
            .vscode/mcp.json
```

## Speed

Spawning every MCP server takes time. If you only need the config checks:

```yaml
      - uses: wanjiaqing/agentcheckup@main
        with:
          config: .mcp.json
          args: --no-spawn
```

`--no-spawn` skips starting servers, so tool-level rules and conflict detection
are skipped too. It is fast and useful, but it is not the full check.

## Pinning

`@main` tracks the branch. For reproducible CI, pin a tag or a commit SHA:

```yaml
      - uses: wanjiaqing/agentcheckup@v0.3.0
```
