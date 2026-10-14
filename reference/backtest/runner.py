"""Offline backtester that replays candles through the live bot's decision code.

    python -m backtest.runner --data DIR [--config bot/config/config.yaml] [--out results.json]
    python -m backtest.runner --fetch --start 2025-10-23T00:00:00Z --end 2025-11-05T23:59:59Z

--data DIR reads one CSV per symbol (DIR/BTC_USDT.csv: ts,open,high,low,close,volume; ts in ms).
--fetch downloads candles from Binance through ccxt instead (network; no API key needed).

Shared with the live loop (bot/trader.py), imported, not copied:
  bot/data/signal/indicators.py           compute_indicators
  bot/strategy.py                         signal_statuses + entry_signal_ok (the entry decision)
  bot/flow_control/stop_loss_take_profit  evaluate_dynamic_sl_tp (stop-loss / tiered take-profit)
Its own: the bar loop, the simulated broker (fills at the bar close plus slippage and fees), and
the metrics. Live-only inputs are not replayed: order-book signals (always "not fired" here, as
live when no book is available), the higher and micro timeframes, and the execution filters.
"""
import argparse
import csv
import itertools
import json
import math
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from bot.config.config_loader import ConfigLoader
from bot.data.signal.indicators import compute_indicators
from bot.data.types import Position
from bot.flow_control.stop_loss_take_profit import evaluate_dynamic_sl_tp
from bot.strategy import entry_signal_ok, signal_statuses
from bot.trading_logic.signal.MACD.divergence import bearish as macd_bearish_divergence

from backtest.audit import EventSink, write_audit

# Live-loop switches the backtester cannot replay from candles alone; reported, never silently dropped.
LIVE_ONLY = {
    ("signal_portfolio", "use_htf"): "higher-timeframe MACD confirmation",
    ("signal_portfolio", "use_micro_signals"): "micro-timeframe RSI/BB/volume",
    ("execution_filter", "enabled"): "micro-timeframe execution filter",
    ("execution_filter", "momentum_enabled"): "momentum execution filter",
    ("execution_filter", "iceberg_enabled"): "order-book iceberg filter",
    ("signal_portfolio", "ob_imbalance"): "order-book imbalance signal (counted as not fired)",
    ("signal_portfolio", "ob_depth"): "order-book depth signal (counted as not fired)",
    ("signal_portfolio", "ob_pressure"): "order-book pressure signal (counted as not fired)",
    ("signal_portfolio", "ob_large_orders"): "order-book large-orders signal (counted as not fired)",
}
WARMUP_BARS = 30  # bars before the first decision, so the 26-period MACD and 20-period bands exist
# The live loop fetches the last 200 candles each cycle (bot/trader.py, fetch_ohlcv(limit=200)) and
# computes indicators on that window, so the backtester does the same. With 200 bars the EMA start-up
# effect is already negligible; the window is kept for fidelity, not because it changed any result.
LIVE_WINDOW = 200


def _to_ms(dt_str: str) -> int:
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(UTC)
    return int(dt.timestamp() * 1000)


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC)


