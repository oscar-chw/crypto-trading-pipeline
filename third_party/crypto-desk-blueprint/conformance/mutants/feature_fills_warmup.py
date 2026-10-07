"""Mutant: warm-up NaNs filled with 0, so the model trades on an undefined value."""
from conformance.toy import *  # noqa: F401,F403
from conformance.toy import Momentum

KILLED_BY = "test_features.py::test_warmup_is_nan"


class _Filled(Momentum):
    def compute(self, bars):
        return super().compute(bars).fillna(0.0)


def make_feature():
    return _Filled()
