#!/usr/bin/env bash
# Recreate the dev environment for agentcheckup (macOS / Linux / Git Bash).
#
# The environment lives inside this folder so the whole tree can be copied to
# another machine. If the path changes, run this again.
#
#   bash scripts/bootstrap.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
echo "==> project root: $ROOT"

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$("$candidate" --version 2>&1 || true)"
    case "$version" in
      *"Python 3."*)
        minor="$(printf '%s' "$version" | sed -E 's/.*Python 3\.([0-9]+).*/\1/')"
        if [ "${minor:-0}" -ge 10 ] 2>/dev/null; then
          PYTHON="$candidate"
          echo "==> using $candidate ($version)"
          break
        fi
        ;;
    esac
  fi
done

if [ -z "$PYTHON" ]; then
  echo "error: no Python 3.10+ found. Install it first." >&2
  exit 1
fi

if [ -d .venv ]; then
  echo "==> removing existing .venv (fixes a changed path)"
  rm -rf .venv
fi

"$PYTHON" -m venv .venv

if [ -x .venv/bin/python ]; then
  VENV_PY=".venv/bin/python"
else
  VENV_PY=".venv/Scripts/python.exe"
fi

"$VENV_PY" -m pip install --upgrade --quiet pip
"$VENV_PY" -m pip install --quiet pytest ruff

echo
echo "==> environment ready"
echo "    activate:  source .venv/bin/activate"
echo "    test:      $VENV_PY -m pytest -q"
echo "    lint:      $VENV_PY -m ruff check ."
echo "    run:       PYTHONPATH=src $VENV_PY -m agentcheckup rules"
