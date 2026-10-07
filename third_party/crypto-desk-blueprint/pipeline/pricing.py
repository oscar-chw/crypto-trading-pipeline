"""No-arbitrage carry: fair value of dated futures, the no-arbitrage band, and perpetual funding cash flows.

Cost of carry: holding spot for tau years costs the quote-currency rate and earns the base-asset yield
(lending or staking), so a future with no arbitrage trades at S * exp((r_quote - r_base) * tau).
Rates are continuously compounded per year. Options are out of scope.
"""
from __future__ import annotations

import math

from pipeline.types import NS_PER_YEAR, UtcNanos


def year_fraction(t: UtcNanos, expiry: UtcNanos) -> float:
    if expiry <= t:
        raise ValueError("contract has expired")
    return (expiry - t) / NS_PER_YEAR


def fair_forward(spot: float, r_quote: float, r_base: float, tau: float) -> float:
    if spot <= 0 or tau < 0:
        raise ValueError("need spot > 0 and tau >= 0")
    return spot * math.exp((r_quote - r_base) * tau)


def implied_carry(spot: float, forward: float, tau: float) -> float:
    """Annualised basis: the carry rate the market price implies."""
    if spot <= 0 or forward <= 0 or tau <= 0:
        raise ValueError("need positive prices and tau")
    return math.log(forward / spot) / tau


def no_arbitrage_band(spot: float, tau: float, *, r_quote_borrow: float, r_quote_lend: float,
                      r_base_borrow: float, r_base_lend: float, round_trip_cost: float) -> tuple[float, float]:
    """Prices outside (low, high) can be locked in as profit after costs.

    high: borrow quote, buy spot, lend it out, sell the future (cash and carry).
    low:  borrow the base asset, sell it, lend the quote, buy the future (reverse cash and carry).
    """
    if round_trip_cost < 0 or r_quote_borrow < r_quote_lend or r_base_borrow < r_base_lend:
        raise ValueError("borrow rates must be >= lend rates and costs >= 0")
    high = spot * (1 + round_trip_cost) * math.exp((r_quote_borrow - r_base_lend) * tau)
    low = spot * (1 - round_trip_cost) * math.exp((r_quote_lend - r_base_borrow) * tau)
    return low, high


def annualize_funding(rate_per_interval: float, interval_hours: float) -> float:
    """Simple annualisation of a per-interval funding rate (365 days of 24 hours)."""
    if interval_hours <= 0:
        raise ValueError("interval_hours must be positive")
    return rate_per_interval * 365 * 24 / interval_hours


def funding_cashflow(position_qty: float, mark_price: float, rate: float) -> float:
    """Cash received by the holder at a funding time. Longs pay when the rate is positive."""
    return -position_qty * mark_price * rate
