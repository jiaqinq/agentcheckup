# Contributing to agentcheckup

The most useful contribution is **a new rule**. This document is written so that
your first one takes about ten minutes.

## Setup

```bash
git clone https://github.com/wanjiaqing/agentcheckup
cd agentcheckup
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install pytest ruff
pytest            # should be green before you change anything
```

No `pip install -e .` needed — `conftest.py` puts `src/` on the path.

## Add a rule in ten minutes

**1. Pick an unused id.** Groups: `AGT0xx` for tool rules, `AGT1xx` for client
config rules. Run `agentcheckup rules` to see what is taken.

**2. Write the rule.** One function, one decorator, in the file that matches the
group (`naming.py`, `docs.py`, `schema.py`, `safety.py`, `injection.py`,
`config_rules.py`):

```python
from ..models import Finding, Severity, Tool
from .base import tool_rule


@tool_rule("AGT015", Severity.WARNING, "Description contains a TODO placeholder")
def todo_placeholder(tool: Tool):
    """Placeholder text ships to production more often than anyone admits.

    The model reads "TODO: describe this tool" as the actual instruction.
    """
    if "TODO" in tool.description.upper():
        return Finding(
            rule="AGT015",
            severity=Severity.WARNING,
            message=f"Tool {tool.name!r} description still contains a TODO.",
            tool=tool.name,
            hint="Write the real description before publishing the server.",
        )
    return None
```

**3. Add a test.** In `tests/test_agentcheckup.py`:

```python
def test_todo_placeholder():
    report = lint_tools([make_tool(description="TODO: describe this tool. " + "x" * 40)])
    assert "AGT015" in rule_ids(report)
```

**4. Run the checks.**

```bash
pytest
ruff check .
```

**5. Open the PR.** Use the template. One rule per PR keeps review fast.

## Rule quality bar

A rule is accepted when it satisfies all four:

- **False positives are rare.** A linter people mute is a linter nobody runs. If
  your heuristic misfires on plausible legitimate input, narrow it — a closed
  allow-list beats a clever regex.
- **The finding has a fix.** `hint` must tell the author what to change, not
  restate the problem.
- **The id is stable and never reused.** `AGT015` means one thing forever.
- **Severity is honest.** `error` = will break or endanger a run. `warning` =
  likely to cause wrong behaviour. `info` = a human should decide. Do not use
  `error` to mean "I feel strongly".

## Adding an output format or a loader

Both are welcome, and both need a test that exercises a real fixture in
`tests/fixtures/`. Do not add a runtime dependency — the zero-dependency
guarantee is a feature, not an accident.

## The two easiest places to help

**Client adapters.** Every client invents its own config filename and nesting.
`src/agentcheckup/discovery.py` has one list; adding Cursor's newer layout, Zed,
JetBrains, or whatever shipped last week is a ten-line PR plus a fixture. This is
the highest-value contribution because coverage is what makes "one command" true.

**Conflict heuristics.** `src/agentcheckup/conflicts.py` scores tool pairs. The
current approach is token Jaccard with a shared-head-noun guard. If you have a
better signal that stays dependency-free — a different weighting, a synonym list,
a schema-overlap term — open an issue with two or three real tool pairs it fixes
and two it must not break. **A heuristic PR that improves recall but adds false
positives will be declined**: a noisy report gets muted, and a muted report is
worth nothing.

## What will be declined

- Rules that need network access or an LLM call.
- Rules that only fire on synthetic input nobody writes.
- Anything that phones home. This tool never sends your manifest anywhere.
- Style preferences dressed up as correctness. `info` at most.

## Commit messages

Conventional Commits, scoped by area:

```
feat(rules): add AGT015 for TODO placeholders in descriptions
fix(loader): tolerate servers that log to stdout
docs(rules): explain why AGT030 is a warning
```

## Code of conduct

Be decent. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
