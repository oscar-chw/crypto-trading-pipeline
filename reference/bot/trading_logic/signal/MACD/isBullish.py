from typing import Dict
import pandas as pd


def check(indicators: Dict) -> bool:
    """Check if MACD is bullish: MACD line > signal line AND histogram increasing.
    
    MACD needs sufficient data:
    - Slow EMA: 26 periods (26 hours for 1h timeframe)
    - Signal line: 9 periods on top of MACD
    - Full accuracy: 26 (slow EMA) + 9 (signal line) = 35 candles
    - On hourly timeframe: 35 candles = ~1.5 days of data
    - Note: Exchange APIs typically return complete candles only (last candle may be incomplete)
    - Removed minimum candle requirement to allow more signals (values may be less accurate with <26 candles)
    """
    # Removed minimum candle check - rely on NaN checks instead
    # This allows MACD to trigger earlier, though values may be less accurate
    
    # Get last values, handling NaN
    if len(indicators["macd"]) == 0:
        return False
    
    macd_now = indicators["macd"].iloc[-1]
    macd_sig = indicators["macd_signal"].iloc[-1]
    
    # Check for NaN or invalid values (this will catch insufficient data)
    if pd.isna(macd_now) or pd.isna(macd_sig):
        return False
    
    # Check if MACD line is above signal line
    macd_above_signal = float(macd_now) > float(macd_sig)
    
    # Check if histogram is increasing (check last 2-3 candles for sustained increase)
    # This is more robust than just checking the last diff
    hist = indicators["macd_hist"]
    if len(hist) < 3:
        return False
    
    # Check if histogram is increasing over last 2-3 candles
    # More robust: check if last 2 candles show increasing trend
    hist_last = hist.iloc[-3:]
    hist_diff = hist_last.diff().dropna()
    
    # Histogram is increasing if:
    # 1. Last diff is positive (immediate increase)
    # 2. OR last 2 diffs are positive (sustained increase)
    if len(hist_diff) < 1:
        return False
    
    hist_increasing = False
    if len(hist_diff) >= 2:
        # Check if last 2 changes are positive (sustained increase)
        hist_increasing = bool(hist_diff.iloc[-1] > 0 and hist_diff.iloc[-2] > 0)
    elif len(hist_diff) >= 1:
        # Check if last change is positive
        hist_increasing = bool(hist_diff.iloc[-1] > 0)
    
    return bool(macd_above_signal and hist_increasing)


