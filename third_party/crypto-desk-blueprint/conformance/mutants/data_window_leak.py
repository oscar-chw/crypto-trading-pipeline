"""Mutant: the source returns one bar past the requested end."""
from conformance.toy import *  # noqa: F401,F403
from conformance.toy import SyntheticBars
from pipeline.types import NS_PER_HOUR

KILLED_BY = "test_data.py::test_window_respected"


class _Leak(SyntheticBars):
    def bars(self, instrument_id, start, end):
        return super().bars(instrument_id, start, end + NS_PER_HOUR)


def make_data_source():
    return _Leak()
