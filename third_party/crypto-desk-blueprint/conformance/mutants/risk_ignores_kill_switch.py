"""Mutant: the risk gate keeps trading after the kill switch trips."""
from conformance.toy import *  # noqa: F401,F403
from pipeline.risk import RiskEngine

KILLED_BY = "test_risk.py::test_kill_switch_blocks_new_risk"


class _Deaf(RiskEngine):
    def check(self, target, current):
        tripped, self.kill_switch.tripped = self.kill_switch.tripped, False
        try:
            return super().check(target, current)
        finally:
            self.kill_switch.tripped = tripped


def make_risk_engine(limits):
    return _Deaf(limits)
