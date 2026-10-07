"""Mutant: deflated Sharpe that forgets how many trials were run."""
from conformance.toy import *  # noqa: F401,F403
from pipeline.stats import probabilistic_sharpe_ratio

KILLED_BY = "test_validation.py::test_dsr_penalises_trials"


def deflated_sharpe(sr, n_obs, n_trials, var_trials, skew=0.0, kurtosis=3.0):
    return probabilistic_sharpe_ratio(sr, 0.0, n_obs, skew, kurtosis)
