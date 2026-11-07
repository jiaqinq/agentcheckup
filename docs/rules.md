# Rule reference

Every rule has a stable id. Ids are never reused or renumbered; a suppression or
a CI threshold that worked in 0.1.0 keeps working in 1.0.

Severity ladder:

| Severity | Means | Score impact |
|---|---|---|
| `error` | Will break a run, or endangers the host | 10 points |
| `warning` | Likely to cause wrong behaviour | 3 points |
| `info` | A human should decide | 1 point, capped at 10 total |

The budget is 20 points per tool, so score reflects finding *density* rather than
manifest size. Info findings are capped because a rule that fires on nearly every
real tool expresses a preference, not a defect.

Grade: A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, F < 60.

---

## Naming

### AGT001 · error · Tool name is not a valid MCP identifier
Names must be 1–64 characters of `[A-Za-z0-9_-]`. Anything else is rejected by
strict clients and silently mangled by lenient ones, which surfaces later as a
"tool not found" error the model cannot recover from.

### AGT002 · info · Tool name is not snake_case
Mixed `readFile` / `read_file` / `ReadFile` in one manifest makes near-duplicate
names harder to tell apart. The model sees them all at once.

### AGT003 · info · Tool name repeats the server/domain name
`github_get_issue` inside the `github` server pays for the prefix on every
request; the client already namespaces by server. Uses a closed list of known
prefixes — a length heuristic produced too many false positives to be useful.

### AGT004 · error · Tool name is duplicated
Clients keep one and drop the rest, non-deterministically. Which one survives is
an implementation detail you should not be betting on.

---

## Documentation

### AGT010 · error · Tool has no description
The tool still appears in the manifest and can still be called. Selection becomes
a coin flip against every other tool.

### AGT011 · info · Tool description is too short
Under ~40 characters there is no room for *when* to use it or *what* it returns.

### AGT012 · info · Description never says when NOT to use the tool
Disambiguation is what separates a reliable tool set from a lucky one. One clause
is enough: *"Use this only for public repos; prefer `get_private_repo` for
authenticated access."*

### AGT013 · warning · Input parameters are undocumented
Each undocumented parameter is a decision the model makes blind — and a likely
retry loop.

### AGT014 · info · Description does not state the return shape
The model plans the *next* call from what it expects back. *"Returns a JSON array
of {id, title}"* is worth more than another sentence about parameters.

---

## Schema

### AGT020 · error · `inputSchema` is not an object schema
MCP tool arguments are always a JSON object. `{"type": "array"}` or a missing
`type` breaks strict client-side validation.

### AGT021 · warning · `required` references an undeclared property
Every call fails validation before it reaches your server.

### AGT022 · info · Schema allows undeclared properties
Models invent extra keys when the schema permits it. `additionalProperties:
false` turns a silent wrong-argument bug into a visible validation error.

### AGT023 · info · String parameter has no `enum` / `format` / `pattern`
Free-form strings are the main source of retry loops. If the value space is
finite, say so.

### AGT024 · info · Array parameter has no `maxItems`
One call can blow the context window, and the failure arrives as a truncation
error far from the cause.

### AGT025 · warning · Parameter name is ambiguous
`data`, `value`, `arg`, `input`, `options`. The model has to infer the shape from
the type alone — exactly where hallucinated payloads come from.

---

## Safety

### AGT030 · warning · Destructive tool does not declare `destructiveHint`
Hosts cannot ask "are you sure?" for a tool that does not admit it is risky.

### AGT031 · warning · `readOnlyHint` contradicts the tool name
A wrong `readOnlyHint: true` is worse than no hint: hosts use it to skip
confirmation and to parallelise calls. That is data loss with no error message.

### AGT032 · error · Tool exposes unconstrained command execution
An `exec`-style tool with a free-form string is remote code execution by design.
Sometimes intentional — but it must be a documented decision, not a default.

