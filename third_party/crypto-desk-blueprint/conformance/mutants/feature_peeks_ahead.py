"""Mutant: momentum stamped one bar early (uses the next close)."""
from conformance.toy import *  # noqa: F401,F403
from conformance.toy import Momentum

KILLED_BY = "test_features.py::test_point_in_time"


class _Peek(Momentum):
    def compute(self, bars):
        return super().compute(bars).shift(-1)


def make_feature():
    return _Peek()
