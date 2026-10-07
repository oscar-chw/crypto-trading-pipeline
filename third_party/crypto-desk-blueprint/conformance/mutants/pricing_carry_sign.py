"""Mutant: carry with the rate differential reversed."""
from conformance.toy import *  # noqa: F401,F403
from conformance.toy import CarryPricing

KILLED_BY = "test_pricing.py::test_fair_matches_carry"


class _Flip(CarryPricing):
    def fair_value(self, instrument_id, t, spot, expiry, r_quote, r_base):
        return super().fair_value(instrument_id, t, spot, expiry, r_base, r_quote)


def make_pricing():
    return _Flip()
