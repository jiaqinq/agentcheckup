# Security Policy

## What agentcheckup does with your data

Nothing leaves your machine.

- No network calls, at any point, for any command.
- No telemetry, no analytics, no update check.
- `agentcheckup scan --cmd` starts the server you name as a local subprocess. It sends
  exactly two JSON-RPC messages (`initialize`, `tools/list`) and then terminates
  the process.
- Nothing is written to disk except what you redirect to stdout.

## Reporting a vulnerability

Use GitHub's private advisory flow:
`https://github.com/wanjiaqing/agentcheckup/security/advisories/new`

Please do not open a public issue for a vulnerability. Expect an initial response
within 7 days.

## Threat model

agentcheckup is a **static analyser for manifests and configs**. It is not a sandbox
and not a runtime guard.

**In scope:**

- A rule that silently fails to detect the pattern it claims to detect.
- ReDoS in a rule's regex (a crafted manifest hanging the linter).
- Path traversal or arbitrary file read via a loader argument.
- A `--cmd` invocation that executes more than the named server.
- Output injection: a crafted tool name or description that manipulates the
  report itself (terminal escape sequences, invisible characters rendered raw).

**Out of scope:**

- A malicious MCP server doing bad things at runtime. agentcheckup tells you the
  manifest looks risky; it cannot stop the server.
- Vulnerabilities in the server you are linting.
- Detection bypass by an adversary who has read the rule source. This is a linter,
  not an adversarial detector — heuristics are public by design.

## A note on the `--cmd` flag

`--cmd` takes a shell string and is therefore equivalent to running that command
yourself. Do not pass untrusted input to it. This is documented in `--help`.

## Supported versions

The latest release. Fixes ship as a patch release; there are no long-term
support branches while the project is pre-1.0.
