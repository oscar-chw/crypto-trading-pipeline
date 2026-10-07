"""Mutant: plain contiguous k-fold, no purge and no embargo."""
import numpy as np

from conformance.toy import *  # noqa: F401,F403

KILLED_BY = "test_validation.py::test_no_train_test_overlap"


class _Plain:
    embargo_ns = 1

    def split(self, t0, t1):
        idx = np.arange(len(t0))
        for test in np.array_split(idx, 5):
            yield np.setdiff1d(idx, test), test


def make_cv_splitter():
    return _Plain()
