import json
import os
import time
from typing import Any, Dict, Optional
import csv


def _daily_path(root: str, ts: int) -> str:
    # UTC day, the same day the CSV mirror uses, so one event never lands on two different days.
    day = time.strftime("%Y%m%d", time.gmtime(ts))
    return os.path.join(root, f"transactions_{day}.jsonl")


def append_record(event: Dict[str, Any], record_root: str) -> None:
    """Append one event to the day's JSONL (canonical) and its CSV mirror."""
    os.makedirs(record_root, exist_ok=True)
    path = _daily_path(record_root, int(event.get("timestamp", int(time.time()))))
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    _append_csv(event, record_root)


def log_order(record_root: str, pair: str, side: str, price: float, quantity: float, order_id: Optional[str] = None, signals: Optional[Dict[str, bool]] = None) -> None:
    """Log an order with optional indicator signals.
    
    Args:
        record_root: Root directory for records
        pair: Trading pair (e.g., "BTC/USDT")
        side: Order side ("BUY" or "SELL")
        price: Order price
        quantity: Order quantity
        order_id: Optional order ID
        signals: Optional dict of indicator signals (e.g., {"rsi": True, "macd": True, "bb": False, "volume": True, "price": True})
    """
    ts = int(time.time())
    event = {
        "type": "order",
        "pair": pair,
        "action": side.upper(),
        "price": float(price),
        "quantity": float(quantity),
        "timestamp": ts,
    }
    if order_id:
        event["order_id"] = order_id
    if signals:
        # Record which indicators were triggered
        event["signals"] = signals
        # Also record as individual boolean fields for easier CSV querying
        event["signal_rsi"] = signals.get("rsi", False)
        event["signal_bb"] = signals.get("bb", False)
        event["signal_macd"] = signals.get("macd", False)
        event["signal_volume"] = signals.get("volume", False)
        event["signal_price"] = signals.get("price", False)
    append_record(event, record_root)


def log_trade_close(record_root: str, pair: str, entry_price: float, exit_price: float, quantity: float, pnl_pct: Optional[float]) -> None:
    ts = int(time.time())
    event = {
        "type": "trade_close",
        "pair": pair,
        "action": "SELL",
        "price": float(exit_price),
        "entry_price": float(entry_price),
        "quantity": float(quantity),
        "pnl_pct": float(pnl_pct) if pnl_pct is not None else None,
        "timestamp": ts,
    }
    append_record(event, record_root)


def log_liquidation(record_root: str, pair: str, current_price: float, quantity: float, peak_equity: float, current_equity: float, loss_usdt: float, reason: str = "daily_max_drawdown") -> None:
    """Log when a position is liquidated due to drawdown limit."""
    ts = int(time.time())
    event = {
        "type": "liquidation",
        "pair": pair,
        "action": "LIQUIDATE",
        "price": float(current_price),
        "quantity": float(quantity),
        "peak_equity": float(peak_equity),
        "current_equity": float(current_equity),
        "loss_usdt": float(loss_usdt),
        "reason": reason,
        "timestamp": ts,
    }
    append_record(event, record_root)


def _append_csv(event: Dict[str, Any], record_root: str) -> None:
    os.makedirs(record_root, exist_ok=True)
    ts = int(event.get("timestamp", int(time.time())))
    dt = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))
    row = {
        "timestamp": ts,
        "datetime": dt,
        "action": (event.get("action") or "").upper(),
        "pair": event.get("pair"),
        "price": event.get("price"),
        "quantity": event.get("quantity"),
        "order_id": event.get("order_id"),
        "entry_price": event.get("entry_price"),
        "pnl_pct": event.get("pnl_pct"),
        "type": event.get("type"),
        "peak_equity": event.get("peak_equity"),
        "current_equity": event.get("current_equity"),
        "loss_usdt": event.get("loss_usdt"),
        "reason": event.get("reason"),
        "signal_rsi": event.get("signal_rsi") if event.get("signal_rsi") is not None else "",
        "signal_bb": event.get("signal_bb") if event.get("signal_bb") is not None else "",
        "signal_macd": event.get("signal_macd") if event.get("signal_macd") is not None else "",
        "signal_volume": event.get("signal_volume") if event.get("signal_volume") is not None else "",
        "signal_price": event.get("signal_price") if event.get("signal_price") is not None else "",
    }
    csv_path = os.path.join(record_root, time.strftime("transactions_%Y%m%d.csv", time.gmtime(ts)))
    header = ["timestamp", "datetime", "action", "pair", "price", "quantity", "order_id", "entry_price", "pnl_pct", "type", "peak_equity", "current_equity", "loss_usdt", "reason", "signal_rsi", "signal_bb", "signal_macd", "signal_volume", "signal_price"]
    write_header = not os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if write_header:
            w.writeheader()
        w.writerow(row)


