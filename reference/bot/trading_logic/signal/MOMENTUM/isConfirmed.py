from typing import Dict


def check(indicators: Dict) -> bool:
    """Check if momentum is sustained over multiple candles.
    
    MACD histogram should be increasing for at least 2-3 candles
    to confirm sustained momentum, not just one candle.
    """
    if len(indicators["macd_hist"]) < 5:
        return False
    
    hist = indicators["macd_hist"]
    # Check last 3 candles for increasing MACD histogram
    recent_hist = hist.iloc[-3:]
    
    # MACD histogram should be increasing (each candle higher than previous)
    increasing = True
    for i in range(1, len(recent_hist)):
        if recent_hist.iloc[i] <= recent_hist.iloc[i-1]:
            increasing = False
            break
    
    return bool(increasing)

