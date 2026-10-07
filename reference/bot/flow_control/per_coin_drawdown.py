from bot.data.types import Position


def is_coin_drawdown_exceeded(pos: Position, current_price: float, max_usd_loss: float) -> bool:
    if not pos:
        return False
    # Use the filled entry price for loss threshold checks per strategy
    entry_price = float(pos.entry_price or pos.avg_price or 0.0)
    loss_usdt = max(0.0, (entry_price - current_price)) * pos.quantity
    return loss_usdt >= max_usd_loss


def is_coin_daily_drawdown_exceeded(pos: Position, current_price: float, max_usd_loss: float, today: str) -> bool:
    """Check per-coin max loss per day using peak-to-trough drawdown.

    Tracks the peak equity per coin during the day and triggers when:
    peak_equity - current_equity > max_usd_loss

    This ensures losses accumulate from the peak, not from the baseline.
    Example: Start $10k, gain to $10.2k (peak), drop to $9.4k → loss = $800
    """
    if not pos:
        return False
    
    # Calculate current equity for this coin
    current_equity = float(current_price * pos.quantity)
    
    # Initialize or reset peak if date changed
    if getattr(pos, "daily_date", "") != today:
        pos.daily_peak_equity = current_equity
        pos.daily_date = today
    elif getattr(pos, "daily_peak_equity", None) is None:
        pos.daily_peak_equity = current_equity
    
    # Update peak equity if current is higher (new peak reached)
    peak_equity = float(getattr(pos, "daily_peak_equity", current_equity) or current_equity)
    if current_equity > peak_equity:
        pos.daily_peak_equity = current_equity
        peak_equity = current_equity
    
    # Calculate loss from peak: peak_equity - current_equity
    # This accumulates losses from the highest point reached during the day
    loss_usdt = max(0.0, peak_equity - current_equity)
    
    return loss_usdt >= max_usd_loss


