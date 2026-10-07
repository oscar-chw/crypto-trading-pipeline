from typing import Dict


def check(indicators: Dict) -> bool:
    if len(indicators["volume"]) < 25:
        return False
    
    volume = indicators["volume"]
    vol_ma = indicators["vol_ma20"]
    
    # Original check: current volume > MA
    vol = volume.iloc[-1]
    vol_ma_current = vol_ma.iloc[-1] or 0.0
    current_check = bool(vol > vol_ma_current)
    
    # Additional check: volume should be above MA for at least 5 of last 15 candles (15 minutes)
    # This ensures sustained volume over a meaningful period, not just one spike
    # For a slow-paced bot using 1h MACD, 15 minutes provides better confirmation
    recent_vol = volume.iloc[-15:]
    recent_ma = vol_ma.iloc[-15:]
    above_ma_count = sum(1 for i in range(len(recent_vol)) if recent_vol.iloc[i] > (recent_ma.iloc[i] or 0.0))
    sustained_check = bool(above_ma_count >= 5)  # At least 5 of 15 candles (33%)
    
    # Both conditions must be true (AND logic)
    return bool(current_check and sustained_check)


