from typing import Dict, List, Optional
import time
from collections import deque

# Store recent order book snapshots per symbol
_order_book_history: Dict[str, deque] = {}


def detect_iceberg_orders(
    order_book: Dict[str, List],
    symbol: str,
    max_history: int = 5,
    stability_threshold: float = 0.95,
    refill_time_window: float = 2.0,
) -> bool:
    """Detect iceberg order patterns in the order book.
    
    Iceberg orders are characterized by:
    1. Small visible orders that get consumed
    2. Orders immediately refilled at the same price levels
    3. Stable total volume despite consumption
    4. Consistent order sizes at the same price levels
    
    Returns:
        True if iceberg pattern detected (should BLOCK entry)
        False if no iceberg pattern (allow entry)
    """
    if not order_book or 'bids' not in order_book or 'asks' not in order_book:
        return False
    
    bids = order_book.get('bids', [])
    asks = order_book.get('asks', [])
    
    if not bids or not asks:
        return False
    
    # Initialize history for this symbol
    if symbol not in _order_book_history:
        _order_book_history[symbol] = deque(maxlen=max_history)
    
    current_time = time.time()
    current_snapshot = {
        'timestamp': current_time,
        'bids': [(float(b[0]), float(b[1])) for b in bids],
        'asks': [(float(a[0]), float(a[1])) for a in asks],
    }
    
    _order_book_history[symbol].append(current_snapshot)
    
    # Need at least 2 snapshots to detect patterns
    if len(_order_book_history[symbol]) < 2:
        return False
    
    history = list(_order_book_history[symbol])
    
    # Check for iceberg patterns
    # Pattern 1: Orders consumed and immediately refilled at same price
    if len(history) >= 2:
        prev = history[-2]
        curr = history[-1]
        
        # Check if orders at same price levels are being refilled
        # This indicates iceberg orders (hidden large orders)
        bid_refill_count = 0
        ask_refill_count = 0
        
        # Check bid side (buy orders)
        prev_bid_prices = {price: qty for price, qty in prev['bids'][:5]}  # Top 5 levels
        curr_bid_prices = {price: qty for price, qty in curr['bids'][:5]}
        
        for price, prev_qty in prev_bid_prices.items():
            if price in curr_bid_prices:
                curr_qty = curr_bid_prices[price]
                # If quantity was reduced but then refilled to similar size
                # This suggests iceberg order refilling
                if prev_qty > 0 and curr_qty > 0:
                    # Check if quantity is stable (within 10% variation)
                    if abs(curr_qty - prev_qty) / max(prev_qty, curr_qty) < 0.1:
                        bid_refill_count += 1
        
        # Check ask side (sell orders)
        prev_ask_prices = {price: qty for price, qty in prev['asks'][:5]}  # Top 5 levels
        curr_ask_prices = {price: qty for price, qty in curr['asks'][:5]}
        
        for price, prev_qty in prev_ask_prices.items():
            if price in curr_ask_prices:
                curr_qty = curr_ask_prices[price]
                if prev_qty > 0 and curr_qty > 0:
                    if abs(curr_qty - prev_qty) / max(prev_qty, curr_qty) < 0.1:
                        ask_refill_count += 1
        
        # Pattern 2: Stable total volume despite consumption
        prev_total_bid_volume = sum(qty for _, qty in prev['bids'][:10])
        curr_total_bid_volume = sum(qty for _, qty in curr['bids'][:10])
        prev_total_ask_volume = sum(qty for _, qty in prev['asks'][:10])
        curr_total_ask_volume = sum(qty for _, qty in curr['asks'][:10])
        
        bid_volume_stable = abs(curr_total_bid_volume - prev_total_bid_volume) / max(prev_total_bid_volume, curr_total_bid_volume, 1) < 0.1
        ask_volume_stable = abs(curr_total_ask_volume - prev_total_ask_volume) / max(prev_total_ask_volume, curr_total_ask_volume, 1) < 0.1
        
        # Pattern 3: Consistent order sizes (same quantities at same prices)
        # This is a strong indicator of iceberg orders
        consistent_sizes = False
        if len(history) >= 3:
            # Check if order sizes are very similar across multiple snapshots
            sizes_prev = [qty for _, qty in prev['bids'][:3] + prev['asks'][:3]]
            sizes_curr = [qty for _, qty in curr['bids'][:3] + curr['asks'][:3]]
            if len(sizes_prev) == len(sizes_curr):
                variations = [abs(sizes_curr[i] - sizes_prev[i]) / max(sizes_prev[i], sizes_curr[i], 1) 
                              for i in range(len(sizes_prev))]
                consistent_sizes = all(v < 0.15 for v in variations)  # Within 15% variation
        
        # Detect iceberg pattern: multiple indicators suggest market manipulation
        iceberg_detected = (
            (bid_refill_count >= 2 or ask_refill_count >= 2) and  # Orders refilling
            (bid_volume_stable or ask_volume_stable) and  # Volume stable
            (time.time() - prev['timestamp'] < refill_time_window)  # Quick refill
        ) or (
            consistent_sizes and  # Very consistent sizes
            (bid_volume_stable and ask_volume_stable)  # Both sides stable
        )
        
        return iceberg_detected
    
    return False


def check(indicators: Dict, order_book: Optional[Dict[str, List]] = None, symbol: str = "") -> bool:
    """Check if order book shows iceberg order patterns.
    
    This function is called by the signal evaluator.
    It needs order_book and symbol to be passed from the trader.
    
    Returns:
        True if OK to trade (no iceberg detected)
        False if iceberg detected (should block entry)
    """
    if not order_book or not symbol:
        return True  # If can't fetch order book, allow entry (fail open)
    
    # Default config values
    max_history = 5
    stability_threshold = 0.95
    refill_time_window = 2.0
    
    iceberg_detected = detect_iceberg_orders(
        order_book,
        symbol,
        max_history=max_history,
        stability_threshold=stability_threshold,
        refill_time_window=refill_time_window,
    )
    
    # Return True if NO iceberg detected (OK to trade)
    return not iceberg_detected

