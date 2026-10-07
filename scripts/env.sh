# Sourced by check.sh and demo.sh. Interpreter: $PYTHON if set (as in CI), else $PORTFOLIO_VENV/bin/python,
# else ./.venv/bin/python. With none of those, it creates ./.venv from requirements.txt (needs network
# once) and says so; a broken environment stops here instead of reading as a pass.
if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"
elif [ -n "${PORTFOLIO_VENV:-}" ]; then PY="$PORTFOLIO_VENV/bin/python"
elif [ -x .venv/bin/python ]; then PY=.venv/bin/python
else
  base="$(command -v python3.12 || command -v python3.11 || command -v python3 || true)"
  if [ -z "$base" ] || ! "$base" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "error: Python 3.11+ is required (found: ${base:-none})" >&2
    exit 3
  fi
  echo "env.sh: no environment found; creating .venv with $base and requirements.txt" >&2
  "$base" -m venv .venv && .venv/bin/python -m pip install -q -r requirements.txt >&2 || { echo "error: could not create .venv" >&2; exit 3; }
  PY=.venv/bin/python
fi
if ! "$PY" -c "import pandas, numpy, yaml, requests, pytest, hypothesis" 2>/dev/null; then
  echo "error: $PY lacks the pinned packages: $PY -m pip install -r requirements.txt" >&2
  exit 3
fi
export PYTHONPATH=reference
export PYTHONDONTWRITEBYTECODE=1
