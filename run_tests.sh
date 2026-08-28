#!/usr/bin/env bash
# Run filter tests with the same Python as the finder (not conda base).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/../.venv/bin/python" ]]; then
  PY="$ROOT/../.venv/bin/python"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  echo "No project .venv found. From this folder run:"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/python -m pip install -r requirements.txt"
  echo "  ./run_tests.sh"
  exit 1
fi

"$PY" -m pip install -q -r requirements-dev.txt
exec "$PY" -m pytest test_filters.py -q "$@"
