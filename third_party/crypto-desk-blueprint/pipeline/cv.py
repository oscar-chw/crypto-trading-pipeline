"""Purged, embargoed k-fold cross-validation for labels that span time (Lopez de Prado 2018, ch. 7).

Each sample i has a label interval [t0[i], t1[i]]. A training sample is dropped (purged) when its interval
overlaps the test block's span, and also when it starts within `embargo_ns` after the test block ends,
because features built on overlapping windows leak the test labels into training.
"""
from __future__ import annotations

from typing import Iterator

import numpy as np


class PurgedKFold:
    def __init__(self, n_splits: int = 5, embargo_ns: int = 0) -> None:
        if n_splits < 2 or embargo_ns < 0:
            raise ValueError("need n_splits >= 2 and embargo_ns >= 0")
        self.n_splits = n_splits
        self.embargo_ns = int(embargo_ns)

    def split(self, t0: np.ndarray, t1: np.ndarray) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        t0, t1 = np.asarray(t0, dtype=np.int64), np.asarray(t1, dtype=np.int64)
        if t0.shape != t1.shape or len(t0) < self.n_splits:
            raise ValueError("t0 and t1 must have equal length >= n_splits")
        if np.any(np.diff(t0) < 0) or np.any(t1 < t0):
            raise ValueError("t0 must be sorted and every t1 >= t0")
        for test in np.array_split(np.arange(len(t0)), self.n_splits):
            start, end = t0[test[0]], t1[test].max()
            keep = np.ones(len(t0), dtype=bool)
            keep[test] = False
            keep &= ~((t0 <= end) & (t1 >= start))  # purge: label overlaps the test span
            keep &= ~((t0 > end) & (t0 <= end + self.embargo_ns))  # embargo after the test block
            yield np.flatnonzero(keep), test
