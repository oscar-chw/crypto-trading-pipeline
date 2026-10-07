from typing import Dict, Optional


def check(orderbook: Optional[Dict], config: Dict) -> bool:
    """Check for large orders in the order book (potential support/resistance).
    
    Large orders in the order book can indicate significant support (bids) or resistance (asks).
    This signal checks if there are large buy orders (bids) that could act as support.
    
    Args:
        orderbook: Order book data with 'bids' and 'asks' lists
        config: Configuration dict with 'orderbook_large_order_threshold' (default: 0.01)
                 and 'orderbook_large_order_levels' (default: 10)
    
    Returns:
        True if order book shows large buy orders (strong support)
    """
    if not orderbook:
        return False
    
    bids = orderbook.get('bids', [])
    
    if not bids:
        return False
    
    # Get number of levels to check
    levels = int(config.get('orderbook_large_order_levels', 10))
    
    # Threshold for "large" order (default: 1% of average volume)
    threshold = float(config.get('orderbook_large_order_threshold', 0.01))
    
    # Check for large orders in bids (buy support)
    large_bid_orders = 0
    for bid in bids[:levels]:
        if len(bid) >= 2:
            bid_volume = float(bid[1])
            if bid_volume >= threshold:
                large_bid_orders += 1
    
    # Require at least 2 large buy orders for strong support
    min_large_orders = int(config.get('orderbook_min_large_orders', 2))
    
    return large_bid_orders >= min_large_orders

