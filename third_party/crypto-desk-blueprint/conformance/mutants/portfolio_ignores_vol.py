"""Mutant: size from the score alone."""
from conformance.toy import *  # noqa: F401,F403
from conformance.toy import VolScaledPortfolio
from pipeline.types import TargetPortfolio

KILLED_BY = "test_portfolio.py::test_inverse_vol_scaling"


class _NoVol(VolScaledPortfolio):
    def target(self, t, signals, risk):
        return TargetPortfolio(t, {s.instrument_id: s.score * self.max_weight for s in signals})


def make_portfolio():
    return _NoVol()
