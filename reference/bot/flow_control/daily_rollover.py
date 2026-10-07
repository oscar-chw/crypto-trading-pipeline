from typing import Dict, Optional
import time
import os
import json
import csv
from bot.core.persistence import save_json


def write_daily_pnl(
    record_root: str,
    out_dir: str,
    cfg_loader,
    alloc: Dict[str, float],
    positions: Dict[str, object],
    detail_console_output: bool = False,
    current_equity_usd: float = None,
    reset_time_utc: Optional[str] = None,
) -> Dict:
    """Compute and persist today's realized PnL and per-coin status.

    - Aggregates realized PnL per symbol for today from records.
    - If reset_time_utc is provided (e.g., "12:00"), only includes trades after that time.
    - Logs per-coin pack size (alloc USD) and whether a position is currently open (on_hold).
    - Logs spare amount computed from config, enabled symbols and current allocations.
    Output written to record/daily_pnl_YYYYMMDD.json.
    """
    # UTC, matching the recorder's file names (bot/record/recorder.py).
    today = time.strftime("%Y-%m-%d", time.gmtime())
    yyyymmdd = time.strftime("%Y%m%d", time.gmtime())
    
    # Calculate reset timestamp if reset_time_utc is provided
    reset_timestamp = None
    if reset_time_utc:
        try:
            hh, mm = [int(x) for x in reset_time_utc.split(":", 1)]
            now_utc = time.gmtime()
            # Create UTC timestamp for today at reset_time_utc
            reset_dt_utc = time.struct_time((
                now_utc.tm_year, now_utc.tm_mon, now_utc.tm_mday,
                hh, mm, 0, now_utc.tm_wday, now_utc.tm_yday, 0  # isdst=0 for UTC
            ))
            # Use calendar.timegm for UTC timestamp (not mktime which uses local time)
            import calendar
            reset_timestamp = calendar.timegm(reset_dt_utc)
        except Exception:
            reset_timestamp = None
    
    # Check if PnL was manually reset - if so, preserve the reset state
    out_path = os.path.join(out_dir, f"daily_pnl_{yyyymmdd}.json")
    existing_data = {}
    manually_reset = False
    try:
        import json as _json
        with open(out_path, 'r', encoding='utf-8') as f:
            existing_data = _json.load(f)
            manually_reset = existing_data.get("_manually_reset", False)
    except Exception:
        pass
    
    # If manually reset, use the preserved PnL instead of recalculating
    if manually_reset:
        summary = existing_data.get("pnl", {"_total": 0.0})
    else:
        summary: Dict[str, float] = {"_total": 0.0}
        # Scan today's files. The recorder writes every event to BOTH transactions_DAY.jsonl and
        # transactions_DAY.csv, so reading both counted each close twice (the original version did).
        # Read the JSONL, which is written first and is the canonical copy; use the CSV only when a
        # day has no JSONL. tests/case/test_daily_pnl.py holds this.
        try:
            names = [n for n in sorted(os.listdir(record_root))
                     if n.startswith(f"transactions_{yyyymmdd}") and n.endswith(('.csv', '.jsonl'))]
            if any(n.endswith('.jsonl') for n in names):
                names = [n for n in names if n.endswith('.jsonl')]
            for name in names:
                path = os.path.join(record_root, name)
                if name.endswith('.csv'):
                    with open(path, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            if (row.get('type') or '').lower() != 'trade_close':
                                continue
                            # Filter by reset time if provided
                            if reset_timestamp:
                                try:
                                    tx_timestamp = float(row.get('timestamp', 0))
                                    if tx_timestamp < reset_timestamp:
                                        continue  # Skip trades before reset time
                                except Exception:
                                    pass
                            sym = str(row.get('pair') or '').upper()
                            try:
                                entry = float(row.get('entry_price') or 0.0)
                                price = float(row.get('price') or 0.0)
                                qty = float(row.get('quantity') or 0.0)
                            except Exception:
                                continue
                            pnl = (price - entry) * qty
                            summary[sym] = float(summary.get(sym, 0.0) + pnl)
                            summary["_total"] = float(summary.get("_total", 0.0) + pnl)
                else:
                    with open(path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            rec = json.loads(line)
                            if (rec.get('type') or '').lower() != 'trade_close':
                                continue
                            # Filter by reset time if provided
                            if reset_timestamp:
                                try:
                                    tx_timestamp = float(rec.get('timestamp', 0))
                                    if tx_timestamp < reset_timestamp:
                                        continue  # Skip trades before reset time
                                except Exception:
                                    pass
                            sym = str(rec.get('pair') or '').upper()
                            entry = float(rec.get('entry_price') or 0.0)
                            price = float(rec.get('price') or 0.0)
                            qty = float(rec.get('quantity') or 0.0)
                            pnl = (price - entry) * qty
                            summary[sym] = float(summary.get(sym, 0.0) + pnl)
                            summary["_total"] = float(summary.get("_total", 0.0) + pnl)
        except Exception:
            pass

    # Build status snapshot: allocations, on-hold flags, spare
    per_coin_status: Dict[str, Dict] = {}
    try:
        cfg = cfg_loader.get()
        usd_per_trade = float(cfg.portfolio.get("usd_per_trade", 10000))
        cash_in_hand_usd = float(cfg.portfolio.get("cash_in_hand_usd", 10000))
        target_active = int(cfg.portfolio.get("target_active_coins", 4))
        enabled = [s for s, en in cfg.crypto_list.items() if en]
    except Exception:
        usd_per_trade = 10000.0
        cash_in_hand_usd = 10000.0
        target_active = 4
        enabled = list(alloc.keys())

    current_total = 0.0
    for s in enabled:
        try:
            current_total += float(alloc.get(s, 0.0) or 0.0)
        except Exception:
            pass
    base_total = usd_per_trade * float(max(0, min(target_active, len(enabled))))
    if current_equity_usd is not None:
        # Spare defined as current equity minus coin pack allocations
        spare_remaining = max(0.0, float(current_equity_usd) - current_total)
    else:
        # Fallback to config-based spare logic
        spare_used = max(0.0, current_total - base_total)
        spare_remaining = max(0.0, cash_in_hand_usd - spare_used)

    # Per-coin snapshot
    for s in enabled:
        a = float(alloc.get(s, 0.0) or 0.0)
        pos = positions.get(s) if isinstance(positions, dict) else None
        on_hold = bool(pos is not None)
        qty = float(getattr(pos, 'quantity', 0.0) or 0.0) if on_hold else 0.0
        avg_price = float(getattr(pos, 'avg_price', 0.0) or 0.0) if on_hold else 0.0
        per_coin_status[s] = {
            "alloc_usd": a,
            "on_hold": on_hold,
            "position_qty": qty,
            "avg_price": avg_price,
            "pnl_today": float(summary.get(s, 0.0)),
        }

    os.makedirs(out_dir, exist_ok=True)
    try:
        # If manually reset, preserve the reset PnL; otherwise use calculated summary
        save_json(out_path, {
            "date": today,
            "pnl": summary,
            "_manually_reset": manually_reset,  # Preserve reset flag if it was set
            "status": {
                "spare_usd": spare_remaining,
                "base_total_usd": base_total,
                "current_total_usd": current_total,
                "cash_in_hand_usd": cash_in_hand_usd,
                "usd_per_trade": usd_per_trade,
                "target_active_coins": target_active,
            },
            "per_coin": per_coin_status,
        })
    except Exception:
        pass

    if detail_console_output:
        print(f"[DAILY_PNL] {today} total={summary.get('_total', 0.0):.2f} USDT | spare={spare_remaining:.2f}")
    return {"pnl": summary, "per_coin": per_coin_status}

