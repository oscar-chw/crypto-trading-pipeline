from typing import Dict, Optional


def check(orderbook: Optional[Dict], config: Dict) -> bool:
    """Check order book depth (total volume at best prices).
    
    Order book depth measures the total volume available at the best bid/ask prices.
    Higher depth indicates stronger support/resistance and more liquidity.
    
    Args:
        orderbook: Order book data with 'bids' and 'asks' lists
        config: Configuration dict with 'orderbook_depth_threshold' (default: 0.001)
                 and 'orderbook_depth_levels' (default: 5)
    
    Returns:
        True if order book shows sufficient depth (strong support)
    """
    if not orderbook:
        return False
    
    bids = orderbook.get('bids', [])
    asks = orderbook.get('asks', [])
    
    if not bids or not asks:
        return False
    
    # Get number of levels to check
    levels = int(config.get('orderbook_depth_levels', 5))
    
    # Calculate total bid volume at best prices (support)
    bid_depth = sum(float(bid[1]) for bid in bids[:levels] if len(bid) >= 2)
    
    # Calculate total ask volume at best prices (resistance)
    ask_depth = sum(float(ask[1]) for ask in asks[:levels] if len(ask) >= 2)
    
    # Threshold: minimum depth required
    threshold = float(config.get('orderbook_depth_threshold', 0.001))
    
    # Check if both sides have sufficient depth (liquidity)
    return bid_depth >= threshold and ask_depth >= threshold

