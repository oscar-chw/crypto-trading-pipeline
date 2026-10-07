from typing import Dict, Optional

from bot.data.types import Position


def evaluate_dynamic_sl_tp(
    position: Position,
    current_price: float,
    cfg: Dict,
    bb_lower: Optional[float] = None,
    bb_upper: Optional[float] = None,
    rsi_value: Optional[float] = None,
    macd_bearish_div: Optional[bool] = None,
    fee_rate: float = 0.0,
) -> Dict:
    dynamic = bool(cfg.get("dynamic", True))

    # Use original entry cost as reference
    base_price = position.entry_price if getattr(position, "entry_price", None) else position.avg_price

    # Strict branch separation
    if dynamic:
        # Dynamic ladder only (no direct OR exits here). Non-regressive tiers.
        initial_sl = float(cfg.get("0_stop_loss", 0.02))
        # Adjust stop threshold to be net-of-fees: price <= base*(1 - sl + 2f)
        threshold_entry = base_price * (1.0 - initial_sl + 2.0 * float(fee_rate)) if initial_sl > 0 else None
        levels = [
            (1, float(cfg.get("1_take_gain", 0.015)), float(cfg.get("1_stop_loss_by_cost", 0.0)), float(cfg.get("1_sell_portion", 0.3))),
            (2, float(cfg.get("2_take_gain", 0.03)), float(cfg.get("2_stop_loss_by_cost", 0.015)), float(cfg.get("2_sell_portion", 0.3))),
            (3, float(cfg.get("3_take_gain", 0.05)), float(cfg.get("3_stop_loss_by_cost", 0.03)), float(cfg.get("3_sell_portion", 0.4))),
        ]
        pnl_ratio = (current_price - base_price) / base_price
        highest_reached = int(getattr(position, "highest_tier_reached", 0) or 0)
        reached_now = 0
        # Find the highest tier reached (iterate in reverse to find highest first)
        # Use a small epsilon for floating point comparison to handle precision issues
        epsilon = 1e-8
        for tier, target_gain, _, _ in reversed(levels):
            # Require net-of-fees gain: >= target + 2f (with epsilon for floating point precision)
            required = target_gain + 2.0 * float(fee_rate)
            if pnl_ratio >= (required - epsilon):
                reached_now = tier
                break  # Found highest tier, no need to check lower tiers
        # Determine effective tier (non-regressive: once a level is reached, never go back)
        # Use max to ensure we only progress forward, never regress
        effective_tier = max(highest_reached, reached_now)
        # Only trigger action if we're crossing into a NEW tier (not already at or past it)
        if effective_tier > highest_reached:
            # We are crossing into a new tier
            for tier, _, stop_by_cost, sell_portion in levels:
                if tier == effective_tier:
                    # Tier 3: liquidate completely
                    if tier == 3:
                        return {
                            "action": "exit",
                            "sell_fraction": 1.0,
                            # Keep stop consistent but net-of-fees cushion on display
                            "new_stop": base_price * (1.0 + stop_by_cost - 2.0 * float(fee_rate)),
                            "tier": effective_tier,
                        }
                    # Tiers 1-2: partial take and raise stop
                    return {
                        "action": "partial_take",
                        "sell_fraction": sell_portion,
                        # Net-of-fees: lower stop by ~2f to preserve target after fees
                        "new_stop": base_price * (1.0 + stop_by_cost - 2.0 * float(fee_rate)),
                        "tier": effective_tier,
                    }
        # Not crossing a new tier: hold, but keep stop at the highest tier reached (non-regressive)
        # This ensures once a level is reached, we maintain that level's stop-loss even if price drops
        # We never regress to a lower tier's stop-loss
        if effective_tier > 0:
            for tier, _, stop_by_cost, _ in levels:
                if tier == effective_tier:
                    # Maintain the stop-loss of the highest tier reached (non-regressive)
                    return {"action": "hold", "sell_fraction": 0.0, "new_stop": base_price * (1.0 + stop_by_cost - 2.0 * float(fee_rate)), "tier": effective_tier}
        # No ladder hit yet → keep base stop
        return {"action": "hold", "sell_fraction": 0.0, "new_stop": threshold_entry, "tier": 0}
    else:
        # Static branch
        # Direct profit-taking (static)
        if (bb_upper is not None and current_price >= float(bb_upper)) or \
           (rsi_value is not None and float(rsi_value) > 70.0) or \
           (bool(macd_bearish_div)):
            return {"action": "exit", "sell_fraction": 1.0, "new_stop": None}

        # Direct stop-loss (static)
        initial_sl = float(cfg.get("0_stop_loss", 0.02))
        # Net-of-fees threshold (exit slightly earlier to cover fees): base*(1 - sl + 2f)
        threshold_entry = base_price * (1.0 - initial_sl + 2.0 * float(fee_rate)) if initial_sl > 0 else None
        if (threshold_entry is not None and current_price <= threshold_entry) or \
           (bb_lower is not None and current_price <= float(bb_lower)):
            candidates = []
            if threshold_entry is not None and current_price <= threshold_entry:
                candidates.append(threshold_entry)
            if bb_lower is not None and current_price <= float(bb_lower):
                candidates.append(float(bb_lower))
            new_stop = min(candidates) if candidates else threshold_entry
            return {"action": "exit", "sell_fraction": 1.0, "new_stop": new_stop}

        # Static hold with base stop
        new_stop = base_price * (1.0 - initial_sl) if initial_sl > 0 else None
        return {"action": "hold", "sell_fraction": 0.0, "new_stop": new_stop}


