"""Mutant: a clock that accepts steps backwards."""
from conformance.toy import *  # noqa: F401,F403
from pipeline.clock import SimClock

KILLED_BY = "test_infra.py::test_clock_monotonic"


class _BackClock(SimClock):
    def advance(self, ns):
        self._now += int(ns)
        return self._now


def make_clock(start):
    return _BackClock(start)
