from typing import Dict, Tuple
import time


def is_portfolio_drawdown_exceeded(equity_info: Dict[str, float], max_drawdown: float) -> bool:
    peak = max(equity_info.get("peak_equity", 0.0), equity_info.get("current_equity", 0.0))
    current = equity_info.get("current_equity", 0.0)
    if peak <= 0:
        # With retry + last-good fallback, reaching here implies transient/edge case; don't trigger stop
        return False
    drawdown = (peak - current) / peak
    return drawdown >= max_drawdown


def update_daily_peak(peak_equity: float, current_equity: float, last_peak_date: str) -> Tuple[float, str]:
    """Return (new_peak, new_date) where peak resets at the start of each UTC day.

    If the date changed, set peak to current. Otherwise, keep the max of current and previous peak.
    """
    today = time.strftime("%Y-%m-%d")
    if last_peak_date != today:
        return current_equity, today
    return max(peak_equity, current_equity), last_peak_date


