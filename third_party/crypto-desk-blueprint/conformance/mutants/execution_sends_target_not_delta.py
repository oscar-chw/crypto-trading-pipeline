"""Mutant: orders the full target quantity, ignoring the current position."""
from conformance.toy import *  # noqa: F401,F403
from conformance.toy import DeltaExecutor
from pipeline.types import OrderIntent

KILLED_BY = "test_execution.py::test_orders_reach_target"


class _Full(DeltaExecutor):
    def orders(self, target, account):
        return [OrderIntent(k, target.t, w * account.equity / account.prices[k], False, f"{k}:{target.t}")
                for k, w in target.weights.items() if w]


def make_executor():
    return _Full()