def _timeframe_ms(timeframe: str) -> int:
    unit, value = timeframe[-1].lower(), int(timeframe[:-1])
    if unit == "m":
        return value * 60_000
    if unit == "h":
        return value * 3_600_000
    if unit == "d":
        return value * 86_400_000
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def load_ohlcv_csv(path: str) -> list[list[float]]:
    """Read finite, consistent candles; errors identify the source line and field."""
    fields = ["ts", "open", "high", "low", "close", "volume"]
    rows: list[list[float]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, strict=True)
        if reader.fieldnames is None or sorted(reader.fieldnames) != sorted(fields):
            raise ValueError(f"{path}:1: header must contain exactly {','.join(fields)}")
        for raw in reader:
            line = reader.line_num
            if set(raw) != set(fields):
                raise ValueError(f"{path}:{line}: row must contain exactly six fields")
            values: list[float] = []
            for name in fields:
                try:
                    value = int(raw[name]) if name == "ts" else float(raw[name])
                except (ValueError, TypeError) as error:
                    raise ValueError(f"{path}:{line}: {name} must be numeric (ts: integer UTC milliseconds)") from error
                if name == "ts" and not 0 <= value <= 253402300799999:
                    raise ValueError(f"{path}:{line}: ts is outside supported UTC millisecond range")
                if name != "ts" and (not math.isfinite(value) or (value < 0 if name == "volume" else value <= 0)):
                    raise ValueError(f"{path}:{line}: {name} must be finite and {'nonnegative' if name in ('ts', 'volume') else 'positive'}")
                if name == "ts":
                    try:
                        _ms_to_dt(int(value))
                    except (ValueError, OverflowError, OSError) as error:
                        raise ValueError(f"{path}:{line}: ts is outside supported UTC datetime range") from error
                values.append(value)
            _, open_, high, low, close, _ = values
            if high < max(open_, close, low):
                raise ValueError(f"{path}:{line}: high must be at least open, close and low")
            if low > min(open_, close):
                raise ValueError(f"{path}:{line}: low must be at most open and close")
            if rows and values[0] <= rows[-1][0]:
                raise ValueError(f"{path}:{line}: ts timestamps are not strictly increasing")
            rows.append(values)
    if not rows:
        raise ValueError(f"{path}: no candles")
    if any(b[0] <= a[0] for a, b in itertools.pairwise(rows)):
        raise ValueError(f"{path}: timestamps are not strictly increasing")
    return rows


def fetch_ohlcv_range(symbol: str, timeframe: str, start_ms: int, end_ms: int, limit: int = 1000) -> list[list[float]]:
    from bot.core.exchange import ExchangeAdapter  # network path only; needs ccxt

    adapter = ExchangeAdapter(exchange_id="binance")
    tf_ms = _timeframe_ms(timeframe)
    since = start_ms
    all_rows: list[list[float]] = []
    while True:
        rows = adapter.client.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
        rows = [r for r in rows or [] if r[0] <= end_ms and (not all_rows or r[0] > all_rows[-1][0])]
        if not rows:
            break
        all_rows.extend(rows)
        if rows[-1][0] + tf_ms > end_ms:
            break
        since = rows[-1][0] + tf_ms
        time.sleep(0.05)
    return all_rows


class BacktestBroker:
    """Cash and one long position per symbol; fills at the given price plus slippage, fee per side."""

    def __init__(self, fee_rate: float, starting_cash: float, slippage_bps: float = 0.0) -> None:
        self.fee_rate = float(fee_rate)
        self.position_qty = 0.0
        self.avg_price = 0.0
        self.cash_usd = float(starting_cash)
        self.slippage = float(slippage_bps) / 10_000.0
        self.trades: list[dict] = []

    def buy(self, price: float, qty: float, ts: int) -> None:
        if qty <= 0 or price <= 0:
            return
        price = price * (1.0 + self.slippage)
        if price * qty * (1.0 + self.fee_rate) > self.cash_usd:
            qty = max(0.0, self.cash_usd / (price * (1.0 + self.fee_rate) + 1e-12))
            if qty <= 0:
                return
        cost = price * qty
        fee = self.fee_rate * cost
        self.avg_price = (self.avg_price * self.position_qty + cost) / (self.position_qty + qty)
        self.position_qty += qty
        self.cash_usd -= cost + fee
        self.trades.append({"ts": ts, "side": "BUY", "price": price, "qty": qty, "fee": fee})

    def sell(self, price: float, qty: float, ts: int) -> tuple[float, float]:
        qty = min(qty, self.position_qty)
        if qty <= 0 or price <= 0:
            return 0.0, 0.0
        price = price * (1.0 - self.slippage)
        proceeds = price * qty
        fee = self.fee_rate * proceeds
        entry_notional = self.avg_price * qty
        pnl = (proceeds - entry_notional) - (self.fee_rate * entry_notional + fee)
        self.position_qty -= qty
        if self.position_qty <= 1e-12:
            self.position_qty, self.avg_price = 0.0, 0.0
        self.cash_usd += proceeds - fee
        self.trades.append({"ts": ts, "side": "SELL", "price": price, "qty": qty, "fee": fee, "pnl": pnl})
        return pnl, qty


