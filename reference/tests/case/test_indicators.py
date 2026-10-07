"""RSI from compute_indicators.

Named failure (found by the blueprint's conformance AT-02-2): with no losing bar yet, the average loss is 0
and RSI came out NaN instead of 100, so a static-mode "RSI > 70" exit could not fire on a run of gains.
"""
import itertools
import math

import pytest
from bot.data.signal.indicators import compute_indicators
from tests.fakes import candles

pytestmark = pytest.mark.case
CFG = {"rsi_1": 14}


def test_rsi_is_100_while_there_has_been_no_loss():
    rsi = compute_indicators(candles([100.0 + i for i in range(30)]), CFG)["rsi"]
    assert math.isnan(rsi.iloc[0])  # no change yet: undefined
    assert (rsi.iloc[1:] == 100.0).all()


def test_rsi_is_0_while_there_has_been_no_gain():
    rsi = compute_indicators(candles([100.0 - i for i in range(30)]), CFG)["rsi"]
    assert (rsi.iloc[1:] == 0.0).all()


def test_rsi_is_undefined_on_flat_prices():
    rsi = compute_indicators(candles([100.0] * 30), CFG)["rsi"]
    assert rsi.isna().all()


def test_rsi_unchanged_once_both_gains_and_losses_exist():
    closes = [100, 101, 99, 102, 98, 103, 101, 104, 100, 105]
    rsi = compute_indicators(candles([float(c) for c in closes]), CFG)["rsi"]
    up = [max(b - a, 0.0) for a, b in itertools.pairwise(closes)]
    dn = [max(a - b, 0.0) for a, b in itertools.pairwise(closes)]
    au, ad = up[0], dn[0]
    for u, d in zip(up[1:], dn[1:], strict=False):  # Wilder smoothing, alpha 1/14, seeded at the first change
        au, ad = au + (u - au) / 14, ad + (d - ad) / 14
    assert rsi.iloc[-1] == pytest.approx(100 - 100 / (1 + au / ad), rel=1e-12)
