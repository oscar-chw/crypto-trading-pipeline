"""Stage 02 Features: one output of compute_indicators (bot/data/signal/indicators.py) per Feature."""

import pandas as pd
from bot.data.signal.indicators import compute_indicators

NS_PER_MS = 1_000_000


def lookbacks(cfg: dict) -> dict[str, int]:
    """Bars before each output's first value, as compute_indicators computes it.

    MACD and RSI are EWMs seeded at the first bar (adjust=False), so they emit from bar 1 and bar 2;
    the bot relies on WARMUP_BARS and its 200-bar window for convergence, not on NaN warm-up.
    """
    bb = int(cfg.get("bb_1", 20))
    out = {k: 1 for k in ("open", "high", "low", "close", "volume", "macd", "macd_signal", "macd_hist")}
    out.update({"rsi": 2, "bb_upper": bb, "bb_lower": bb, "bb_mid": bb, "vol_ma20": 20})
    return out


class IndicatorFeature:
    """compute_indicators(...)[key], re-indexed by close_time and shifted `lag` bars (the value lag bars ago)."""

    def __init__(self, key: str, cfg: dict, lag: int = 0) -> None:
        self.key, self.cfg, self.lag = key, cfg, lag
        self.name = key if lag == 0 else f"{key}_lag{lag}"
        self.lookback = lookbacks(cfg)[key] + lag

    def compute(self, bars: pd.DataFrame) -> pd.Series:
        ts_ms = (bars.index.to_numpy() // NS_PER_MS).tolist()
        cols = [bars[c].tolist() for c in ("open", "high", "low", "close", "volume")]
        ohlcv = [list(row) for row in zip(ts_ms, *cols, strict=False)]
        out = compute_indicators(ohlcv, self.cfg)[self.key]
        return pd.Series(out.to_numpy(), index=bars.index, name=self.name).shift(self.lag)
