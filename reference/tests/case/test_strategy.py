import pytest
from bot.data.signal.indicators import compute_indicators
from bot.strategy import entry_signal_ok, signal_statuses
from tests.fakes import candles

pytestmark = pytest.mark.case

ALL_OFF = {k: False for k in ("macd", "rsi", "bb", "volume", "price", "engulfing",
                               "ob_imbalance", "ob_depth", "ob_pressure", "ob_large_orders")}


def test_any_two_needs_two_enabled_signals():
    flags = dict(ALL_OFF, macd=True, rsi=True, engulfing=True, entry_mode="any_two")
    assert entry_signal_ok({"macd": True, "rsi": True, "engulfing": False}, flags) is True
    assert entry_signal_ok({"macd": True, "rsi": False, "engulfing": False}, flags) is False


def test_a_disabled_signal_never_counts():
    flags = dict(ALL_OFF, macd=True, entry_mode="any_two")
    # rsi fired but is switched off: one enabled signal fired, not two
    assert entry_signal_ok({"macd": True, "rsi": True}, flags) is False


def test_all_mode_needs_every_enabled_signal():
    flags = dict(ALL_OFF, macd=True, rsi=True, entry_mode="all")
    assert entry_signal_ok({"macd": True, "rsi": True}, flags) is True
    assert entry_signal_ok({"macd": True, "rsi": False}, flags) is False


def test_an_unlisted_orderbook_signal_blocks_all_mode():
    # Kept from the original loop: a signal key absent from the config counts as enabled, and an
    # order-book signal with no status counts as not fired, so "all" needs every ob_* key listed.
    flags = {k: v for k, v in ALL_OFF.items() if k != "ob_depth"}
    flags.update(macd=True, rsi=True, entry_mode="all")
    assert entry_signal_ok({"macd": True, "rsi": True}, flags) is False


def test_orderbook_signal_without_a_book_reports_not_fired():
    ind = compute_indicators(candles([100.0] * 60), {})
    st = signal_statuses(ind, dict(ALL_OFF, ob_imbalance=True), orderbook=None, ob_config={"x": 1})
    assert st == {"ob_imbalance": False}


def test_orderbook_imbalance_reads_the_book():
    ind = compute_indicators(candles([100.0] * 60), {})
    book = {"bids": [[99.0, 5.0]], "asks": [[101.0, 1.0]]}
    st = signal_statuses(ind, dict(ALL_OFF, ob_imbalance=True), orderbook=book, ob_config={"orderbook_imbalance_threshold": 1.0})
    assert st["ob_imbalance"] is True
    book = {"bids": [[99.0, 1.0]], "asks": [[101.0, 5.0]]}
    st = signal_statuses(ind, dict(ALL_OFF, ob_imbalance=True), orderbook=book, ob_config={"orderbook_imbalance_threshold": 1.0})
    assert st["ob_imbalance"] is False


def test_rsi_window_is_50_to_70():
    import pandas as pd
    from bot.trading_logic.signal.RSI.isConfirmed import check

    assert check({"rsi": pd.Series([60.0] * 20)}) is True
    assert check({"rsi": pd.Series([75.0] * 20)}) is False
    assert check({"rsi": pd.Series([45.0] * 20)}) is False


def test_bullish_engulfing():
    import pandas as pd
    from bot.trading_logic.signal.ENGULFING.isBullish import check

    ind = {"open": pd.Series([101.0, 98.0]), "close": pd.Series([99.0, 102.0])}
    assert check(ind) is True
    ind = {"open": pd.Series([101.0, 99.5]), "close": pd.Series([99.0, 100.5])}  # does not engulf
    assert check(ind) is False
