"""Risk-limits engine: per-instrument and gross caps, a daily loss halt, a drawdown budget and a kill switch.

Order of precedence in `check`: kill switch (flatten everything) > daily halt (reduce only) > caps (clip).
The kill switch latches: only a named human can re-arm it, because an automatic re-arm turns a stop into
a pause and the same fault trips it again with less capital.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping

from pipeline.types import NS_PER_DAY, TargetPortfolio, UtcNanos

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RiskLimits:
    max_weight: float = 0.25  # |notional| per instrument as a fraction of equity
    max_gross: float = 1.0  # sum of |weights|
    max_drawdown: float = 0.20  # from the equity high-water mark; trips the kill switch
    daily_loss_limit: float = 0.05  # from the UTC day's opening equity; reduce-only until the next day

    def __post_init__(self) -> None:
        if not (0 < self.max_weight and 0 < self.max_gross and 0 < self.max_drawdown < 1
                and 0 < self.daily_loss_limit < 1):
            raise ValueError(f"invalid limits {self}")


class KillSwitch:
    def __init__(self) -> None:
        self.tripped = False
        self.reason = ""

    def trip(self, reason: str) -> None:
        if not self.tripped:
            log.critical("kill switch tripped: %s", reason)
        self.tripped, self.reason = True, reason

    def rearm(self, operator: str) -> None:
        if not operator.strip():
            raise PermissionError("re-arming needs a named human operator")
        log.warning("kill switch re-armed by %s (was: %s)", operator, self.reason)
        self.tripped, self.reason = False, ""


@dataclass(frozen=True)
class RiskDecision:
    target: TargetPortfolio
    breaches: tuple[str, ...]
    halted: bool


class RiskEngine:
    def __init__(self, limits: RiskLimits, kill_switch: KillSwitch | None = None) -> None:
        self.limits = limits
        self.kill_switch = kill_switch or KillSwitch()
        self.high_water: float | None = None
        self._day: int | None = None
        self._day_open: float | None = None
        self.day_halted = False

    def update_equity(self, t: UtcNanos, equity: float) -> None:
        day = t // NS_PER_DAY
        if day != self._day:
            self._day, self._day_open, self.day_halted = day, equity, False
        self.high_water = equity if self.high_water is None else max(self.high_water, equity)
        if equity <= 0 or 1 - equity / self.high_water >= self.limits.max_drawdown:
            self.kill_switch.trip(f"drawdown budget {self.limits.max_drawdown:.0%} breached at t={t}")
        if self._day_open and 1 - equity / self._day_open >= self.limits.daily_loss_limit:
            self.day_halted = True

    def check(self, target: TargetPortfolio, current: Mapping[str, float]) -> RiskDecision:
        """Return the target the execution stage may trade toward. `current` is today's weights."""
        names = set(target.weights) | set(current)
        if self.kill_switch.tripped:
            return RiskDecision(TargetPortfolio(target.t, {k: 0.0 for k in names}), ("kill_switch",), True)
        breaches: list[str] = []
        w = {k: target.weights.get(k, 0.0) for k in names}
        if self.day_halted:
            breaches.append("daily_loss_halt")
            for k in names:
                c = current.get(k, 0.0)
                if w[k] * c < 0 or c == 0:
                    w[k] = 0.0  # no new or flipped positions
                elif abs(w[k]) > abs(c):
                    w[k] = c  # no adds
        cap = self.limits.max_weight
        for k in names:
            if abs(w[k]) > cap:
                breaches.append(f"max_weight:{k}")
                w[k] = cap if w[k] > 0 else -cap
        gross = sum(abs(v) for v in w.values())
        if gross > self.limits.max_gross:
            breaches.append("max_gross")
            w = {k: v * self.limits.max_gross / gross for k, v in w.items()}
        return RiskDecision(TargetPortfolio(target.t, w), tuple(breaches), self.day_halted)
