from typing import Dict
import pandas as pd


def check(indicators: Dict) -> bool:
    """Check if bullish engulfing pattern is present.
    
    Bullish Engulfing Pattern:
    1. Previous candle: Bearish (close < open) - Red candle
    2. Current candle: Bullish (close > open) - Green candle
    3. Current candle 'engulfs' previous:
       - Current open < Previous close
       - Current close > Previous open
    
    This pattern indicates strong buying pressure and potential reversal.
    Works best on higher timeframes (1h, 4h, 1d).
    
    Returns:
        True if bullish engulfing pattern detected
        False otherwise
    """
    # Need at least 2 candles (previous + current)
    if len(indicators["close"]) < 2:
        return False
    
    open_ = indicators["open"]
    close = indicators["close"]
    
    # Get previous and current candle values
    prev_open = open_.iloc[-2]
    prev_close = close.iloc[-2]
    curr_open = open_.iloc[-1]
    curr_close = close.iloc[-1]
    
    # Check for NaN values
    if pd.isna(prev_open) or pd.isna(prev_close) or pd.isna(curr_open) or pd.isna(curr_close):
        return False
    
    # Previous candle: Bearish (close < open)
    prev_bearish = float(prev_close) < float(prev_open)
    
    # Current candle: Bullish (close > open)
    curr_bullish = float(curr_close) > float(curr_open)
    
    # Current candle engulfs previous:
    # - Current open < Previous close
    # - Current close > Previous open
    engulfs = float(curr_open) < float(prev_close) and float(curr_close) > float(prev_open)
    
    # All three conditions must be true
    return bool(prev_bearish and curr_bullish and engulfs)

