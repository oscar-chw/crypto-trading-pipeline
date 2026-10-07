from typing import Dict, List, Optional

from bot.data.signal.indicators import compute_indicators


def basic_execution_ok(ohlcv: List[List[float]], cfg_signals: Dict) -> bool:
    """Simple micro-timeframe execution filter.

    Rules (tunable by cfg_signals values):
      - RSI > 50
      - close >= BB mid
    """
    ind = compute_indicators(ohlcv, cfg_signals)
    rsi_ok = float(ind["rsi"].iloc[-1]) > 50.0
    close_ge_mid = float(ind["close"].iloc[-1]) >= float(ind["bb_mid"].iloc[-1])
    return bool(rsi_ok and close_ge_mid)


def momentum_execution_ok(indicators: Dict) -> bool:
    """Momentum execution filter.
    
    Checks if MACD histogram is increasing for sustained momentum.
    This filter blocks entry if momentum is not sustained.
    
    Returns:
        True if OK to trade (momentum is sustained)
        False if momentum is not sustained (should block entry)
    """
    # Import here to avoid circular dependencies
    from bot.trading_logic.signal.MOMENTUM.isConfirmed import check as momentum_check
    
    return bool(momentum_check(indicators))


def iceberg_execution_ok(order_book: Optional[Dict], symbol: str, cfg: Optional[Dict] = None) -> bool:
    """Iceberg order execution filter.
    
    Checks order book for iceberg order patterns (market manipulation).
    This filter blocks entry if iceberg patterns are detected.
    
    Returns:
        True if OK to trade (no iceberg detected)
        False if iceberg detected (should block entry)
    """
    if not order_book or not symbol:
        return True  # If can't fetch order book, allow entry (fail open)
    
    # Import here to avoid circular dependencies
    from bot.trading_logic.signal.ICEBERG.isConfirmed import detect_iceberg_orders
    
    # Default config values
    max_history = 5
    stability_threshold = 0.95
    refill_time_window = 2.0
    
    if cfg:
        max_history = int(cfg.get("max_history", max_history))
        stability_threshold = float(cfg.get("stability_threshold", stability_threshold))
        refill_time_window = float(cfg.get("refill_time_window", refill_time_window))
    
    iceberg_detected = detect_iceberg_orders(
        order_book,
        symbol,
        max_history=max_history,
        stability_threshold=stability_threshold,
        refill_time_window=refill_time_window,
    )
    
    # Return True if NO iceberg detected (OK to trade)
    return not iceberg_detected


