## What this changes

<!-- One or two sentences. Link the issue if there is one. -->

Closes #

## Type

- [ ] New rule
- [ ] Rule fix (false positive / false negative / severity)
- [ ] Loader or output format
- [ ] Docs
- [ ] Refactor (no behaviour change)

## If this adds a rule

- Rule id:
- Severity:
- What it catches:
- **What legitimate input it might wrongly flag, and how you narrowed it:**

## Checklist

- [ ] `pytest` is green
- [ ] `ruff check .` is clean
- [ ] A test covers the new behaviour (both a positive and a negative case)
- [ ] No new runtime dependency
- [ ] `docs/rules.md` updated (for rule changes)
- [ ] Rule id is unused — checked with `agentcheckup rules`
- [ ] Severity is honest: `error` means "breaks a run or endangers the host"

## Notes for the reviewer

<!-- Anything you are unsure about. Saying "I'm not confident about the
     false-positive rate here" is more useful than silence. -->
