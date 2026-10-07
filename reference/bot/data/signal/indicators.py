from typing import Dict, List

import numpy as np
import pandas as pd


def _to_dataframe(ohlcv: List[List[float]]) -> pd.DataFrame:
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df


def compute_indicators(ohlcv: List[List[float]], cfg: Dict) -> Dict[str, pd.Series]:
    df = _to_dataframe(ohlcv)
    open_ = df["open"]
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]

    macd_fast = int(cfg.get("macd_1", 12))
    macd_slow = int(cfg.get("macd_2", 26))
    macd_signal = int(cfg.get("macd_3", 9))
    ema_fast = close.ewm(span=macd_fast, adjust=False).mean()
    ema_slow = close.ewm(span=macd_slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal_line = macd.ewm(span=macd_signal, adjust=False).mean()
    macd_hist = macd - macd_signal_line

    rsi_period = int(cfg.get("rsi_1", 14))
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / rsi_period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / rsi_period, adjust=False).mean()
    rs = roll_up / (roll_down.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    # No loss yet but some gain: RS is infinite and RSI is 100 (Wilder), not undefined. It was NaN, so a
    # static-mode "RSI > 70" exit could not fire on a run of gains. Flat prices (0/0) stay NaN.
    rsi = rsi.mask((roll_down == 0) & (roll_up > 0), 100.0)

    bb_period = int(cfg.get("bb_1", 20))
    bb_std = float(cfg.get("bb_2", 2))
    ma = close.rolling(bb_period).mean()
    std = close.rolling(bb_period).std(ddof=0)
    bb_upper = ma + bb_std * std
    bb_lower = ma - bb_std * std

    vol_ma = volume.rolling(20).mean()

    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "macd": macd,
        "macd_signal": macd_signal_line,
        "macd_hist": macd_hist,
        "rsi": rsi,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_mid": ma,
        "vol_ma20": vol_ma,
        "volume": volume,
    }


