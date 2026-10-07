"""Mutant: the vol forecast reads the whole frame, ignoring t."""
from conformance.toy import *  # noqa: F401,F403
from conformance.toy import EwmaVol

KILLED_BY = "test_risk.py::test_forecast_is_point_in_time"


class _Future(EwmaVol):
    def forecast(self, t, returns):
        return super().forecast(int(returns.index[-1]), returns)


def make_risk_model():
    return _Future()
