# agentcheckup

> Diagnose your agent setup before your agent does.

[![CI](https://github.com/jiaqinq/agentcheckup/actions/workflows/ci.yml/badge.svg)](https://github.com/jiaqinq/agentcheckup/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agentcheckup.svg)](https://pypi.org/project/agentcheckup/)
[![Python](https://img.shields.io/pypi/pyversions/agentcheckup.svg)](https://pypi.org/project/agentcheckup/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Every other MCP tool looks at **one server**. None of them look at what happens
when you load five.

```console
$ agentcheckup

agentcheckup 0.4.0  |  3 server(s)  |  4 tool(s)  |  ~442 tokens per request

  Grade C    Score  79/100   1 error  2 warning  1 info

  CONFLICTS (1)
    AGT201  Tool name 'read_file' is exposed by both 'files' and 'git'.
            [files/read_file <-> git/read_file]
            fix: Hard collision: the client keeps one and the other is
                 unreachable. Rename one, or use a gateway that prefixes.

  RISKS (2)
    AGT101  Server 'github' runs unpinned npx package
            '@modelcontextprotocol/server-github'.
    AGT107  Server 'github' stores credential(s) inline:
            GITHUB_PERSONAL_ACCESS_TOKEN.

  NUDGES (1 across 1 rule(s), no score impact)
    AGT105  Server did not return a tool list  (1)
            github
```

## The problem nobody is testing for

Two servers cannot see each other. Your model can. It gets a flat list of 47
tools from five servers and picks by description similarity — with no way to know
that `files.read_file` and `git.read_file` are different things.

Three failure modes follow, and no existing tool catches them:

**1. Hard collision.** Two servers expose the same tool name. The client keeps
one, the other is silently unreachable. You spend an afternoon debugging "why
won't it read the file" when the answer is "it's calling the other one".

**2. Soft collision.** `github.search` and `docs.search` with 70% overlapping
descriptions. Selection becomes a coin flip that looks exactly like model
flakiness. It isn't — it's your manifest.

**3. Context tax.** An agent pays for the full tool manifest on **every** request.
47 tools with 200-character descriptions is thousands of tokens before the user
says anything. Nobody budgets for it because nobody measures it.

`agentcheckup` measures all three, in one command, from the configs you already
have.

## What it checks

| Layer | Question it answers | Rules |
|---|---|---|
| **Conflicts** | Will my agent pick the wrong tool? | AGT201–AGT203 |
| **Risks** | Is my setup unsafe? | AGT001–AGT107 |
| **Budget** | What does my manifest cost per request? | reported on every run |

36 rules in total. Full reference: [docs/rules.md](docs/rules.md).

## Install

```bash
pip install agentcheckup
# or run without installing
uvx agentcheckup
```

Python 3.10+. **Zero runtime dependencies** — no SDK, no tokenizer, no embeddings,
no network calls. It reads JSON, starts processes, prints text.

## Usage

### One command, no arguments

```bash
agentcheckup
```

Finds your configs automatically — 26 known locations across Claude Desktop,
Claude Code (including its per-project `mcpServers`), Cursor, VS Code, Cline,
Roo Code, Kilo Code, Windsurf, Zed, Codex CLI and Continue, plus project-local
`.mcp.json` / `.cursor/mcp.json` / `.vscode/mcp.json` — starts each server,
collects its tools, and reports.

Servers that fail to start are reported as `AGT105` and skipped, not fatal. A
broken server should not stop you auditing the other four.

### Common flags

```bash
agentcheckup --no-spawn          # configs only, no processes started
agentcheckup --config path.json  # add a config the discovery missed
agentcheckup --no-discover       # audit only what you passed with --config
agentcheckup --timeout 40        # slow server? give it longer
agentcheckup --format json       # machine-readable
agentcheckup --fail-on warning   # CI gate
```

### One server at a time

```bash
agentcheckup scan tools.json                    # {"tools": [...]}, {"result": {...}} or a log
agentcheckup scan --cmd "python my_server.py"   # live stdio handshake
agentcheckup config ~/.claude.json              # config rules only
agentcheckup rules                              # list every rule
```

### As a GitHub Action

The fastest way to keep a manifest from regressing, and the version you pin is
the version you run — the action installs from its own checkout.

```yaml
- uses: jiaqinq/agentcheckup@v0.7.0
  with:
    config: .mcp.json
    fail-on: warning
```

Full reference, including SARIF upload and score gates: [docs/github-action.md](docs/github-action.md).

### Raw CLI in CI

```yaml
- name: Diagnose agent setup
  run: |
    pip install agentcheckup
    agentcheckup --no-spawn --fail-on warning
```

For GitHub code scanning, emit SARIF:

```yaml
- run: agentcheckup --format sarif --fail-on never > agentcheckup.sarif
- uses: github/codeql-action/upload-sarif@v4
  with:
    sarif_file: agentcheckup.sarif
```

One run can produce all three outputs:

```bash
agentcheckup --format text --json-out report.json --sarif-out report.sarif
```

Exit codes: `0` clean, `1` findings at or above `--fail-on`, `2` usage/load error.

## How conflicts are detected

No embeddings, no model, no network — because a linter that needs a 200MB wheel
is a linter that stops running on a plane.

Each tool pair across servers is scored on two signals:

- **name overlap** — normalised token Jaccard (`read_files` ≡ `read_file`)
- **description overlap** — token Jaccard over stopword-stripped, plural-stemmed words

Chinese is tokenised as character bigrams (`读取文件` → `读取`, `取文`, `文件`) rather
than by a segmenter, because a segmenter is a dependency. It is cruder than a real
word split, but without it every Chinese description produced an empty token set
and two Chinese tools could never be compared at all.

A pair is flagged when the descriptions overlap ≥ 65% **and** the names share a
head noun, or when the blended score clears 0.55. The shared-noun requirement is
what keeps `search_repositories` and `search_documents` apart — without it the
false-positive rate made the report untrustworthy, which is worse than no report.

It is a heuristic, and the docs say so. `AGT203` is a warning, not a verdict.

## Adopting it on an existing project

The first run on a real repository finds things that were there before you
arrived. Failing CI on all of them means the tool never gets turned on. Record
them once, then fail only on what is new:

```console
$ agentcheckup audit --write-baseline .agentcheckup-baseline.json
agentcheckup: recorded 8 finding(s) in .agentcheckup-baseline.json

$ agentcheckup audit --baseline .agentcheckup-baseline.json
baseline: 8 known finding(s) withheld
  Grade A    Score 100/100   clean
```

The baseline is plain JSON listing what it suppresses, so a reviewer can see what
was accepted. Fingerprints ignore severity — escalating a rule does not orphan
every entry — and an unreadable baseline is a usage error rather than a silent
no-op.

Commit the file. Regenerate it when you fix things, so the list only shrinks.

## Pick your clients

```bash
agentcheckup audit --client cursor --client codex
```

Repeatable, case-insensitive substring against the discovered client labels. An
unmatched name exits 2 rather than printing an empty report — "found nothing" and
"you typed it wrong" should not look alike.

## Look before it runs

`audit` starts every server in your config to read its tool list. That is what
makes cross-server conflict detection possible, and it is also the part worth
being careful about. `--dry-run` shows exactly what would be executed and stops:

```console
$ agentcheckup audit --dry-run

Would start 2 server(s) from 1 config(s):

  files                python /opt/mcp/files.py
  github               npx -y @modelcontextprotocol/server-github --api-key <redacted>

Nothing was executed.
```

Credentials are masked, so the preview is safe to paste into an issue.
`--no-spawn` goes further: it audits the configuration and never starts anything,
at the cost of no tool or conflict findings.

`--probe` is the explicit "yes, start them" acknowledgement. It does not change
what runs today; it exists so that requiring it later is a documented migration
rather than a surprise.

## Coverage

A server that never answered is not a clean server. The report says which is which:

```console
coverage: 2/3 server(s) inspected (67%), 1 unverified
```

`servers_inspected`, `servers_unverified` and `coverage` are in the JSON output
too. Findings from an unverified server are reported as `AGT105`, never as
"nothing wrong found".

## Does it scale?

`detect_conflicts` groups by exact name and by normalised name, so hard
collisions cost O(n) rather than O(n²). Only the soft-overlap phase enumerates
pairs, from a token index, rarest tokens first, under a budget.

Measured with `scripts/perf.py` on a synthetic manifest:

| tools | pairs | old peak | now peak | now time | planted collision found |
|---:|---:|---:|---:|---:|:--:|
| 50 | 1,225 | 0 MiB | 0 MiB | 0.015 s | yes |
| 200 | 19,900 | 1 MiB | 0 MiB | 0.186 s | yes |
| 1,000 | 499,500 | 30 MiB | 5 MiB | 2.6 s | yes |
| 5,000 | 12,497,500 | 763 MiB | 8 MiB | 2.7 s | yes |

"old peak" is `list(combinations(refs, 2))` alone — what the first version
allocated before filtering anything.

## How well does conflict detection work?

Measured, not asserted. `tests/fixtures/collision_benchmark.json` holds 44
hand-labelled tool pairs — 20 that should be flagged, 24 that should not — and
`scripts/benchmark.py` scores the detector against them:

| | value |
|---|---|
| pairs | 44 (20 positive, 24 negative) |
| precision | **0.952** |
| recall | **1.000** |
| F1 | 0.976 |

The one disagreement is a pair like `lookup_contact` / `lookup_user` with
near-identical descriptions: the detector flags it, the label says it should not.
That is arguably the detector being right and the label being strict.

Two honest caveats. The labels are the author's, not users' — the criterion was
"would a model picking the wrong one get a materially different result". And this
benchmark did not exist before 0.4.4; the earlier claim of "zero false positives"
came from running on 18 tools that contained no conflicts at all, which measured
nothing. `tests/test_benchmark.py` fails the build if precision or recall drops
below 0.90.

## How the score works

Most linters fail here: a rule that fires on 18 of 18 tools is a *preference*,
not a defect, and charging one point each scores the official MCP servers 0/100.
That number is useless, so the model is calibrated instead of invented:

| Severity | Cost | Why |
|---|---|---|
| `error` | 10 | breaks a run, or endangers the host |
| `warning` | 3 | likely to cause wrong behaviour |
| `info` | 1, **capped at 10 total** | a human should decide |

Budget is **20 points per tool**, so a 200-tool manifest is not punished for
being large, and a 4-tool manifest with one hard collision is not let off easy.

Calibration against four real inputs:

| Input | Tools | Result |
|---|---|---|
| Clean fixture | 2 | A · 100 |
| Official `fetch` + `git` + `time` servers | 18 | B · 87 |
| Hard collision + unpinned package + plaintext token | 4 | C · 79 |
| Deliberately broken fixture | 7 | F · 36 |

Repeated findings are collapsed: 12 tools missing parameter descriptions print
as one line naming all twelve, and info findings are summarised one line per
rule. A report nobody can read is a report nobody acts on.

## Design principles

- **Zero runtime dependencies.** A diagnostic that breaks because a transitive
  dep broke is worse than no diagnostic.
- **Stable rule IDs.** `AGT201` never changes meaning. Suppressions and CI
  thresholds keep working across releases.
- **Every finding has a fix.** A rule that only says "this is bad" trains people
  to ignore the output.
- **Degrade, don't die.** A server that will not start is one finding, not an
  aborted run.
- **No network calls of its own.** No telemetry, no API, no upload; your config
  never leaves the machine. It does *start* the servers you configured, and those
  can do whatever they were written to do — `--no-spawn` skips that entirely.
- **Heuristics are labelled as heuristics.** `info` means "a human should
  decide". The score is a conversation starter, not a certification.

## What this is not

- Not a sandbox. It tells you the manifest looks risky; it cannot stop the server.
- Not a runtime guard. Nothing here runs during an agent session.
- Not an MCP protocol validator. It checks quality and safety, not conformance —
  the official `modelcontextprotocol/conformance` suite does that.

## Further reading

- [多个 MCP Server 一起使用时，如何检测工具冲突？](https://juejin.cn/post/7704995965740580904) — the design story, in Chinese: why the scope changed from a single-server linter to cross-server conflicts, and how the scoring was rebuilt after it graded the official servers 0/100.

## Contributing

Adding a rule takes about ten minutes and one small file — see
[CONTRIBUTING.md](CONTRIBUTING.md). Rules and client adapters are the whole point
of this project, so those PRs are the most welcome kind.

## License

MIT
