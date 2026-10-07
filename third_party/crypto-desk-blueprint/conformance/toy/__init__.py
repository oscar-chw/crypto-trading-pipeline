"""Toy implementation of every stage: small, complete, and passing every conformance suite.

The strategy here is a PLACEHOLDER (trailing momentum squashed into [-1, 1]). It exists so the pipeline
runs end to end; nothing about it is a claim that it makes money.
"""
from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from pipeline import pricing
from pipeline.clock import SimClock
from pipeline.costs import CostModel
from pipeline.cv import PurgedKFold
from pipeline.risk import RiskEngine, RiskLimits
from pipeline.stats import deflated_sharpe_ratio
from pipeline.store import PointInTimeStore
from pipeline.types import (NS_PER_HOUR, NS_PER_SECOND, AccountState, Bar, FairValue, Fill, OrderIntent,
                            RiskForecast, Signal, TargetPortfolio, UtcNanos)

T0 = 1_704_067_200 * NS_PER_SECOND  # 2024-01-01T00:00:00Z
TOY_ID = "toy:BTCUSDT:spot"
DATA_SAMPLE = (TOY_ID, T0, T0 + 500 * NS_PER_HOUR)
STRATEGY_FEATURES = ("momentum",)


class SyntheticBars:
    """Hourly geometric-random-walk bars, generated once from a seed so every read is replayable."""

    def __init__(self, n: int = 2_000, seed: int = 7) -> None:
        rng = np.random.default_rng(seed)
        close = 30_000 * np.exp(np.cumsum(rng.normal(0, 0.005, n)))
        opens = np.r_[30_000, close[:-1]]
        wick = np.abs(rng.normal(0, 0.002, n))
        self._bars = [Bar(TOY_ID, T0 + i * NS_PER_HOUR, T0 + (i + 1) * NS_PER_HOUR, float(opens[i]),
                          float(max(opens[i], close[i]) * (1 + wick[i])),
                          float(min(opens[i], close[i]) * (1 - wick[i])), float(close[i]),
                          float(rng.lognormal(3, 0.5)), T0 + (i + 1) * NS_PER_HOUR + NS_PER_SECOND)
                      for i in range(n)]

    def bars(self, instrument_id: str, start: UtcNanos, end: UtcNanos) -> list[Bar]:
        return [b for b in self._bars if b.instrument_id == instrument_id and start < b.close_time <= end]


class Momentum:
    name = "momentum"

    def __init__(self, window: int = 24) -> None:
        self.window = window
        self.lookback = window + 1

    def compute(self, bars: pd.DataFrame) -> pd.Series:
        return np.log(bars["close"]).diff(self.window).rename(self.name)


class PlaceholderStrategy:
    model_id = "placeholder-momentum"

    def __init__(self, scale: float = 0.05) -> None:
        self.scale = scale

    def signal(self, instrument_id: str, t: UtcNanos, features: Mapping[str, float]) -> Signal:
        x = features.get("momentum", math.nan)
        score = 0.0 if not math.isfinite(x) else math.tanh(x / self.scale)
        return Signal(instrument_id, t, score, 24 * NS_PER_HOUR, self.model_id)


class CarryPricing:
    def __init__(self, round_trip_cost: float = 0.001) -> None:
        self.round_trip_cost = round_trip_cost

    def fair_value(self, instrument_id: str, t: UtcNanos, spot: float, expiry: UtcNanos,
                   r_quote: float, r_base: float) -> FairValue:
        tau = pricing.year_fraction(t, expiry)
        fair = pricing.fair_forward(spot, r_quote, r_base, tau)
        low, high = pricing.no_arbitrage_band(spot, tau, r_quote_borrow=r_quote, r_quote_lend=r_quote,
                                              r_base_borrow=r_base, r_base_lend=r_base,
                                              round_trip_cost=self.round_trip_cost)
        return FairValue(instrument_id, t, fair, low, high)

    def funding_cashflow(self, position_qty: float, mark_price: float, rate: float) -> float:
        return pricing.funding_cashflow(position_qty, mark_price, rate)


