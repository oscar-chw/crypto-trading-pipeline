from typing import Dict


def check(indicators: Dict) -> bool:
    if len(indicators["rsi"]) < 15:
        return False
    rsi = indicators["rsi"].iloc[-1]
    return bool(50 < rsi < 70)


