"""Mutant: never marks reduce-only, so a shrink can flip into a new position."""
import dataclasses

from conformance.toy import *  # noqa: F401,F403
from conformance.toy import DeltaExecutor

KILLED_BY = "test_execution.py::test_reduce_only_flags"


class _Never(DeltaExecutor):
    def orders(self, target, account):
        return [dataclasses.replace(o, reduce_only=False) for o in super().orders(target, account)]


def make_executor():
    return _Never()
