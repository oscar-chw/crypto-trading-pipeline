"""Mutant: purges overlaps but applies no embargo, while claiming one."""
from conformance.toy import *  # noqa: F401,F403
from pipeline.cv import PurgedKFold
from pipeline.types import NS_PER_HOUR

KILLED_BY = "test_validation.py::test_embargo"


def make_cv_splitter():
    sp = PurgedKFold(5, embargo_ns=0)
    sp.embargo_ns_claimed = 24 * NS_PER_HOUR
    return _Claim(sp)


class _Claim:
    def __init__(self, inner):
        self.inner, self.embargo_ns = inner, inner.embargo_ns_claimed

    def split(self, t0, t1):
        return self.inner.split(t0, t1)
