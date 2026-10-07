"""Mutant: the source repeats its last bar (a retried page appended twice)."""
from conformance.toy import *  # noqa: F401,F403
from conformance.toy import SyntheticBars

KILLED_BY = "test_data.py::test_ordered_unique"


class _Dup(SyntheticBars):
    def bars(self, instrument_id, start, end):
        out = super().bars(instrument_id, start, end)
        return out + out[-1:]


def make_data_source():
    return _Dup()
