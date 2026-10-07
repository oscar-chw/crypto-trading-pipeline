"""The backtester and the live loop make the same entry decision on the same candles.

Named failure: the original backtester imported its own older copies of the signal modules, so a
backtest said nothing about the code that traded.
"""
import pytest
from backtest.runner import decide_entry, window_indicators
from backtest.synthetic import make_candles
from tests.fakes import make_trader

pytestmark = pytest.mark.integration


def test_entry_decisions_agree_bar_by_bar(in_tmp):
    ohlcv = make_candles(420, seed=11)
    probe = make_trader(ohlcv)[0]
    flags = probe.cfg_loader.get().signal_portfolio
    checked, fired = 0, 0
    for idx in range(30, len(ohlcv), 3):
        bt = decide_entry(window_indicators(ohlcv, idx, flags), flags)
        t, broker = make_trader(ohlcv[: idx + 1])
        t.run_once()
        live = any(side == "BUY" for _, side, _ in broker.orders)
        assert live == bt, f"bar {idx}: live {live}, backtest {bt}"
        checked += 1
        fired += bt
    # both outcomes must occur, or agreement would be trivially true
    assert checked >= 100 and 0 < fired < checked
