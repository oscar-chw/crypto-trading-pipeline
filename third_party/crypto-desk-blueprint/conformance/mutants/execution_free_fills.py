"""Mutant: fills at mid with no fee."""
from conformance.toy import *  # noqa: F401,F403
from pipeline.types import Fill

KILLED_BY = "test_execution.py::test_fills_pay_costs"


class _Free:
    def submit(self, order, mid, bar_volume):
        return Fill(order.client_id, order.instrument_id, order.t, order.qty, mid, 0.0)


def make_venue():
    return _Free()