class EwmaVol:
    """RiskMetrics-style EWMA volatility; the baseline any GARCH model has to beat out of sample."""

    def __init__(self, lam: float = 0.94, periods_per_year: float = 365 * 24) -> None:
        self.lam, self.periods_per_year = lam, periods_per_year

    def forecast(self, t: UtcNanos, returns: pd.DataFrame) -> RiskForecast:
        past = returns.loc[:t]
        if len(past) < 2:
            raise ValueError("need at least two past returns")
        var = (past ** 2).ewm(alpha=1 - self.lam, adjust=False).mean().iloc[-1]
        return RiskForecast(t, {k: math.sqrt(max(float(v), 1e-16)) for k, v in var.items()},
                            self.periods_per_year)


class VolScaledPortfolio:
    """Weight = score x (target vol / forecast vol), clipped per instrument, then scaled to the gross cap."""

    def __init__(self, target_vol_annual: float = 0.20, max_weight: float = 0.5, max_gross: float = 1.0):
        self.target_vol_annual, self.max_weight, self.max_gross = target_vol_annual, max_weight, max_gross

    def target(self, t: UtcNanos, signals: Sequence[Signal], risk: RiskForecast) -> TargetPortfolio:
        per_period = self.target_vol_annual / math.sqrt(risk.periods_per_year)
        w = {s.instrument_id: max(-self.max_weight, min(self.max_weight,
                                                         s.score * per_period / risk.vol[s.instrument_id]))
             for s in signals}
        gross = sum(abs(v) for v in w.values())
        if gross > self.max_gross:
            w = {k: v * self.max_gross / gross for k, v in w.items()}
        return TargetPortfolio(t, w)


class DeltaExecutor:
    def __init__(self, min_notional: float = 1.0) -> None:
        self.min_notional = min_notional

    def orders(self, target: TargetPortfolio, account: AccountState) -> list[OrderIntent]:
        out = []
        for k in sorted(set(target.weights) | set(account.positions)):
            price = account.prices[k]
            current = account.positions.get(k, 0.0)
            desired = target.weights.get(k, 0.0) * account.equity / price
            delta = desired - current
            if abs(delta) * price < self.min_notional:
                continue
            reduce_only = abs(desired) <= abs(current) and desired * current >= 0
            out.append(OrderIntent(k, target.t, delta, reduce_only, f"{k}:{target.t}"))
        return out


class PaperVenue:
    def __init__(self, costs: CostModel | None = None) -> None:
        self.costs = costs or CostModel()

    def submit(self, order: OrderIntent, mid: float, bar_volume: float) -> Fill:
        price = self.costs.fill_price(mid, order.qty, bar_volume)
        return Fill(order.client_id, order.instrument_id, order.t, order.qty, price,
                    self.costs.fee(price * order.qty))


def make_data_source() -> SyntheticBars:
    return SyntheticBars()


def make_feature() -> Momentum:
    return Momentum()


def make_strategy() -> PlaceholderStrategy:
    return PlaceholderStrategy()


def make_pricing() -> CarryPricing:
    return CarryPricing()


def make_risk_model() -> EwmaVol:
    return EwmaVol()


def make_risk_engine(limits: RiskLimits) -> RiskEngine:
    return RiskEngine(limits)


def make_portfolio() -> VolScaledPortfolio:
    return VolScaledPortfolio()


def make_executor() -> DeltaExecutor:
    return DeltaExecutor()


def make_venue() -> PaperVenue:
    return PaperVenue()


def make_cv_splitter() -> PurgedKFold:
    return PurgedKFold(n_splits=5, embargo_ns=24 * NS_PER_HOUR)


def make_clock(start: UtcNanos) -> SimClock:
    return SimClock(start)


def make_store() -> PointInTimeStore:
    return PointInTimeStore()


deflated_sharpe = deflated_sharpe_ratio
