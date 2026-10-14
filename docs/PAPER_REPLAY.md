# Inspect a candle replay, decision and simulated fill

Use this workflow to diagnose imported OHLCV data and the existing strategy/broker path without
network access. The example is 130 seeded SYNTHETIC hourly bars, not market performance evidence.
Replace it with your own licensed data in the same format. No exchange or model is contacted.

## Input contract

One UTF-8 CSV per enabled symbol; `BTC/USDT` maps to `BTC_USDT.csv`. The header has exactly
`ts,open,high,low,close,volume` (column order can vary). Example:

```csv
ts,open,high,low,close,volume
1735689600000,100,101,99,100.5,10
1735693200000,100.5,102,100,101,12
```

`ts` is a nonnegative integer UTC millisecond **bar-open** timestamp, strictly increasing, within
the supported UTC datetime range. Prices are finite and positive. High must contain open/close/low;
low must not exceed open/close. Volume is finite and nonnegative. Missing cells, duplicate timestamps,
non-numeric values, NaN/infinity, impossible ranges and unexpected columns are rejected. Errors name
the file, physical CSV line and relevant field. Nothing is dropped, interpolated or repaired.

Set the replay `--timeframe` to the actual bar duration (default: the configuration's primary
timeframe). Gaps are allowed and counted as `nonstandard_intervals` in the audit manifest. A gap
still leaves a gap; indicator lookbacks count bars and summary annualization assumes the declared
timeframe. Do not interpret irregular-input ratios as measured financial performance.

Configuration chooses enabled symbols. An enabled symbol without a file is explicitly reported
on stderr and under `missing_symbols`; a run with no usable symbols returns 2. The example config
enables BTC/USDT only. Fee rate is per side in `[0,1)`, slippage basis points in `[0,10000)`, and
starting cash must be finite and nonnegative. These are simulator inputs, not venue estimates.

## Run the supported path

From the repository root after installing requirements into `.venv`:

```bash
PYTHONPATH=reference .venv/bin/python -m backtest.runner \
  --data examples/paper-replay --config examples/paper-replay/config.yaml \
  --audit /tmp/ctp-paper-replay
```

`--audit` selects a **new directory** whose parent already exists. It is an alternative to `--out`,
which retains the summary-only interface. Existing run directories are refused; choose a new name
to compare another run. Config/input files cannot be used as summary output paths.

The directory appears only after successful replay and contains:

| File / record | What to inspect |
|---|---|
| `events.jsonl`, first `run` record | Schema `ctp-replay-audit/v1`, configuration hash, parsed-candle hashes, ranges, gaps, missing symbols, costs and fill/cash assumptions |
| One `bar` record per input bar | Symbol/index, open and calculated close timestamps, signal flags, entry decision/reason, actual simulated fills, cash/quantity before and after, marked equity |
| Optional `liquidation` record | The existing runner's forced end-of-data exit, distinct from a strategy decision at the last bar |
| Final `completed` record | Per-symbol results and processed counts; elapsed wall time is excluded so the event bytes are deterministic |
| `summary.json` | Existing per-symbol metrics and aggregate runtime, including its original simulation limitations |

Each candle is passed through the same indicator and entry functions used by the live loop.
`entry_signal` is `null` when entry was not evaluated (warm-up or an open position). `signals`
explains the enabled checks when entry was evaluated. The first 30 bars are warm-up; they still
appear in the log. Fills come from the existing BacktestBroker's trade ledger. Their `ts` remains
the historical runner's bar-open index; the enclosing event states the bar-close availability
explicitly. An end-of-data liquidation can therefore share the final bar's timestamps.

To inspect only events containing fills:

```bash
python3 - /tmp/ctp-paper-replay/events.jsonl <<'PY'
import json, sys
for line in open(sys.argv[1]):
    event = json.loads(line)
    if event.get("fills"):
        print(event["bar_index"], event["decision"], event["reason"],
              event["fills"], event["cash_after"], event["quantity_after"])
PY
```

The manifest hashes the parsed rows actually supplied to the engine and canonical configuration,
not raw CSV formatting. Preserve the source revision and input files alongside a run;
[validation.json](validation.json) records the checked source pins and local verification scope.

## Inspect a saved run without the trading dependencies

The read-only inspector needs Python 3.11+ and the repository source; pandas, NumPy and installed
site packages are unnecessary. After producing or copying a run bundle:

```bash
PYTHONPATH=reference python3 -S -m backtest.inspect /tmp/ctp-paper-replay
PYTHONPATH=reference python3 -S -m backtest.inspect /tmp/ctp-paper-replay --json
```

