"""Mutant: longs receive positive funding."""
from conformance.toy import *  # noqa: F401,F403
from conformance.toy import CarryPricing

KILLED_BY = "test_pricing.py::test_long_pays_positive_funding"


class _Flip(CarryPricing):
    def funding_cashflow(self, position_qty, mark_price, rate):
        return position_qty * mark_price * rate


def make_pricing():
    return _Flip()
