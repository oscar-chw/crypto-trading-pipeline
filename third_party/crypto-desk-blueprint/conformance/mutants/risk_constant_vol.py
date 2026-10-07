"""Mutant: a fixed volatility that never reacts."""
from conformance.toy import *  # noqa: F401,F403
from pipeline.types import RiskForecast

KILLED_BY = "test_risk.py::test_vol_responds_to_shock"


class _Const:
    def forecast(self, t, returns):
        return RiskForecast(t, {k: 0.01 for k in returns.columns}, 8760)


def make_risk_model():
    return _Const()