def compute_metrics(equity_series: pd.Series, periods_per_year: float) -> dict[str, float]:
    ret = equity_series.pct_change().dropna()
    if len(ret) == 0:
        return {"pnl": 0.0, "sharpe": 0.0, "sortino": 0.0, "max_drawdown": 0.0}
    ann = math.sqrt(periods_per_year)
    sharpe = (ret.mean() / (ret.std(ddof=0) + 1e-12)) * ann
    downside_std = ret[ret < 0].std(ddof=0)
    sortino = (ret.mean() / ((0.0 if np.isnan(downside_std) else downside_std) + 1e-12)) * ann
    drawdowns = equity_series / equity_series.cummax() - 1.0
    return {
        "pnl": float(equity_series.iloc[-1] - equity_series.iloc[0]),
        "sharpe": float(0.0 if np.isnan(sharpe) else sharpe),
        "sortino": float(0.0 if np.isnan(sortino) else sortino),
        "max_drawdown": float(drawdowns.min()),
    }


def window_indicators(ohlcv: list[list[float]], idx: int, flags: dict) -> dict[str, pd.Series]:
    """Indicators as the live loop would see them at bar idx: the last LIVE_WINDOW candles."""
    return compute_indicators(ohlcv[max(0, idx + 1 - LIVE_WINDOW): idx + 1], flags)


def decide_entry(ind: dict[str, pd.Series], flags: dict) -> bool:
    """The entry decision on one window: the same two functions the live loop calls."""
    return entry_signal_ok(signal_statuses(ind, flags), flags)


