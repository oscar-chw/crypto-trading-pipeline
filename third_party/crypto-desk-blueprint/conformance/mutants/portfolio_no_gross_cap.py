"""Mutant: advertises a gross cap but never applies it."""
import math

from conformance.toy import *  # noqa: F401,F403
from conformance.toy import VolScaledPortfolio
from pipeline.types import TargetPortfolio

KILLED_BY = "test_portfolio.py::test_gross_cap"


class _NoCap(VolScaledPortfolio):
    def target(self, t, signals, risk):
        per_period = self.target_vol_annual / math.sqrt(risk.periods_per_year)
        return TargetPortfolio(t, {s.instrument_id: max(-self.max_weight, min(
            self.max_weight, s.score * per_period / risk.vol[s.instrument_id])) for s in signals})


def make_portfolio():
    return _NoCap()
