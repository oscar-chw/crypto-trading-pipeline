"""Data that crosses a stage boundary. Every record is frozen and validates itself on construction.

Time is always an int of nanoseconds since the Unix epoch, UTC (`UtcNanos`). Every record that comes
from outside carries `available_at`: the moment the system could first have known it. Point-in-time
correctness is checked against that field, never against the event time alone.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

import pandas as pd

UtcNanos = int
NS_PER_SECOND = 1_000_000_000
NS_PER_HOUR = 3_600 * NS_PER_SECOND
NS_PER_DAY = 24 * NS_PER_HOUR
NS_PER_YEAR = 365 * NS_PER_DAY  # crypto trades every calendar day, so a year is 365 days, not 252


def _finite(name: str, *values: float) -> None:
    for v in values:
        if not math.isfinite(v):
            raise ValueError(f"{name} must be finite, got {v!r}")


def _frozen_map(obj: object, name: str) -> None:
    m = dict(getattr(obj, name))
    _finite(name, *m.values())
    object.__setattr__(obj, name, MappingProxyType(m))


@dataclass(frozen=True)
class Instrument:
    instrument_id: str  # "<venue>:<symbol>:<kind>", e.g. "binance:BTCUSDT:perp"
    venue: str
    symbol: str
    kind: Literal["spot", "perp", "future"]
    base: str
    quote: str
    expiry: UtcNanos | None = None

    def __post_init__(self) -> None:
        if (self.kind == "future") != (self.expiry is not None):
            raise ValueError("a dated future needs an expiry; spot and perp must not have one")


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar covering (open_time, close_time]. It is stamped by its close."""

    instrument_id: str
    open_time: UtcNanos
    close_time: UtcNanos
    open: float
    high: float
    low: float
    close: float
    volume: float
    available_at: UtcNanos

    def __post_init__(self) -> None:
        _finite("bar prices", self.open, self.high, self.low, self.close, self.volume)
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time")
        if self.available_at < self.close_time:
            raise ValueError("a bar cannot be known before it closes")
        if not (0 < self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high):
            raise ValueError(f"inconsistent OHLC: {self}")
        if self.volume < 0:
            raise ValueError("volume must be >= 0")


def bars_to_frame(bars: list[Bar]) -> pd.DataFrame:
    """Bars as a DataFrame indexed by close_time (int ns), the shape every Feature consumes."""
    cols = ["open", "high", "low", "close", "volume"]
    frame = pd.DataFrame([[getattr(b, c) for c in cols] for b in bars], columns=cols,
                         index=pd.Index([b.close_time for b in bars], name="close_time"))
    return frame


@dataclass(frozen=True)
class FundingEvent:
    """A perpetual-swap funding print: `rate` per funding interval, paid by longs when positive."""

    instrument_id: str
    funding_time: UtcNanos
    rate: float
    interval_hours: float
    available_at: UtcNanos

    def __post_init__(self) -> None:
        _finite("funding rate", self.rate, self.interval_hours)
        if self.interval_hours <= 0 or self.available_at < self.funding_time:
            raise ValueError("bad funding event")


@dataclass(frozen=True)
class Signal:
    """A strategy's view: `score` in [-1, 1] (sign = side, size = conviction). Strategies never size."""

    instrument_id: str
    t: UtcNanos
    score: float
    horizon_ns: int
    model_id: str

    def __post_init__(self) -> None:
        _finite("signal score", self.score)
        if not -1.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [-1, 1], got {self.score}")
        if self.horizon_ns <= 0:
            raise ValueError("horizon_ns must be positive")


@dataclass(frozen=True)
class FairValue:
    instrument_id: str
    t: UtcNanos
    fair_price: float
    band_low: float
    band_high: float

    def __post_init__(self) -> None:
        _finite("fair value", self.fair_price, self.band_low, self.band_high)
        if not 0 < self.band_low <= self.fair_price <= self.band_high:
            raise ValueError("need 0 < band_low <= fair_price <= band_high")


@dataclass(frozen=True)
class RiskForecast:
    """Per-period volatility forecast per instrument, for the period after `t`."""

    t: UtcNanos
    vol: Mapping[str, float]
    periods_per_year: float

    def __post_init__(self) -> None:
        _frozen_map(self, "vol")
        if any(v <= 0 for v in self.vol.values()):
            raise ValueError("volatility forecasts must be positive")


@dataclass(frozen=True)
class TargetPortfolio:
    """Signed target weights as a fraction of equity (0.5 = long half the equity in notional)."""

    t: UtcNanos
    weights: Mapping[str, float]

    def __post_init__(self) -> None:
        _frozen_map(self, "weights")

    @property
    def gross(self) -> float:
        return sum(abs(w) for w in self.weights.values())


@dataclass(frozen=True)
class AccountState:
    t: UtcNanos
    equity: float
    positions: Mapping[str, float]  # signed quantity in base units
    prices: Mapping[str, float]  # mark price per instrument

    def __post_init__(self) -> None:
        _finite("equity", self.equity)
        _frozen_map(self, "positions")
        _frozen_map(self, "prices")

    def weight(self, instrument_id: str) -> float:
        return self.positions.get(instrument_id, 0.0) * self.prices[instrument_id] / self.equity


@dataclass(frozen=True)
class OrderIntent:
    instrument_id: str
    t: UtcNanos
    qty: float  # signed: + buy, - sell
    reduce_only: bool
    client_id: str  # idempotency key: resending the same id must never create a second order

    def __post_init__(self) -> None:
        _finite("order qty", self.qty)
        if self.qty == 0:
            raise ValueError("zero-quantity order")


@dataclass(frozen=True)
class Fill:
    client_id: str
    instrument_id: str
    t: UtcNanos
    qty: float
    price: float
    fee: float  # in quote currency; negative for a maker rebate

    def __post_init__(self) -> None:
        _finite("fill", self.qty, self.price, self.fee)
        if self.price <= 0:
            raise ValueError("fill price must be positive")
