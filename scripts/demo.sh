#!/usr/bin/env bash
# Offline demo, no API keys, under a minute: write SYNTHETIC hourly candles, replay them through the
# live bot's decision code with the backtester, and fail unless the result matches the committed
# reference/results/synthetic-backtest.json (timings excluded) and at least one trade happened.
#   bash scripts/demo.sh            run and compare
#   bash scripts/demo.sh --update   rewrite reference/results/synthetic-backtest.json from this run
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
"$PY" -m backtest.synthetic "$out/data" --bars 1500 --seed 7
"$PY" -m backtest.runner --data "$out/data" --out "$out/summary.json" >/dev/null

if [ "${1:-}" = --update ]; then
  cp "$out/summary.json" reference/results/synthetic-backtest.json
  echo "demo.sh: wrote reference/results/synthetic-backtest.json"
fi

"$PY" - "$out/summary.json" reference/results/synthetic-backtest.json <<'PYEOF'
import json, sys
new, ref = (json.load(open(p)) for p in sys.argv[1:3])
agg = new["aggregate"]
print(f"SYNTHETIC data: {agg['symbols']} symbols x {agg['bars'] // agg['symbols']} hourly bars, "
      f"{agg['bars']} bars in {agg['seconds']:.2f} s ({agg['bars_per_second']:.0f} bars/s on this machine)")
for sym, m in new["per_symbol"].items():
    print(f"  {sym:10s} entries={m['entries']:3d} sells={m['sells']:3d} exits={m['exit_reasons']}")
trades = sum(m["entries"] for m in new["per_symbol"].values())
for d in (new, ref):
    for k in ("seconds", "bars_per_second"):
        d["aggregate"].pop(k)
if trades == 0:
    sys.exit("demo.sh: FAIL, the backtest opened no position: the signal path is broken")
if new != ref:
    sys.exit("demo.sh: FAIL, the result differs from reference/results/synthetic-backtest.json")
print("demo.sh: matches reference/results/synthetic-backtest.json (P&L figures on synthetic data mean nothing and are not quoted)")
PYEOF
