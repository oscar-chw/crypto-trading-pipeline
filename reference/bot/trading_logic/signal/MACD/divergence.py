from typing import Dict
import pandas as pd


def bearish(ind: Dict[str, pd.Series], lookback: int = 30) -> bool:
    if len(ind["close"]) < lookback + 5:
        return False
    close = ind["close"].iloc[-lookback:]
    macd = ind["macd"].iloc[-lookback:]
    half = max(2, lookback // 2)
    price_high1 = close.iloc[:half].max()
    price_high2 = close.iloc[half:].max()
    macd_high1 = macd.iloc[:half].max()
    macd_high2 = macd.iloc[half:].max()
    return (price_high2 > price_high1) and (macd_high2 < macd_high1)


