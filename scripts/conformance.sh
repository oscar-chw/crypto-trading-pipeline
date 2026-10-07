#!/usr/bin/env bash
# The crypto-desk-blueprint conformance suites (vendored, third_party/crypto-desk-blueprint) against the
# bot's adapters (reference/adapters/impl.py), for the stages the bot implements and nothing else.
# Order: the blueprint's toy (control) and its mutants first, so a pass below means a suite that can fail.
# Then data, every compute_indicators output the strategy and the exits read, strategy, and the
# ExecutionVenue test of stage 07. Any failure, or a run that collects nothing, exits non-zero.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
BP=third_party/crypto-desk-blueprint
export PYTHONPATH="$PWD/reference"
run() { "$PY" -m pytest -q -c "$BP/pyproject.toml" --rootdir "$BP" "$@"; }

echo "== control: blueprint toy, then its mutants"
run "$BP/conformance/stages/test_data.py" "$BP/conformance/stages/test_features.py" \
    "$BP/conformance/stages/test_strategy.py" "$BP/conformance/stages/test_execution.py"
run "$BP/conformance/test_mutants.py"

IMPL=(--impl adapters.impl)
echo "== 01 data: OhlcvDataSource over MarketDataProvider.fetch_ohlcv"
run "$BP/conformance/stages/test_data.py" "${IMPL[@]}"
for f in open high low close volume macd macd_signal macd_hist rsi bb_upper bb_lower bb_mid vol_ma20 \
         open_lag1 close_lag1 macd_hist_lag1 macd_hist_lag2; do
  echo "== 02 features: $f"
  BOT_FEATURE="$f" run "$BP/conformance/stages/test_features.py" "${IMPL[@]}"
done
echo "== 03 strategy: EntryStrategy over bot/strategy.py"
run "$BP/conformance/stages/test_strategy.py" "${IMPL[@]}"
# Stage 07 holds two Protocols. The bot implements ExecutionVenue only (no target-weight Executor),
# so only the test that exercises make_venue runs; README, Roadmap, says why.
echo "== 07 execution venue: BrokerVenue over BacktestBroker"
run "$BP/conformance/stages/test_execution.py::test_fills_pay_costs" "${IMPL[@]}"
echo "conformance.sh: all passed"
