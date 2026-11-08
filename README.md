# agentcheckup

**MCP tool conflict detector and config auditor for AI agents.** One command reads
the MCP configs you already have, starts the servers they declare, and tells you
where two of them collide — before your agent picks the wrong tool.

> **Not the npm package.** There is an unrelated `agentcheckup` on npm — Node.js,
> different author, different job (it inspects what each coding agent loads from a
> repository). This project is the **Python** package on PyPI:
> `pip install agentcheckup`. Running `npx agentcheckup` gets you the other one.

[![CI](https://github.com/jiaqinq/agentcheckup/actions/workflows/ci.yml/badge.svg)](https://github.com/jiaqinq/agentcheckup/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agentcheckup.svg)](https://pypi.org/project/agentcheckup/)
[![Python](https://img.shields.io/pypi/pyversions/agentcheckup.svg)](https://pypi.org/project/agentcheckup/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

```bash
pip install agentcheckup
agentcheckup
```

```console
agentcheckup 0.8.1  |  2 server(s)  |  4 tool(s)  |  ~442 tokens per request
source: 1 config(s)
coverage: 2/2 server(s) inspected (100%), 0 unverified

  Grade B    Score  88/100   1 error

  CONFLICTS (1)
    AGT201  Tool name 'read_file' is exposed by both 'files' and 'git'.  [files/read_file <-> git/read_file]
            fix: Two servers expose the same name and clients resolve that differently, so the same call can reach either one. Rename one, or use a gateway that prefixes.


  Rule docs: https://github.com/jiaqinq/agentcheckup#rules
```

That output is from two mock servers committed under `tests/fixtures/`, not from a
user's machine — run `agentcheckup` yourself for your own numbers.

## What it does

| | |
|---|---|
| **Cross-server conflicts** | The same tool name in two servers (`AGT201`), the same name once normalised (`AGT202`), overlapping descriptions (`AGT203`), and the same name in two *different clients* (`AGT204`, informational). |
| **MCP config risks** | Unpinned `npx`/`uvx` packages, plaintext credentials, filesystem servers rooted at a volume root, shell wrapping, permission-bypass flags, prompt injection hidden in tool descriptions. |
| **Tool-manifest overhead** | A rough token cost for the manifest your agent re-sends on every request. An estimate from the schemas, not a billed figure. |
| **CI integration** | `--format sarif`, `--fail-on`, `--min-score`, `--baseline`, and a GitHub Action. |

37 rules, zero runtime dependencies, Python 3.10+.

## Who it is for

People running **more than one MCP server** in Claude Desktop, Claude Code, Cursor,
Codex CLI, VS Code, Windsurf, Zed, Continue, Cline, Roo Code or Kilo Code — and who
have hit a moment where the agent called the wrong tool and nothing in the logs
explained why.

If you run a single server, there is nothing here for you: one server cannot
collide with itself.

## How it differs from an MCP protocol validator

A protocol validator checks whether a server speaks MCP correctly. This checks
whether the servers you *already have working* make sense together.

| | agentcheckup | Protocol validator |
|---|---|---|
| Scope | Many servers at once | One server |
| Question | "Can my agent tell these tools apart?" | "Does this server follow the spec?" |
| Output | Conflicts, config risk, token cost | Conformance failures |

It is not a substitute for the official conformance suite, and it does not attempt
to be.

## Documentation

| | |
|---|---|
| [Detecting MCP tool name conflicts](docs/mcp-tool-conflict-detection.md) | What a conflict is, the four rule ids, and the normalisation rules |
| [Auditing MCP server configuration](docs/mcp-configuration-auditing.md) | Every client it finds, the config rules, and what "audit" does not mean |
| [Tool manifest token cost](docs/mcp-tool-manifest-token-cost.md) | How the estimate is produced, and why it is not a bill |
| [GitHub Action reference](docs/github-action.md) | Inputs, outputs, SARIF, auto-discovery in CI |
| [Rule reference](docs/rules.md) | All 37 rules with the reasoning behind each |
| [FAQ](docs/faq.md) | Direct answers, including what the tool does not do |


## Quick start

```bash
# See what would run, and change nothing
agentcheckup audit --dry-run

# Full audit: reads configs, starts servers, reports conflicts
agentcheckup
```

`--dry-run` prints the command line for every server that *would* be started and
exits without executing anything — credentials masked. `--no-spawn` goes further:
it audits the configuration and never starts anything, at the cost of no tool or
conflict findings. `agentcheckup` on its own starts the servers, because
`tools/list` is how a tool manifest is obtained.

## Why cross-server

Two servers cannot see each other. Your model can: it receives one flat list with
every tool from every server, and has no way to know that `files.read_file` and
`git.read_file` are different things.

Three failure modes follow. Most scanners I looked at examine one server at a
time, so none of them see any of these:

**1. Hard collision.** Two servers expose the same tool name. What a client does
about that varies — some keep one and drop the other, some namespace them — but
the outcome is decided by your config rather than by you. If one disappears, you
get to debug "why won't it read the file" while the agent is calling the other.

**2. Soft collision.** Two tools with different names and near-identical
descriptions. The model has to choose from text alone, so the choice is not
predictable from your config. That looks like model flakiness and is not.

**3. Context tax.** An agent re-sends the full tool manifest on **every** request.
A handful of servers with long descriptions is thousands of tokens before the user
says anything. It is rarely budgeted for because it is rarely measured.

`agentcheckup` looks at all three at once, from the configs you already have.

## What it checks

| Layer | Question it answers | Rules |
|---|---|---|
| **Conflicts** | Could my agent pick the wrong tool? | AGT201–AGT204 |
| **Risks** | Is my setup unsafe? | AGT001–AGT108 |
| **Budget** | What does my manifest cost per request? | reported on every run |

37 rules in total. Full reference: [docs/rules.md](docs/rules.md).

## Install

```bash
pip install agentcheckup
# or run without installing
uvx agentcheckup
```

Python 3.10+. **Zero runtime dependencies** — no SDK, no tokenizer, no embeddings.
It reads JSON, starts processes, prints text, and makes no network calls of its
own. It does start the servers your config declares; those can do whatever they
were written to do, which is why `--dry-run` and `--no-spawn` exist.

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

A quick way to keep a manifest from regressing, and the version you pin is
the version you run — the action installs from its own checkout.

```yaml
- uses: jiaqinq/agentcheckup@v0.8.1
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

## One client's `filesystem` is not another's

Cursor and Codex each load only their own config. Two servers with the same name
in different clients are not an unreachable duplicate — nothing ever loads both
lists at once — so that case is reported as information, not as an error:

```
AGT204  Tool name 'read_file' exists in both 'Cursor' and 'Codex CLI'.
        Separate clients, separate configs: they are never loaded together.
```

Within one client the same name is still `AGT201` (error). When the client is
unknown the strict answer wins: better to warn twice than to downgrade a real
collision because a label was missing.

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
- **Codex configs are read the way Codex reads them.** `env_vars` names are
  resolved against your environment at spawn time and never stored or printed;
  `startup_timeout_sec` becomes that server's deadline.
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
