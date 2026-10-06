#!/usr/bin/env bash
# Facetcast one-step launcher: creates .venv, installs dependencies once, opens the dashboard.
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3.10+ is not installed. Get it from https://www.python.org/downloads/"; exit 1
fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "Python 3.10+ needed"; exit 1; }

if [ ! -x .venv/bin/python ]; then
  echo "[1/3] Creating a virtual environment..."
  "$PY" -m venv .venv
fi
if ! cmp -s requirements.txt .venv/.installed; then
  echo "[2/3] Installing dependencies..."
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  cp requirements.txt .venv/.installed
fi
echo "[3/3] Starting Facetcast..."
exec .venv/bin/python facetcast.py serve "$@"
