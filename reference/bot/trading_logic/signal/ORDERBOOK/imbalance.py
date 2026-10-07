from typing import Dict, Optional


def check(orderbook: Optional[Dict], config: Dict) -> bool:
    """Check order book imbalance (buying vs selling pressure).
    
    Order book imbalance measures the ratio of bid volume to ask volume.
    A high imbalance (>1.0) indicates more buying pressure (bullish).
    A low imbalance (<1.0) indicates more selling pressure (bearish).
    
    Args:
        orderbook: Order book data with 'bids' and 'asks' lists
        config: Configuration dict with 'orderbook_imbalance_threshold' (default: 1.2)
    
    Returns:
        True if order book shows bullish imbalance (more buying pressure)
    """
    if not orderbook:
        return False
    
    bids = orderbook.get('bids', [])
    asks = orderbook.get('asks', [])
    
    if not bids or not asks:
        return False
    
    # Calculate total bid volume (buying pressure)
    bid_volume = sum(float(bid[1]) for bid in bids if len(bid) >= 2)
    
    # Calculate total ask volume (selling pressure)
    ask_volume = sum(float(ask[1]) for ask in asks if len(ask) >= 2)
    
    if ask_volume == 0:
        return False
    
    # Calculate imbalance ratio (bid/ask)
    imbalance = bid_volume / ask_volume
    
    # Threshold: imbalance > threshold indicates bullish pressure
    threshold = float(config.get('orderbook_imbalance_threshold', 1.2))
    
    return imbalance >= threshold

