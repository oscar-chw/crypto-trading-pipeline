"""Stage 03 Strategy over the bot's entry decision (bot/strategy.py), as the backtester makes it."""
import math
from collections.abc import Mapping

import pandas as pd
from backtest.runner import LIVE_WINDOW
from bot.strategy import CANDLE_SIGNALS, entry_signal_ok, signal_statuses
from pipeline.types import Signal, UtcNanos

# The candle signals this adapter can rebuild from scalars, and the features (with lags) each one reads.
SUPPORTED = ("macd", "rsi", "engulfing")
FEATURES = ("macd", "macd_signal", "macd_hist", "macd_hist_lag1", "macd_hist_lag2", "rsi",
            "open", "open_lag1", "close", "close_lag1")


class EntryStrategy:
    """score 1.0 when entry_signal_ok fires (long-only, fixed-notional entry), else 0.0 (no view).

    The Protocol passes scalars, while the bot's checks read the tail of indicator series. The adapter
    rebuilds each series as LIVE_WINDOW bars, NaN except its last values, so the length guards in the
    checks see the live window and a NaN input reads as "not fired", exactly as in the bot. No order book
    is passed: like backtest.runner.decide_entry, enabled order-book signals count as not fired.
    """

    model_id = "wqt2025-entry"

    def __init__(self, flags: dict, horizon_ns: int) -> None:
        unsupported = [k for k in CANDLE_SIGNALS if bool(flags.get(k, True)) and k not in SUPPORTED]
        if unsupported:  # a signal this adapter cannot feed would silently never fire
            raise ValueError(f"signals {unsupported} need history this adapter does not map")
        self.flags, self.horizon_ns = flags, horizon_ns

    def _series(self, features: Mapping[str, float], key: str, lags: int) -> pd.Series:
        tail = [float(features.get(key if lag == 0 else f"{key}_lag{lag}", math.nan)) for lag in range(lags, -1, -1)]
        return pd.Series([math.nan] * (LIVE_WINDOW - len(tail)) + tail)

    def signal(self, instrument_id: str, t: UtcNanos, features: Mapping[str, float]) -> Signal:
        ind = {"macd": self._series(features, "macd", 0), "macd_signal": self._series(features, "macd_signal", 0),
               "macd_hist": self._series(features, "macd_hist", 2), "rsi": self._series(features, "rsi", 0),
               "open": self._series(features, "open", 1), "close": self._series(features, "close", 1)}
        fired = entry_signal_ok(signal_statuses(ind, self.flags), self.flags)
        return Signal(instrument_id, t, 1.0 if fired else 0.0, self.horizon_ns, self.model_id)
