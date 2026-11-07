# Convenience targets. On Windows, run these from Git Bash, or use the
# equivalent commands printed by scripts/bootstrap.ps1.
#
#   make test    run the suite
#   make lint    ruff
#   make fmt     ruff --fix
#   make run     agentcheckup against the fixtures
#   make clean   drop caches

PY ?= python
SRC := src

.PHONY: help test lint fmt run clean bootstrap

help:
	@echo "targets: test lint fmt run clean bootstrap"

test:
	PYTHONPATH=$(SRC) $(PY) -m pytest -q

lint:
	$(PY) -m ruff check .

fmt:
	$(PY) -m ruff check . --fix

run:
	PYTHONPATH=$(SRC) $(PY) -m agentcheckup scan tests/fixtures/bad_tools.json --fail-on never

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

bootstrap:
	bash scripts/bootstrap.sh
