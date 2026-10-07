#!/usr/bin/env bash
# Ruff, mypy, every test tier, the blueprint conformance suites, then the offline demo. Exits 0 only if all pass.
# A tier that collects zero tests FAILS (pytest exit 5): an empty suite reporting green is not a pass.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

echo "== ruff"
"$PY" -m ruff check --config ruff.toml .
echo "== mypy"
"$PY" -m mypy

for tier in case integration property; do
  echo "== reference/tests/$tier"
  "$PY" -m pytest -q -m "$tier" "reference/tests/$tier" || { echo "check.sh: tier '$tier' failed or collected no tests"; exit 1; }
done

echo "== conformance"
bash scripts/conformance.sh

echo "== demo"
bash scripts/demo.sh
echo "check.sh: all passed"
