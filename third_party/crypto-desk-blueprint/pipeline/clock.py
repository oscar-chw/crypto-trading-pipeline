"""Clocks. Every component asks a Clock for the time; nothing calls time.time() directly, so a backtest,
a paper run and a live run execute the same code and differ only in which clock they are given."""
from __future__ import annotations

import time
from typing import Protocol

from pipeline.types import UtcNanos


class Clock(Protocol):
    def now(self) -> UtcNanos: ...


class SimClock:
    """A clock the backtest drives. It only moves forward: a step back would let a later decision see
    state written for an earlier time, which is look-ahead by another route."""

    def __init__(self, start: UtcNanos) -> None:
        self._now = int(start)

    def now(self) -> UtcNanos:
        return self._now

    def advance(self, ns: int) -> UtcNanos:
        if ns < 0:
            raise ValueError("a clock cannot move backwards")
        self._now += int(ns)
        return self._now

    def set(self, t: UtcNanos) -> UtcNanos:
        if t < self._now:
            raise ValueError(f"a clock cannot move backwards ({t} < {self._now})")
        self._now = int(t)
        return self._now


class WallClock:
    def now(self) -> UtcNanos:
        return time.time_ns()
