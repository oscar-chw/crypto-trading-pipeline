"""Mutant: no guard for missing inputs."""
import math

from conformance.toy import *  # noqa: F401,F403
from conformance.toy import PlaceholderStrategy
from pipeline.types import NS_PER_HOUR, Signal

KILLED_BY = "test_strategy.py::test_missing_features_mean_flat"


class _NoGuard(PlaceholderStrategy):
    def signal(self, instrument_id, t, features):
        return Signal(instrument_id, t, math.tanh(features["momentum"] / self.scale), 24 * NS_PER_HOUR,
                      self.model_id)


def make_strategy():
    return _NoGuard()
