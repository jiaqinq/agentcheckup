# Detecting MCP tool name conflicts across servers

**Short answer:** two MCP servers can expose the same tool name. A client that
loads both has to decide what to do about it, and that decision is made by the
client, not by you. `agentcheckup` reads your configs, starts the servers, and
reports every name that appears twice — before your agent runs into it.

```bash
pip install agentcheckup
agentcheckup
```

## What a conflict actually is

Each MCP server publishes a tool list with `tools/list`. Nothing in the protocol
makes those names unique *across* servers — the specification scopes uniqueness to
a single server and explicitly notes that aggregating clients "**MAY** encounter
naming collisions" and "**SHOULD** implement a disambiguation strategy".

So when `files` exposes `read_file` and `git` also exposes `read_file`, both are
valid servers doing valid things. The problem only exists in the client, which
receives one flat list and has to pick.

What the client does about it varies:

- keep the first and drop the second,
- keep the last and drop the first,
- prefix or namespace them,
- show both and let the model choose by description.

The specification does not mandate any of these. `agentcheckup` therefore reports
the collision rather than promising a particular outcome — an earlier version of
this project claimed "the client keeps one and the other is unreachable", which
was a guess dressed up as a fact.

## Five kinds, five rule ids

| Rule | Severity | Condition |
|---|---|---|
| `AGT201` | error | Byte-identical names in two servers of the **same client** |
| `AGT202` | warning | Names that differ but normalise to the same tokens |
| `AGT203` | warning | Different names, descriptions that overlap heavily |
| `AGT204` | info | Same name, but in **different clients** |
| `AGT205` | info | Same server name at **two scopes** of one client |

`AGT204` exists because Cursor and Codex never load each other's config. The same
name in both is not an unreachable duplicate, and reporting it as one is a false
positive on the most common multi-client setup.

`AGT205` covers the other near-miss: a user-level and a project-level config of the
*same* client, both declaring `filesystem`. Claude Code documents its order
(Local > Project > User) and the losing entry is dropped before the manifest is
built, so what is left is a note saying which one won. Cursor and VS Code read both
files but document no rule for a duplicate name; that stays a note too, because
guessing would either hide a collision or invent one.

## How names are normalised

`readFiles`, `read_files`, `read-files` and `Read.Files` are four spellings of the
same tool, and a model reading a flat list will treat them as the same thing.

```
readFiles   -> {read, file}      camelCase split, acronym runs included
read_files  -> {read, file}      separators are token boundaries
Read.Files  -> {read, file}      case folded, dots split
parseHTML   -> {parse, html}     not {p, a, r, s, e, h, t, m, l}
```

Chinese names are tokenised as character bigrams, because there are no spaces to
split on and a real segmenter would be a runtime dependency:

```
读取文件 -> {读取, 取文, 文件}
```

Without that, every Chinese tool name produced an empty token set and two Chinese
tools could never be compared at all — it failed silently, which is the worst way
to fail.

## How descriptions are compared

Token-set Jaccard similarity, no embeddings and no model:

```
name_sim = J(name_tokens(a), name_tokens(b))
desc_sim = J(tokens(a.description), tokens(b.description))
blended  = 0.45 * name_sim + 0.55 * desc_sim
```

A pair is `AGT203` when the two names share at least one token **and** either
`desc_sim >= 0.65` or `blended >= 0.55`.

The shared-token requirement is what keeps `search_repositories` and
`search_documents` apart. Without it, every pair of tools that mentions "search"
was flagged, and the report became unreadable — which is worse than no report.

## What it will not do

- It does not predict which tool your model will pick. Similarity is a property of
  the text, not a probability of a model's choice. No such experiment exists in
  this project.
- It does not understand synonyms. `fetch` and `retrieve` are different tokens and
  will not match.
- It does not detect resource conflicts (two tools writing the same file).
- It is a heuristic. The thresholds are hand-tuned against a labelled set, not
  derived from theory.

## How accurate is it

44 hand-labelled tool pairs — 20 that should be flagged, 24 that should not:

| | |
|---|---|
| precision | 0.952 |
| recall | 1.000 |

The labels are the author's, and the single disagreement is a pair where the
detector is arguably right. Reproduce with `python scripts/benchmark.py`.

## See also

- [Rule reference](rules.md) — every rule, with the reasoning
- [Configuration auditing](mcp-configuration-auditing.md) — the other half of the tool
- [Repository](https://github.com/jiaqinq/agentcheckup) · [PyPI](https://pypi.org/project/agentcheckup/)
