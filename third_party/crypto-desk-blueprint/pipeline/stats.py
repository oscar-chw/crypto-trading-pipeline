"""Sharpe ratio, probabilistic Sharpe and deflated Sharpe (Bailey and Lopez de Prado 2012, 2014).

All Sharpe inputs here are per period (not annualised): `sr` from n_obs returns of the same frequency,
and `var_trials` is the variance of the per-period Sharpe ratios of every trial run in the search.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def sharpe_ratio(returns: np.ndarray, periods_per_year: float | None = None) -> float:
    r = np.asarray(returns, dtype=float)
    if len(r) < 2 or r.std(ddof=1) == 0:
        raise ValueError("need at least two returns with non-zero dispersion")
    sr = r.mean() / r.std(ddof=1)
    return sr * math.sqrt(periods_per_year) if periods_per_year else sr


def probabilistic_sharpe_ratio(sr: float, sr_benchmark: float, n_obs: int, skew: float = 0.0,
                               kurtosis: float = 3.0) -> float:
    """P(true Sharpe > benchmark) given an estimate from n_obs returns with this skew and kurtosis."""
    denom = 1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr * sr
    if n_obs < 2 or denom <= 0:
        raise ValueError("need n_obs >= 2 and a positive variance term")
    return _N.cdf((sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denom))


def expected_max_sharpe(n_trials: int, var_trials: float) -> float:
    """Expected best per-period Sharpe among n_trials skill-less trials whose Sharpes have var_trials."""
    if n_trials < 1 or var_trials < 0:
        raise ValueError("need n_trials >= 1 and var_trials >= 0")
    if n_trials == 1:
        return 0.0
    return math.sqrt(var_trials) * ((1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials)
                                    + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * math.e)))


def deflated_sharpe_ratio(sr: float, n_obs: int, n_trials: int, var_trials: float, skew: float = 0.0,
                          kurtosis: float = 3.0) -> float:
    """PSR against the Sharpe the best of n_trials would reach by luck. Count every trial you ran."""
    return probabilistic_sharpe_ratio(sr, expected_max_sharpe(n_trials, var_trials), n_obs, skew, kurtosis)
