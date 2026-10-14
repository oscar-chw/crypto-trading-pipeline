# Saved-audit inspection contract

User: a developer receiving or revisiting a replay bundle. Problem: reading JSON alone does not
show whether events are missing, fees/account transitions disagree, or the summary belongs to
another run. Input: existing ctp-replay-audit/v1 events.jsonl and summary.json. Output: a concise
human report or JSON consistency report with counts, fees, assumptions and the event-file SHA256.
The inspector is read-only and uses only Python 3.11+ stdlib.

existing: audit.write_audit, runner.emit and BacktestBroker buy/sell,130-bar saved example,
original case/property/integration suites and the unchanged CI/check scripts. There is no existing
saved-artifact consumer. Python's json parser supports duplicate-key hooks and parse_constant;
the documented defaults accept NaN/infinity, so strict inspection needs explicit rejection.
Primary source: https://docs.python.org/3.11/library/json.html . No new dependency or engine.

## Scope fixed before implementation

- CLI: `python -m backtest.inspect RUN_DIR [--json] [--expect-sha256 HEX]`; exit0 on consistency,
  exit2 for unavailable/invalid/inconsistent input. Report names the file and record line/field.
- Exactly one initial run and final completed event; no events after completion. Schema/model
  assumptions must be supported. Required numeric fields must be finite numbers, not booleans.
  JSON objects reject duplicate keys; records and summary have an explicit1MiB byte limit.
- For every declared symbol: exact bar count and indices, strictly increasing open timestamps,
  close=open+declared duration, declared range/gap count, one final flat account. Any liquidation
  follows the last bar with its timestamps. Missing/truncated/malformed records fail.
- An independent arithmetic pass reconstructs fills from the declared mark/slippage/fee model:
  fill_price=mark*(1+slippage) for BUY and mark*(1-slippage) for SELL; fee=rate*(fill_price*qty).
  BUY subtracts notional+fee and adds quantity; SELL adds notional-fee and subtracts quantity,
  matching the existing broker's documented<=1e-12 residual-quantity clamp. An over-budget BUY can
  only have the broker's exact clipped quantity, cash/(price*(1+fee_rate)+1e-12); its binary64
  roundoff is preserved without a new tolerance. Otherwise-consistent interim overdrafts fail.
  Events reconcile with prior state, marked equity, entry/sell counts and final cash/PnL. Binary64 operations use
  the producer's grouping and exact comparisons; no new permissive tolerance is introduced.
- Summary must match completion/per-symbol counts and observed final account result. The tool
  does not independently recompute Sharpe/Sortino/drawdown, verify strategy signals, raw source
  provenance or financial validity. It cannot prove authenticity from self-consistency. A supplied
  trusted event digest additionally verifies byte identity; otherwise report digest_check=not_supplied.
- Keep one state per symbol and stream events. A line bound is not a total-RSS or hostile-parser
  CPU guarantee. Concurrent file mutation during inspection is unsupported. Never repair a bundle.

## Acceptance and controls

Use the actual existing producer with normal130-bar data and boundary short/zero-cost/multi-symbol
cases. Inspect under `python -S` to prove no installed packages are required. Compare with the
independent account oracle on generated paths; check that reading preserves both file hashes.
Adversarial edits individually change fee, fill price, cash, bar count/index/timestamps, summary,
completion, duplicate keys/nonfinite values and a trusted digest. Each must fail with context.
Recovery uses the preserved valid bundle. Prove named checks fail under disposable source mutants.
Run the original full check and review any source change. Local results do not imply a remote CI
run, data authenticity, strategy validity or live-execution approval.
