"""Position sizing: fractional Kelly capped by a drawdown budget (Kelly 1956; Thorp 2006; Chan 2009 ch. 6)."""
from __future__ import annotations


def kelly_leverage(mean_excess: float, variance: float) -> float:
    """Growth-optimal leverage for Gaussian returns: mean excess return over variance (same period)."""
    if variance <= 0:
        raise ValueError("variance must be positive")
    return mean_excess / variance


def capped_kelly(mean_excess: float, variance: float, worst_period_loss: float, max_drawdown: float,
                 fraction: float = 0.5) -> float:
    """Default sizing: `fraction` of Kelly, never more than the leverage at which the worst observed
    one-period loss would by itself use up the drawdown budget. Returns a signed leverage."""
    if not 0 < fraction <= 1 or worst_period_loss <= 0 or not 0 < max_drawdown < 1:
        raise ValueError("need 0 < fraction <= 1, worst_period_loss > 0, 0 < max_drawdown < 1")
    f = fraction * kelly_leverage(mean_excess, variance)
    cap = max_drawdown / worst_period_loss
    return max(-cap, min(cap, f))
