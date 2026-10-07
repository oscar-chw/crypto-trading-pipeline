from typing import Dict


def check(indicators: Dict) -> bool:
    if len(indicators["close"]) < 10:
        return False
    
    # Original logic: price touched lower BB and closed above
    close_prev = indicators["close"].iloc[-2]
    close_curr = indicators["close"].iloc[-1]
    bb_lower_prev = indicators["bb_lower"].iloc[-2]
    bb_lower_curr = indicators["bb_lower"].iloc[-1]

    touched_lower = (close_prev <= bb_lower_prev)
    closed_above_lower = (close_curr > bb_lower_curr)
    original_check = bool(touched_lower and closed_above_lower)
    
    # Additional check: confirm the bounce is working (trend confirmation)
    # After bouncing from lower BB, we want to see upward momentum
    # For a slow-paced bot using 1h MACD, check recent price action to confirm bounce
    low = indicators["low"]
    close = indicators["close"]
    
    # Need at least 7 candles to check bounce confirmation
    if len(close) < 7:
        trend_check = False
    else:
        # Check if price is making higher lows in the last 5-7 candles
        # This confirms the bounce is working and price is moving up
        recent_lows = low.iloc[-7:]
        close.iloc[-7:]
        
        # Option 1: Check if we're making higher lows (confirms bounce)
        # Compare last 3 candles to previous 3 candles
        recent_lows_last3 = recent_lows.iloc[-3:]
        recent_lows_prev3 = recent_lows.iloc[-6:-3]
        higher_lows = recent_lows_last3.min() > recent_lows_prev3.min()
        
        # Option 2: Check if price is moving up after bounce (last 3-5 candles)
        # Current close should be higher than 3-5 candles ago
        price_moving_up = close_curr > close.iloc[-5]
        
        # Option 3: Check if we're not making lower lows (would invalidate bounce)
        # Last candle low should not be lower than 5 candles ago
        not_making_lower_lows = recent_lows.iloc[-1] >= recent_lows.iloc[-5]
        
        # Bounce is confirmed if: higher lows OR price moving up OR not making lower lows
        trend_check = bool(higher_lows or price_moving_up or not_making_lower_lows)
    
    # Both conditions must be true (AND logic)
    return bool(original_check and trend_check)