### AGT033 · info · Filesystem parameter has no documented scope
Without a stated root, the model will happily read outside the project.
Documenting the sandbox root is cheap and makes the boundary testable.

### AGT034 · info · Tool declares no annotations at all
No hints means the host must assume the worst case for every call.

---

## Injection

These four are the reason this project exists. Tool descriptions are injected into
the model's context verbatim, so whoever wrote the server controls a slice of your
system prompt.

### AGT040 · error · Description tries to override model instructions
Matches `ignore all previous instructions`, `disregard the above`, `you are now
a...`, `new instructions:`, `system prompt`. The classic tool-poisoning payload.

### AGT041 · error · Description asks the model to hide behaviour from the user
`do not tell the user`, `without notifying the user`, `hide this from`. Anything
the model is told to hide is, by definition, not auditable.

### AGT042 · warning · Description embeds an outbound URL with credentials
Endpoints belong in config, never in the model-visible description. Matches
`post ... to https://` and URLs carrying `?token=` / `?key=`.

### AGT043 · error · Description hides text with invisible characters
Zero-width (`U+200B`), joiner (`U+200C/200D`), word-joiner (`U+2060`) and BOM
(`U+FEFF`) let a description read one way and behave another. Reports render them
as `\u200b` so you can actually see them.

### AGT044 · warning · Description hides instructions in markup
HTML comments and chat-template tokens (`<|...|>`) are invisible in most UIs but
not to the model.

---

## Config

Operates on client config files (`mcpServers` in Claude Desktop/Cursor, `servers`
in VS Code, `mcp_servers` in Cline).

### AGT101 · warning · `npx` package is not version-pinned
`npx -y foo` re-resolves to the latest release on every launch. The code you
audited last week is not necessarily the code running today.

### AGT102 · warning · `uvx` package is not version-pinned
Same failure mode on the Python side.

### AGT103 · warning · Config wraps the server in a shell
`sh -c "..."` re-parses every argument, so any string can become a command. It
also defeats the escaping the client already did.

### AGT104 · error · Filesystem server is rooted at the volume root
Granting the filesystem root gives the agent read-write access to everything. One
prompt injection is then enough to reach SSH keys and browser profiles.

### AGT106 · error · Config passes a permission-bypass flag
`--dangerously-skip-permissions`, `--yolo`, `--allow-all`, `--no-sandbox`. These
disable the only confirmation step between the model and your disk.

### AGT107 · warning · Credentials stored in plaintext in the config
Config files get committed, screenshotted and pasted into issues. Reference an
env var instead.

### AGT108 · warning · Remote server uses plain HTTP
Tool calls carry your data, often your credentials, over an unencrypted link.

### AGT105 · info · Server did not return a tool list
The server failed to start, timed out, or is a remote `url` endpoint that cannot
be introspected over stdio.

This is info rather than an error on purpose: one broken server must not
stop you auditing the other four. But an unreachable server is also an unaudited
one — its tools were never checked for conflicts.

---

## Conflicts

These are the rules that need more than one server. They are the reason this tool
exists: a single server cannot see another server, but your model sees all of
them at once, flattened into one list.

### AGT201 · error · Same tool name exposed by two servers
A hard collision. The client keeps one and the other becomes unreachable — no
error, no warning, just a tool that never gets called. This is the bug that costs
an afternoon.

### AGT202 · warning · Two servers expose the same name once normalised
`read_file` and `readFiles` are different strings but the same word to a model
reading a flat list. Flagged separately from AGT201 because the fix is different:
rename one so the *name alone* disambiguates.

### AGT203 · warning · Two servers expose overlapping tools
The soft case: different names, but descriptions that overlap ≥ 65% and a shared
head noun. Selection becomes a coin flip that presents as model flakiness.

The shared-noun requirement is deliberate. Without it, `search_repositories` and
`search_documents` get flagged for both containing the word "search", and a
report full of noise is worse than no report at all.
