# Bollinger Band Position: Price pulls back to lower Bollinger Band or middle band (20 SMA)
from typing import Dict


def check(indicators: Dict) -> bool:
    if len(indicators["close"]) < 25:
        return False
    price_curr = indicators["close"].iloc[-1]
    price_prev = indicators["close"].iloc[-2]
    bb_lower_curr = indicators["bb_lower"].iloc[-1]
    bb_lower_prev = indicators["bb_lower"].iloc[-2]
    bb_mid_curr = indicators["bb_mid"].iloc[-1]
    bb_mid_prev = indicators["bb_mid"].iloc[-2]

    # Case 1: Pullback to lower band, then close above lower and not above mid
    touched_lower = (price_prev <= bb_lower_prev)
    closed_above_lower_not_above_mid = ((price_curr > bb_lower_curr) and (price_curr <= bb_mid_curr))

    # Case 2: Pullback to middle band (20 SMA), then close above mid
    touched_mid = ((price_prev <= bb_mid_prev) and (price_prev >= bb_lower_prev))
    closed_above_mid = (price_curr > bb_mid_curr)

    return bool((touched_lower and closed_above_lower_not_above_mid) or (touched_mid and closed_above_mid))