The report identifies each symbol's processed bars, buys, sells, fees and final cash/quantity,
the fill/account assumptions and the event-file SHA256. It checks the saved event sequence and
independently reconstructs execution costs, cost basis and account transitions; final counts and
cash/PnL must agree with the completion record and summary. It preserves both input file hashes.

Use a digest received from a separately trusted receipt when byte identity matters:

```bash
PYTHONPATH=reference python3 -S -m backtest.inspect /tmp/ctp-paper-replay \
  --expect-sha256 YOUR_64_CHARACTER_EVENT_SHA256
```

A successful check reports `digest_check=matched`; without an expected digest it reports
`not_supplied`. Consistency alone cannot prove data authenticity or that the strategy is sound.
Sharpe, Sortino and drawdown are not independently recomputed by this tool. No source file or
audit record is repaired or rewritten.

The inspector rejects duplicate JSON keys, nonfinite numbers, missing/completed records in the
wrong order, impossible accounting and unsupported model assumptions. It reads at most 1 MiB
for one event or summary before refusing oversized input. That limit does not guarantee total
process memory or hostile-parser CPU usage. Keep bundles immutable while inspecting them.

| Symptom | Meaning and recovery |
|---|---|
| `events.jsonl:N: fee`, `price`, `cash_after`, `quantity_after` or `pnl` mismatch | A saved transition disagrees with the declared model. Preserve the damaged bundle; regenerate from the original CSV/config/revision into a new run directory. |
| Missing `completed` or bar-index/count mismatch | The bundle is incomplete or records were removed/reordered. Recover the complete original or rerun; do not add a success marker manually. |
| Duplicate key, invalid UTF-8/JSON or inspection limit | The record is malformed or outside this consumer's declared size scope. Restore the original file; the tool does not trim records. |
| SHA256 mismatch | Event bytes differ from the supplied trusted receipt. Compare the correct run and receipt; a self-generated replacement digest is not independent integrity evidence. |
| `summary.json` mismatch | Summary and event/completion data do not describe the same account result. Restore or regenerate both files together. |

Diagnostics name the file, line and relevant field, print to stderr and exit 2. Successful inspection
exits 0. Restoring a preserved valid bundle supports an immediate recheck; inspection itself creates
no replacement artifacts.

## Fill and account assumptions

- A decision formed from a bar close fills at that same close with directional slippage. This is
  optimistic: it does not model order latency, quotes, queues, spread depth or partial liquidity.
- Buy price = close × (1 + slippage_bps /10000); sell price = close × (1 − slippage_bps /10000).
  Each side charges fee_rate × filled_price × quantity. Buys may be clipped to available cash
  by BacktestBroker. The real PaperBroker uses this cost formula but rejects uncovered whole
  orders; that admission difference remains.
- Each symbol has its own starting cash. This is not the PaperBroker's shared multi-symbol cash
  account. Global live risk, higher/micro-timeframe data and order-book/execution filters are not
  reproduced. Enabled omitted inputs are named in the manifest and stderr.
- The final position is forcibly sold at the last close. Cash/position reconciliation covers
  those sells and partial takes; it does not prove live fills, deployment safety or profitability.
- The runner eagerly loads input candles. Audit events are streamed to a temporary file; no
  out-of-core data or total-memory guarantee is made. Restarting means replaying the full input,
  not restoring a live or paper account. Concurrent writers to one run name are unsupported.

## Failure and recovery

A row like `1735689600000,100,101,99,nan,1` is refused with a `:2: close` error and exit 2.
Correct that source cell from an authoritative source, or use a separate known-valid input; then
rerun the same command. A failed attempt creates no completed run directory. I/O failures and
interruption remove the staged audit; they are not retried or turned into successful runs.
The command does not alter your input or overwrite an earlier run. Publication is a directory
rename after both files close; it is not a power-loss durability guarantee.

## What was verified

The new cases exercise malformed rows/settings, byte-identical repeated audits, fill/fee/account
reconciliation, missing-symbol reporting, input/output collisions, I/O failure and interruption
cleanup, followed by correction and successful rerun. Generated market paths include costed and
zero-cost controls; their entry decision is deliberately forced in that unit test to exercise
fills, not to test an alpha model. Disposable mutants prove the checks catch the named defects.
The original test assertions, blueprint conformance and synthetic golden remain unchanged.

The verification supports the offline input-validation and accounting-consistency behaviour
above. It does not establish trading performance or production execution.
