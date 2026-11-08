# What an MCP tool manifest costs in tokens

**Short answer:** every MCP client sends the full tool manifest on every request.
`agentcheckup` estimates that cost from your actual tool definitions, so you can
see what your agent pays before the user says anything.

```console
$ agentcheckup
agentcheckup 0.8.1  |  3 server(s)  |  18 tool(s)  |  ~3,336 tokens per request
```

## Why it matters

A tool definition is not free context. Each one carries a name, a description, and
a JSON Schema for its parameters — and all of it is re-sent on every turn.

The three official servers (`mcp-server-fetch`, `-git`, `-time`) expose 18 tools
between them and estimate at roughly **3,300 tokens per request**. A dozen servers
with verbose schemas gets expensive fast, and it is the kind of cost that never
appears on an invoice, so it never gets budgeted for.

## How the estimate is produced

No tokenizer dependency. `tiktoken` ships per-platform native wheels and downloads
model data on first use, which is a bad trade for a CLI that has to run in CI on
arbitrary machines.

```
CJK characters         1 token each
everything else        max(1, round(characters / 4))
```

The `max(1, ...)` keeps a string of one or two non-CJK characters from rounding to
zero. The manifest is serialised as compact JSON and the rule is applied to the
result. JSON punctuation is denser than prose, so this runs slightly conservative.

## What the number is not

- **Not a billed figure.** It is an estimate from your schemas, not a tokenizer
  count and not an invoice.
- **Not necessarily every request.** Some clients cache the manifest, compress it,
  or send a subset. Whether the manifest is re-sent, and how, is a client decision.
- **Not comparable across models.** Different tokenizers give different counts for
  the same text; the 4-characters-per-token average holds for English prose in the
  cl100k/o200k families, not universally.

Use it to compare two configurations, or to notice that one server's schemas cost
more than the other five combined. Do not quote it as an exact bill.

## Where the cost comes from

In practice the descriptions dominate, not the names. A schema with ten parameters
each carrying a paragraph of `description` costs several times what the same schema
costs with one-line descriptions.

If a server is expensive and you cannot remove it, the cheap fix is usually to
shorten parameter descriptions rather than to drop tools — but that is a judgement
call, and `agentcheckup` only reports the number.

## Related rules

`AGT011` (description too short) and `AGT014` (return shape not stated) push in the
opposite direction from cost: they ask for *more* description, because an
undescribed parameter makes the model guess. Both are `info`, and the scoring caps
how much `info` findings can cost, so a verbose manifest is not penalised for being
verbose.

## See also

- [Conflict detection](mcp-tool-conflict-detection.md)
- [Configuration auditing](mcp-configuration-auditing.md)
- [Repository](https://github.com/jiaqinq/agentcheckup) · [PyPI](https://pypi.org/project/agentcheckup/)
