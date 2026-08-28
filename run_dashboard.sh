#!/usr/bin/env bash
# Start the CA camping finder locally.
# Usage (from this folder):  ./run_dashboard.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

STREAMLIT=""
if [[ -x "$ROOT/.venv/bin/streamlit" ]]; then
  STREAMLIT="$ROOT/.venv/bin/streamlit"
elif [[ -x "$ROOT/../.venv/bin/streamlit" ]]; then
  STREAMLIT="$ROOT/../.venv/bin/streamlit"
elif command -v streamlit >/dev/null 2>&1; then
  STREAMLIT="$(command -v streamlit)"
fi

if [[ -z "$STREAMLIT" ]]; then
  echo "Streamlit is not installed. From this folder run:"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/python -m pip install -r requirements.txt"
  echo "  ./run_dashboard.sh"
  exit 1
fi

echo "Dashboard will open at http://localhost:8502"
exec "$STREAMLIT" run "$ROOT/dashboard.py" \
  --server.port 8502 \
  --browser.gatherUsageStats false \
  --client.toolbarMode minimal
