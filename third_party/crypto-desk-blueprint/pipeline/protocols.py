"""The contract of each stage. An implementation satisfies a stage when it matches the Protocol here and
passes that stage's suite in conformance/stages/. The blueprint/0N-*.md files say why each rule exists."""
from __future__ import annotations

from typing import Iterator, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np
import pandas as pd

from pipeline.risk import KillSwitch, RiskDecision
from pipeline.types import (AccountState, Bar, FairValue, Fill, OrderIntent, RiskForecast, Signal,
                            TargetPortfolio, UtcNanos)


@runtime_checkable
class DataSource(Protocol):  # stage 01
    def bars(self, instrument_id: str, start: UtcNanos, end: UtcNanos) -> list[Bar]:
        """Bars with start < close_time <= end, strictly increasing, no gaps filled in."""


@runtime_checkable
class Feature(Protocol):  # stage 02
    name: str
    lookback: int  # bars needed for the first value; earlier outputs are NaN

    def compute(self, bars: pd.DataFrame) -> pd.Series:
        """Same index as `bars` (close_time). The value at t depends only on rows with close_time <= t."""


@runtime_checkable
class Strategy(Protocol):  # stage 03
    model_id: str

    def signal(self, instrument_id: str, t: UtcNanos, features: Mapping[str, float]) -> Signal:
        """A view at decision time t. Missing (NaN) inputs mean no view: score 0."""


@runtime_checkable
class PricingModel(Protocol):  # stage 04
    def fair_value(self, instrument_id: str, t: UtcNanos, spot: float, expiry: UtcNanos,
                   r_quote: float, r_base: float) -> FairValue: ...

    def funding_cashflow(self, position_qty: float, mark_price: float, rate: float) -> float: ...


@runtime_checkable
class RiskModel(Protocol):  # stage 05
    def forecast(self, t: UtcNanos, returns: pd.DataFrame) -> RiskForecast:
        """Volatility for the period after t from rows with index <= t only."""


@runtime_checkable
class RiskGate(Protocol):  # stage 05 (pipeline.risk.RiskEngine is the reference)
    kill_switch: KillSwitch

    def update_equity(self, t: UtcNanos, equity: float) -> None: ...

    def check(self, target: TargetPortfolio, current: Mapping[str, float]) -> RiskDecision: ...


@runtime_checkable
class PortfolioConstructor(Protocol):  # stage 06
    max_gross: float

    def target(self, t: UtcNanos, signals: Sequence[Signal], risk: RiskForecast) -> TargetPortfolio: ...


@runtime_checkable
class Executor(Protocol):  # stage 07
    def orders(self, target: TargetPortfolio, account: AccountState) -> list[OrderIntent]:
        """Orders that move the account's positions to the target weights."""


@runtime_checkable
class ExecutionVenue(Protocol):  # stage 07: the paper venue and the live adapter share this
    def submit(self, order: OrderIntent, mid: float, bar_volume: float) -> Fill: ...


@runtime_checkable
class Splitter(Protocol):  # stage 08
    embargo_ns: int

    def split(self, t0: np.ndarray, t1: np.ndarray) -> Iterator[tuple[np.ndarray, np.ndarray]]: ...
