from typing import Dict, Optional


def check(orderbook: Optional[Dict], current_price: float, config: Dict) -> bool:
    """Check order book pressure (buying pressure near current price).
    
    Order book pressure measures the volume of buy orders near the current price.
    High buying pressure near the price indicates bullish momentum.
    
    Args:
        orderbook: Order book data with 'bids' and 'asks' lists
        current_price: Current market price
        config: Configuration dict with 'orderbook_pressure_threshold' (default: 1.5)
                 and 'orderbook_pressure_range' (default: 0.01 = 1%)
    
    Returns:
        True if order book shows strong buying pressure near current price
    """
    if not orderbook or current_price <= 0:
        return False
    
    bids = orderbook.get('bids', [])
    asks = orderbook.get('asks', [])
    
    if not bids or not asks:
        return False
    
    # Price range to check (default: 1% above/below current price)
    price_range = float(config.get('orderbook_pressure_range', 0.01))
    lower_bound = current_price * (1 - price_range)
    upper_bound = current_price * (1 + price_range)
    
    # Calculate bid volume near current price (buying pressure)
    bid_pressure = 0.0
    for bid in bids:
        if len(bid) >= 2:
            bid_price = float(bid[0])
            bid_volume = float(bid[1])
            if lower_bound <= bid_price <= upper_bound:
                bid_pressure += bid_volume
    
    # Calculate ask volume near current price (selling pressure)
    ask_pressure = 0.0
    for ask in asks:
        if len(ask) >= 2:
            ask_price = float(ask[0])
            ask_volume = float(ask[1])
            if lower_bound <= ask_price <= upper_bound:
                ask_pressure += ask_volume
    
    if ask_pressure == 0:
        return False
    
    # Calculate pressure ratio (bid/ask)
    pressure_ratio = bid_pressure / ask_pressure
    
    # Threshold: pressure ratio > threshold indicates bullish pressure
    threshold = float(config.get('orderbook_pressure_threshold', 1.5))
    
    return pressure_ratio >= threshold

