"""The pluggable decision: which signals fire, and whether they are enough to enter.

The live loop (bot/trader.py) and the offline backtester (backtest/runner.py) both call these two
functions, so a backtest exercises the same entry decision the live bot makes. A new strategy
replaces these two functions (and, for exits, bot/flow_control/stop_loss_take_profit.py); data,
risk, execution and recording stay as they are. See docs/how-it-works.md, "Swapping the strategy".
"""
from typing import Dict, Optional

from bot.trading_logic.signal.BB.inPosition import check as _sig_bb
from bot.trading_logic.signal.ENGULFING.isBullish import check as _sig_engulfing
from bot.trading_logic.signal.MACD.isBullish import check as _sig_macd
from bot.trading_logic.signal.ORDERBOOK.depth import check as _sig_ob_depth
from bot.trading_logic.signal.ORDERBOOK.imbalance import check as _sig_ob_imbalance
from bot.trading_logic.signal.ORDERBOOK.largeOrders import check as _sig_ob_large_orders
from bot.trading_logic.signal.ORDERBOOK.pressure import check as _sig_ob_pressure
from bot.trading_logic.signal.PRICE.underAction import check as _sig_price
from bot.trading_logic.signal.RSI.isConfirmed import check as _sig_rsi
from bot.trading_logic.signal.VOLUME.isConfirmed import check as _sig_vol

# Candle signals read the indicator dict; order-book signals read a fetched order book.
CANDLE_SIGNALS = ("rsi", "bb", "macd", "volume", "price", "engulfing")
ORDERBOOK_SIGNALS = ("ob_imbalance", "ob_depth", "ob_pressure", "ob_large_orders")
SIGNAL_KEYS = CANDLE_SIGNALS + ORDERBOOK_SIGNALS

_CANDLE_CHECKS = {
    "macd": _sig_macd,
    "rsi": _sig_rsi,
    "bb": _sig_bb,
    "volume": _sig_vol,
    "price": _sig_price,
    "engulfing": _sig_engulfing,
}


def signal_statuses(
    indicators: Dict,
    flags: Dict,
    orderbook: Optional[Dict] = None,
    current_price: float = 0.0,
    ob_config: Optional[Dict] = None,
) -> Dict[str, bool]:
    """Return {signal: fired?} for every signal switched on in `flags` (config `signal_portfolio`).

    A candle signal missing from `flags` counts as on; an order-book signal missing counts as off.
    An order-book signal that raises, or has no order book to read, reports False.
    """
    result: Dict[str, bool] = {}
    for key in CANDLE_SIGNALS:
        if bool(flags.get(key, True)):
            result[key] = bool(_CANDLE_CHECKS[key](indicators))

    ob_checks = {
        "ob_imbalance": lambda: _sig_ob_imbalance(orderbook, ob_config),
        "ob_depth": lambda: _sig_ob_depth(orderbook, ob_config),
        "ob_pressure": lambda: current_price > 0 and _sig_ob_pressure(orderbook, current_price, ob_config),
        "ob_large_orders": lambda: _sig_ob_large_orders(orderbook, ob_config),
    }
    for key in ORDERBOOK_SIGNALS:
        if not bool(flags.get(key, False)):
            continue
        if not (orderbook and ob_config):
            result[key] = False
            continue
        try:
            result[key] = bool(ob_checks[key]())
        except Exception:
            result[key] = False
    return result


def entry_signal_ok(statuses: Dict[str, bool], flags: Dict) -> bool:
    """Apply the entry rule to the statuses: `entry_mode` "all" or "any_two" (the default).

    Kept exactly as the original loop computed it: every key in SIGNAL_KEYS whose flag is not
    explicitly false is "enabled", and an enabled signal with no status counts as not fired.
    """
    mode = str(flags.get("entry_mode", "any_two")).lower()
    enabled = [k for k in SIGNAL_KEYS if bool(flags.get(k, True))]
    fired = [k for k in enabled if statuses.get(k, False)]
    if mode == "any_two":
        return len(fired) >= 2
    return len(fired) == len(enabled)
