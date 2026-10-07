"""Fee and slippage model. Every backtest fill and every paper fill goes through it.

Taker fills pay the fee, cross half the spread and pay square-root market impact on the share of the bar's
volume they take. Maker fills earn the half spread back and pay the maker fee (which may be negative).
The defaults are placeholders: set them from your venue's fee tier and your own measured spreads.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Liquidity = Literal["taker", "maker"]


@dataclass(frozen=True)
class CostModel:
    taker_fee_bps: float = 5.0
    maker_fee_bps: float = 1.0
    half_spread_bps: float = 1.0
    impact_bps_at_full_volume: float = 50.0  # impact if one order took the whole bar's volume
    max_participation: float = 0.10  # refuse orders larger than this share of bar volume

    def __post_init__(self) -> None:
        if min(self.taker_fee_bps, self.half_spread_bps, self.impact_bps_at_full_volume) < 0:
            raise ValueError("taker fee, spread and impact must be >= 0")
        if not 0 < self.max_participation <= 1:
            raise ValueError("max_participation must be in (0, 1]")

    def slippage_bps(self, qty: float, bar_volume: float, liquidity: Liquidity = "taker") -> float:
        """Signed-free slippage in bps against mid. Positive = worse than mid."""
        if liquidity == "maker":
            return -self.half_spread_bps
        if bar_volume <= 0:
            raise ValueError("no volume: cannot fill a taker order in this bar")
        participation = abs(qty) / bar_volume
        if participation > self.max_participation:
            raise ValueError(f"participation {participation:.3f} exceeds cap {self.max_participation}")
        return self.half_spread_bps + self.impact_bps_at_full_volume * math.sqrt(participation)

    def fill_price(self, mid: float, qty: float, bar_volume: float, liquidity: Liquidity = "taker") -> float:
        if qty == 0 or mid <= 0:
            raise ValueError("need a non-zero quantity and a positive mid")
        side = 1.0 if qty > 0 else -1.0
        return mid * (1.0 + side * self.slippage_bps(qty, bar_volume, liquidity) / 1e4)

    def fee(self, notional: float, liquidity: Liquidity = "taker") -> float:
        bps = self.taker_fee_bps if liquidity == "taker" else self.maker_fee_bps
        return abs(notional) * bps / 1e4

    def total_cost(self, mid: float, qty: float, bar_volume: float, liquidity: Liquidity = "taker") -> float:
        """Cost in quote currency versus trading at mid with no fee."""
        price = self.fill_price(mid, qty, bar_volume, liquidity)
        return (price - mid) * qty + self.fee(price * qty, liquidity)
