"""Mutant: a store view that ignores as_of (returns the future)."""
from conformance.toy import *  # noqa: F401,F403
from pipeline.store import PointInTimeStore, PointInTimeView

KILLED_BY = "test_infra.py::test_store_refuses_read_after_as_of"


class _OpenView(PointInTimeView):
    def read(self, key, start, end):
        return [r for r in self._rows.get(key, []) if start < r.event_time <= end]


class _OpenStore(PointInTimeStore):
    def view(self, as_of):
        return _OpenView(self._rows, as_of)


def make_store():
    return _OpenStore()
