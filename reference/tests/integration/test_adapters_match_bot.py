"""The adapters (reference/adapters) decide exactly what the bot decides: data -> features -> strategy.

Named failure: an adapter that maps a feature to the wrong lag, or drops a signal, still passes the
blueprint's conformance suites (they test the contract, not the bot); only a bar-by-bar comparison with
the bot's own decision catches it.
"""
import pytest
from adapters.data import OhlcvDataSource
from adapters.features import IndicatorFeature
from adapters.impl import FLAGS, make_strategy
from adapters.strategy import FEATURES
from backtest.runner import LIVE_WINDOW, decide_entry, window_indicators
from backtest.synthetic import HOUR_MS, make_candles
from bot.data.signal.indicators import compute_indicators
from pipeline.types import bars_to_frame
from tests.fakes import FakeMarketData

pytestmark = pytest.mark.integration
NS = 1_000_000


def _frame(rows):
    """The window as the adapters see it: Bars from OhlcvDataSource, then the blueprint's frame."""
    end = (rows[-1][0] + HOUR_MS) * NS
    return bars_to_frame(OhlcvDataSource(FakeMarketData(rows), limit=len(rows)).bars("BTC/USDT", 0, end))


def test_entry_signal_matches_backtest_bar_by_bar():
    ohlcv = make_candles(420, seed=11)
    strat = make_strategy()
    checked = fired = 0
    for idx in range(30, len(ohlcv), 3):
        rows = ohlcv[max(0, idx + 1 - LIVE_WINDOW): idx + 1]
        frame = _frame(rows)
        feats = {}
        for name in FEATURES:
            key, _, lag = name.partition("_lag")
            feats[name] = float(IndicatorFeature(key, FLAGS, int(lag or 0)).compute(frame).iloc[-1])
        score = strat.signal("BTC/USDT", int(frame.index[-1]), feats).score
        bot = decide_entry(window_indicators(ohlcv, idx, FLAGS), FLAGS)
        assert score == (1.0 if bot else 0.0), f"bar {idx}: adapter {score}, bot {bot}"
        checked += 1
        fired += bot
    # both outcomes must occur, or agreement would be trivially true
    assert checked >= 100 and 0 < fired < checked


def test_every_feature_equals_compute_indicators():
    rows = make_candles(300, seed=3)
    frame = _frame(rows)
    ind = compute_indicators(rows, FLAGS)
    for key, series in ind.items():
        out = IndicatorFeature(key, FLAGS).compute(frame)
        assert out.index.equals(frame.index)
        assert out.to_numpy() == pytest.approx(series.to_numpy(), nan_ok=True, rel=0, abs=0), key