def backtest_symbol(symbol: str, ohlcv: list[list[float]], cfg: dict, timeframe: str,
                    on_event: EventSink | None = None) -> dict:
    fee_rate = float(cfg.get("transaction_fee", 0.0))
    flags = cfg.get("signal_portfolio", {}) or {}
    portfolio = cfg.get("portfolio", {}) or {}
    sltp_cfg = cfg.get("stop_loss_take_gain", {}) or {}
    base_capital = float(cfg.get("initial_capital_in_usd", 50_000))
    usd_per_trade = float(portfolio.get("usd_per_trade", 10_000))
    max_holding_time = float(portfolio.get("maximum_holding_time", 0))
    max_coin_loss = float(portfolio.get("per_crypto_max_drawdown", 0))
    broker = BacktestBroker(fee_rate, starting_cash=base_capital, slippage_bps=float(portfolio.get("slippage_bps", 1.0)))

    pos: Position | None = None
    realized_loss_usd = 0.0
    removed_from_pack = False  # live: a 72 h close sets the symbol's allocation to 0 (bot/trader.py)
    equity: list[tuple[datetime, float]] = []
    exits: dict[str, int] = {}

    def close_all(reason: str, price: float, ts: int) -> None:
        nonlocal pos, realized_loss_usd
        pnl, _ = broker.sell(price, broker.position_qty, ts)
        realized_loss_usd += max(0.0, -pnl)
        exits[reason] = exits.get(reason, 0) + 1
        pos = None

    def emit(kind: str, decision: str, reason: str, before: tuple[float, float, int],
             idx: int, ts: int, price: float, entry: bool | None, statuses: dict) -> None:
        if on_event is not None:
            cash, qty, trade_start = before
            on_event({"type": kind, "symbol": symbol, "bar_index": idx,
                      "bar_open_ts_ms": ts, "bar_close_ts_ms": ts + _timeframe_ms(timeframe),
                      "mark_price": price, "decision": decision, "reason": reason,
                      "entry_signal": entry, "signals": statuses,
                      "cash_before": cash, "quantity_before": qty,
                      "cash_after": broker.cash_usd, "quantity_after": broker.position_qty,
                      "equity_after": broker.cash_usd + broker.position_qty * price,
                      "fills": [dict(trade) for trade in broker.trades[trade_start:]]})

    for idx, row in enumerate(ohlcv):
        ts, price = int(row[0]), float(row[4])
        before = broker.cash_usd, broker.position_qty, len(broker.trades)
        decision, reason = "warmup", "insufficient_indicator_history"
        entry: bool | None = None
        statuses: dict = {}
        if idx >= WARMUP_BARS:
            decision, reason = "hold", "position_open"
            ind = window_indicators(ohlcv, idx, flags)
            if pos is not None:
                # Same order as the live loop: hard stop, then holding time, then the SL/TP ladder.
                if pos.stop_price and price <= float(pos.stop_price):
                    decision, reason = "exit", "stop_loss"
                    close_all("stop_loss", price, ts)
                elif max_holding_time > 0 and (ts / 1000.0 - pos.opened_ts) >= max_holding_time:
                    decision, reason = "exit", "max_holding_time"
                    close_all("max_holding_time", price, ts)
                    removed_from_pack = True
                else:
                    action = evaluate_dynamic_sl_tp(
                        pos, price, sltp_cfg,
                        bb_lower=float(ind["bb_lower"].iloc[-1]),
                        bb_upper=float(ind["bb_upper"].iloc[-1]),
                        rsi_value=float(ind["rsi"].iloc[-1]),
                        macd_bearish_div=macd_bearish_divergence(ind),
                        fee_rate=fee_rate,
                    )
                    if action["action"] == "exit":
                        decision, reason = "exit", "exit_ladder"
                        close_all(f"take_profit_tier_{action.get('tier', 0)}" if action.get("tier") else "signal_exit", price, ts)
                    else:
                        if action["action"] == "partial_take":
                            decision, reason = "partial_take", f"tier_{action['tier']}"
                            # Live sells a fraction of the ORIGINAL quantity at each tier.
                            qty = (pos.original_quantity or pos.quantity) * float(action["sell_fraction"])
                            pnl, sold = broker.sell(price, qty, ts)
                            realized_loss_usd += max(0.0, -pnl)
                            pos.quantity -= sold
                            exits[f"partial_tier_{action['tier']}"] = exits.get(f"partial_tier_{action['tier']}", 0) + 1
                        pos.stop_price = float(action.get("new_stop") or pos.stop_price or 0.0) or None
                        pos.highest_tier_reached = max(int(pos.highest_tier_reached or 0), int(action.get("tier") or 0))
            else:
                entry = decide_entry(ind, flags)
                statuses = signal_statuses(ind, flags) if on_event is not None else {}
                decision, reason = "no_entry", "signal_not_fired"
                if entry:
                    if removed_from_pack or (max_coin_loss > 0 and realized_loss_usd >= max_coin_loss):
                        decision, reason = "entry_blocked", "allocation_removed" if removed_from_pack else "coin_loss_cap"
                    else:
                        usd = usd_per_trade * (1.0 - 2.0 * fee_rate)  # live: fee cushion on the per-coin allocation
                        broker.buy(price, usd / price, ts)
                        decision, reason = "entry_blocked", "insufficient_cash"
                        if broker.position_qty > 0:
                            decision, reason = "entry", "signal_fired"
                            pos = Position(symbol=symbol, quantity=broker.position_qty, avg_price=broker.avg_price,
                                           entry_price=broker.avg_price, original_quantity=broker.position_qty,
                                           opened_ts=ts / 1000.0)
        equity.append((_ms_to_dt(ts), broker.cash_usd + broker.position_qty * price))
        emit("bar", decision, reason, before, idx, ts, price, entry, statuses)

    if broker.position_qty > 0:
        before = broker.cash_usd, broker.position_qty, len(broker.trades)
        close_all("end_of_data", float(ohlcv[-1][4]), int(ohlcv[-1][0]))
        emit("liquidation", "exit", "end_of_data", before, len(ohlcv) - 1,
             int(ohlcv[-1][0]), float(ohlcv[-1][4]), None, {})
        equity.append((_ms_to_dt(int(ohlcv[-1][0])), broker.cash_usd))

    eq = pd.Series([v for _, v in equity], index=pd.DatetimeIndex([t for t, _ in equity]))
    metrics: dict[str, Any] = compute_metrics(eq, 365 * 86_400_000 / _timeframe_ms(timeframe))
    metrics.update({
        "bars": len(ohlcv),
        "entries": sum(1 for t in broker.trades if t["side"] == "BUY"),
        "sells": sum(1 for t in broker.trades if t["side"] == "SELL"),
        "exit_reasons": dict(sorted(exits.items())),
    })
    return metrics


