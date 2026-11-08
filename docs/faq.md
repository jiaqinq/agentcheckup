# FAQ

## What is agentcheckup?

An open-source Python CLI and GitHub Action that audits MCP (Model Context
Protocol) configurations for AI agents. It does three things:

1. **Cross-server tool conflict detection** — the same tool name exposed by two
   servers, or two tools whose descriptions overlap enough that a model cannot
   reliably tell them apart.
2. **Configuration risk auditing** — unpinned packages, plaintext credentials,
   filesystem servers rooted at a volume root, prompt injection hidden in
   descriptions, and similar.
3. **Tool-manifest token estimation** — a rough figure for what your agent re-sends
   on every request.

Zero runtime dependencies. Python 3.10+.

## Is this the same as the `agentcheckup` npm package?

No. They are different projects by different authors:

| | this project | the npm one |
|---|---|---|
| Install | `pip install agentcheckup` | `npx agentcheckup` |
| Language | Python 3.10+ | Node.js 22.12+ |
| Job | Cross-server tool conflicts, config risk, manifest cost | What each coding agent loads from a repository |
| Source | [jiaqinq/agentcheckup](https://github.com/jiaqinq/agentcheckup) | a different repository |

The npm package was published first; the name was not available there. If a search
result sent you to the wrong one, that is why.


## Who is it for?

People running more than one MCP server in Claude Desktop, Claude Code, Cursor,
Codex CLI, VS Code, Windsurf, Zed, Continue, Cline, Roo Code or Kilo Code — and
who have hit a moment where the agent called the wrong tool and nothing in the logs
explained why.

If you run one server, there is nothing here for you: a single server cannot
collide with itself.

## Is it an MCP server linter?

Partly. It lints the *tool definitions* a server publishes — names, descriptions,
schemas, annotations — with 24 rules, plus 6 suite-level rules that only make sense
across several servers, and 7 on the configuration itself. 37 in total.

It does not lint server source code, and it does not check the protocol handshake
against the specification. For protocol conformance, the official conformance suite
is the right tool.

## How does conflict detection work?

Token-set Jaccard similarity. No embeddings, no model, no network.

```
name_sim = J(name_tokens(a), name_tokens(b))
desc_sim = J(tokens(a.description), tokens(b.description))
blended  = 0.45 * name_sim + 0.55 * desc_sim
```

Names are split on camelCase, PascalCase, separators and plural stems, so
`readFiles`, `read_files` and `Read-Files` all reduce to `{read, file}`. Chinese
names become character bigrams.

Full detail: [detecting MCP tool name conflicts](mcp-tool-conflict-detection.md).

## Does a name collision break the agent?

Not necessarily, and the tool does not claim it does. The MCP specification scopes
name uniqueness to a single server and says aggregating clients **MAY** hit
collisions and **SHOULD** disambiguate. What a given client does — keep the first,
keep the last, namespace, or show both — is up to that client.

`agentcheckup` reports the collision and lets you decide. An earlier version of this
project asserted that one tool "becomes unreachable"; that was a guess, and it was
removed in 0.4.2.

## Can it predict which tool my model will pick?

No, and it does not try. Similarity is a property of the text, not a probability of
a model's choice. Measuring the latter needs a model-calling experiment with a
labelled set of near-duplicate tools; that experiment has not been run here.

## How accurate is it?

44 hand-labelled tool pairs (20 positive, 24 negative):

| | |
|---|---|
| precision | 0.952 |
| recall | 1.000 |

The labels are the author's. The one disagreement is a pair where the detector is
arguably right and the label strict. Reproduce with `python scripts/benchmark.py`.

## Does it need network access?

It makes no network calls of its own — no telemetry, no API, no upload. Your
configuration never leaves the machine.

It *does* start the servers your config declares, and those processes can do
whatever they were written to do. That is why these exist:

```bash
agentcheckup audit --dry-run   # print the commands, execute nothing
agentcheckup audit --no-spawn  # audit the config only, no tools, no conflicts
```

## How do I use it in CI without failing on existing problems?

Record a baseline, then fail only on new findings:

```bash
agentcheckup audit --write-baseline .agentcheckup-baseline.json
agentcheckup audit --baseline .agentcheckup-baseline.json
```

Commit the baseline file. Regenerate it as you fix things, so the list only shrinks.

## Does it work with Chinese tool descriptions?

Yes, since 0.4.3. Before that, the tokeniser matched `[a-z0-9]+` only, so every
Chinese description produced an empty token set and two Chinese tools could never be
compared — silently, with no error.

Names are now split into character bigrams: `读取文件` → `读取`, `取文`, `文件`.

## Why is my server reported as unverified?

It did not answer `tools/list` within the timeout. Common causes: a missing
credential in the environment, a remote `url` endpoint that cannot be introspected
over stdio, or a slow start.

The report separates this from "clean":

```
coverage: 2/3 server(s) inspected (67%), 1 unverified
```

An unverified server is not a clean server. Raise the timeout with `--timeout`, or
set `startup_timeout_sec` in a Codex config to give one server more room.

## Why are two servers in different clients not flagged as a conflict?

Because they are never loaded together. Cursor and Codex each read their own
config. The same tool name in both is reported as `AGT204` (info), not `AGT201`
(error). Within one client it is still an error.

## What is it not?

- Not a vulnerability scanner. No CVE checks, no advisory database.
- Not a proxy or gateway. It does not sit between your agent and the servers.
- Not a protocol validator. It does not check the handshake against the spec.
- Not runtime protection. It diagnoses a configuration; it does not enforce
  anything while the agent runs.

## Where do I report a bug?

[Issues](https://github.com/jiaqinq/agentcheckup/issues). For a false positive, the
most useful thing is the two tool names and descriptions with secrets removed —
that is enough to reproduce.
