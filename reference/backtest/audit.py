"""Publish an offline replay audit only when the complete run succeeds."""

import hashlib
import itertools
import json
import tempfile
from collections.abc import Callable
from pathlib import Path

EventSink = Callable[[dict], None]


def json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def write_audit(directory: str, cfg: dict, data: dict[str, list[list[float]]], timeframe: str,
                timeframe_ms: int, run: Callable[[EventSink], dict], omitted: list[str]) -> dict:
    destination = Path(directory)
    if destination.exists():
        raise ValueError(f"audit output already exists: {destination}; choose a new run directory")
    portfolio = cfg.get("portfolio") or {}
    inputs = {symbol: {
        "bars": len(rows), "first_bar_open_ts_ms": int(rows[0][0]), "last_bar_open_ts_ms": int(rows[-1][0]),
        "parsed_candles_sha256": hashlib.sha256(json.dumps(rows, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
        "nonstandard_intervals": sum(b[0] - a[0] != timeframe_ms for a, b in itertools.pairwise(rows)),
    } for symbol, rows in data.items()}
    # A single directory rename publishes events and summary together. Failed runs leave neither.
    with tempfile.TemporaryDirectory(prefix=".ctp-replay-", dir=destination.parent) as tmp:
        staged = Path(tmp) / "run"
        staged.mkdir()
        with (staged / "events.jsonl").open("wb") as stream:
            def emit(event: dict) -> None:
                stream.write(json_bytes(event) + b"\n")

            emit({"type": "run", "schema": "ctp-replay-audit/v1", "timeframe": timeframe,
                  "requested_symbols": [symbol for symbol, enabled in (cfg.get("crypto_list") or {}).items() if enabled],
                  "missing_symbols": [symbol for symbol, enabled in (cfg.get("crypto_list") or {}).items()
                                      if enabled and symbol not in data],
                  "config_sha256": hashlib.sha256(json_bytes(cfg)).hexdigest(), "inputs": inputs,
                  "assumptions": {
                      "fill_model": "same_bar_close_plus_directional_slippage",
                      "cash_model": "independent_account_per_symbol",
                      "starting_cash_per_symbol": float(cfg.get("initial_capital_in_usd", 50_000)),
                      "fee_rate_per_side": float(cfg.get("transaction_fee", 0)),
                      "slippage_bps": float(portfolio.get("slippage_bps", 1)),
                      "force_liquidation_at_end": True, "gaps_interpolated": False,
                      "omitted_live_inputs": omitted,
                  }})
            summary = run(emit)
            emit({"type": "completed", "per_symbol": summary["per_symbol"],
                  "symbols": summary["aggregate"]["symbols"], "bars": summary["aggregate"]["bars"]})
        (staged / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n")
        if destination.exists():
            raise FileExistsError(f"audit output already exists: {destination}")
        staged.rename(destination)
    return summary