def run_backtest(cfg: dict, data: dict[str, list[list[float]]], timeframe: str,
                 on_event: EventSink | None = None) -> dict:
    started = time.perf_counter()
    per_symbol = {sym: backtest_symbol(sym, rows, cfg, timeframe, on_event=on_event) for sym, rows in data.items()}
    elapsed = time.perf_counter() - started
    bars = sum(m["bars"] for m in per_symbol.values())
    return {
        "per_symbol": per_symbol,
        "aggregate": {"symbols": len(per_symbol), "bars": bars, "seconds": round(elapsed, 3),
                      "bars_per_second": round(bars / elapsed, 1) if elapsed > 0 else None},
    }


def main(argv: list[str] | None = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--config", default=os.path.join(os.path.dirname(here), "bot", "config", "config.yaml"))
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--data", help="directory of <BASE>_<QUOTE>.csv files (offline)")
    src.add_argument("--fetch", action="store_true", help="download candles from Binance via ccxt (network)")
    p.add_argument("--start", default="2025-10-23T00:00:00Z")
    p.add_argument("--end", default="2025-11-05T23:59:59Z")
    p.add_argument("--timeframe", default=None, help="default: signal_portfolio.ltf_timeframe")
    output = p.add_mutually_exclusive_group()
    output.add_argument("--out", default=None, help="write the JSON summary here")
    output.add_argument("--audit", default=None, help="publish events.jsonl and summary.json in a NEW directory")
    args = p.parse_args(argv)
    try:
        return execute(args)
    except (ValueError, OSError, csv.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def execute(args: argparse.Namespace) -> int:
    cfg = ConfigLoader(args.config).get().raw
    portfolio = cfg.get("portfolio") or {}
    for field, raw, lower, upper in (
        ("transaction_fee", cfg.get("transaction_fee", 0), 0, 1),
        ("slippage_bps", portfolio.get("slippage_bps", 1), 0, 10000),
        ("initial_capital_in_usd", cfg.get("initial_capital_in_usd", 50_000), 0, math.inf),
    ):
        try:
            value = float(raw)
        except (ValueError, TypeError) as error:
            raise ValueError(f"{field} must be numeric") from error
        if not math.isfinite(value) or not lower <= value < upper:
            raise ValueError(f"{field} must be finite and in [{lower}, {upper})")
    timeframe = str(args.timeframe or (cfg.get("signal_portfolio") or {}).get("ltf_timeframe", "1h"))
    timeframe_ms = _timeframe_ms(timeframe)
    if timeframe_ms <= 0:
        raise ValueError("timeframe must have a positive duration")
    symbols = [s for s, on in (cfg.get("crypto_list") or {}).items() if on]
    data: dict[str, list[list[float]]] = {}
    input_paths = {Path(args.config).resolve()}
    for sym in symbols:
        if args.data:
            path = os.path.join(args.data, sym.replace("/", "_") + ".csv")
            if os.path.isfile(path):
                input_paths.add(Path(path).resolve())
                data[sym] = load_ohlcv_csv(path)
        else:
            rows = fetch_ohlcv_range(sym, timeframe, _to_ms(args.start), _to_ms(args.end))
            if rows:
                data[sym] = rows
    if not data:
        print(f"error: no candles for any enabled symbol {symbols}", file=sys.stderr)
        return 2
    for symbol in symbols:
        if symbol not in data:
            print(f"note: no candles for enabled symbol {symbol}; excluded from replay", file=sys.stderr)
    for output in (args.out, args.audit):
        if output is not None:
            target = Path(output)
            if any(target.resolve() == path or (target.exists() and target.samefile(path)) for path in input_paths):
                raise ValueError(f"output must not overwrite an input: {output}")
    omitted = []
    for (section, key), what in LIVE_ONLY.items():
        if bool((cfg.get(section) or {}).get(key, False)):
            omitted.append(f"{section}.{key}: {what}")
            print(f"note: {section}.{key} is on in the config; the backtester does not replay the {what}", file=sys.stderr)

    if args.audit:
        summary = write_audit(args.audit, cfg, data, timeframe, timeframe_ms,
                              lambda sink: run_backtest(cfg, data, timeframe, on_event=sink), omitted)
    else:
        summary = run_backtest(cfg, data, timeframe)
    text = json.dumps(summary, indent=2, sort_keys=True, allow_nan=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
