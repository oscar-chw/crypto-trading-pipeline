"""The live loop (Trader.run_once) end to end, with the exchange and market data replaced by fakes."""
import pytest
from bot.api.exchange import PaperBroker
from bot.data.types import Position
from tests.fakes import FakeMarketData, candles, make_trader

pytestmark = pytest.mark.integration

SYMBOL = "ICP/USDT"


def test_entry_is_a_market_buy_and_opens_a_position_only_when_filled(in_tmp):
    flat = candles([100.0] * 200)
    # every candle signal off and "all" mode: the entry rule passes, so the order path is what is tested
    off = {k: False for k in ("macd", "rsi", "bb", "volume", "price", "engulfing")}
    t, broker = make_trader(flat, SYMBOL, fill=True, signal_overrides=dict(off, entry_mode="all"))
    t.run_once()
    assert [o[:2] for o in broker.orders] == [("ICP/USDT", "BUY")]
    assert SYMBOL in t.positions and t.positions[SYMBOL].quantity == pytest.approx(10000 * (1 - 2 * 0.0001) / 100.0)
    assert (in_tmp / "record").is_dir() and list((in_tmp / "record").glob("transactions_*.jsonl"))

    t2, broker2 = make_trader(flat, SYMBOL, fill=False, signal_overrides=dict(off, entry_mode="all"))
    t2.run_once()
    assert broker2.orders and SYMBOL not in t2.positions


def test_no_entry_when_the_rule_fails(in_tmp):
    t, broker = make_trader(candles([100.0] * 200), SYMBOL)  # flat prices: MACD/RSI/engulfing do not fire
    t.run_once()
    assert broker.orders == [] and t.positions == {}


def test_hard_stop_sells_everything_and_closes(in_tmp):
    t, broker = make_trader(candles([98.0] * 200), SYMBOL)
    t.positions[SYMBOL] = Position(symbol=SYMBOL, quantity=1.0, avg_price=100.0, entry_price=100.0, stop_price=99.0)
    t.run_once()
    assert broker.orders == [("ICP/USDT", "SELL", 1.0)]
    assert SYMBOL not in t.positions


def test_unfilled_stop_keeps_the_position(in_tmp):
    t, broker = make_trader(candles([98.0] * 200), SYMBOL, fill=False)
    t.positions[SYMBOL] = Position(symbol=SYMBOL, quantity=2.0, avg_price=100.0, entry_price=100.0, stop_price=99.0)
    t.run_once()
    assert broker.orders and t.positions[SYMBOL].quantity == 2.0


def test_first_take_profit_sells_30_percent_of_the_original_size(in_tmp):
    t, broker = make_trader(candles([103.0] * 200), SYMBOL)
    t.positions[SYMBOL] = Position(symbol=SYMBOL, quantity=1.0, avg_price=100.0, entry_price=100.0, original_quantity=1.0)
    t.run_once()
    side, qty = broker.orders[0][1:]
    assert side == "SELL" and qty == pytest.approx(0.3)
    assert t.positions[SYMBOL].quantity == pytest.approx(0.7)


def test_tripped_drawdown_guard_still_sells_at_the_stop(in_tmp):
    # A tripped guard must block new entries only; an open position at its stop must still be sold.
    t, broker = make_trader(candles([98.0] * 200), SYMBOL)
    t.initial_equity = 1e9  # equity (50000) is far below it: drawdown far past the limit
    t._dd_breach_count = 10  # already tripped, so this cycle is guarded
    t.positions[SYMBOL] = Position(symbol=SYMBOL, quantity=1.0, avg_price=100.0, entry_price=100.0, stop_price=99.0)
    t.run_once()
    assert broker.orders == [("ICP/USDT", "SELL", 1.0)]
    assert SYMBOL not in t.positions


def test_tripped_drawdown_guard_blocks_new_entries(in_tmp):
    # The same setup as the entry test, which buys; with the guard tripped, no buy may be sent.
    off = {k: False for k in ("macd", "rsi", "bb", "volume", "price", "engulfing")}
    t, broker = make_trader(candles([100.0] * 200), SYMBOL, fill=True, signal_overrides=dict(off, entry_mode="all"))
    t.initial_equity = 1e9
    t._dd_breach_count = 10
    t.run_once()
    assert not [o for o in broker.orders if o[1] == "BUY"]
    assert SYMBOL not in t.positions


def test_paper_broker_entry_moves_paper_cash_into_the_coin(in_tmp):
    flat = candles([100.0] * 200)
    off = {k: False for k in ("macd", "rsi", "bb", "volume", "price", "engulfing")}
    paper = PaperBroker(FakeMarketData(flat).fetch_ticker_price, fee_rate=0.0001, slippage_bps=1.0, cash=50_000.0)
    t, _ = make_trader(flat, SYMBOL, signal_overrides=dict(off, entry_mode="all"), broker=paper)
    t.run_once()
    qty = t.positions[SYMBOL].quantity
    assert qty == pytest.approx(10000 * (1 - 2 * 0.0001) / 100.0)
    bal = paper.fetch_balance()["free"]
    assert bal["ICP"] == qty
    assert bal["USDT"] == pytest.approx(50_000.0 - qty * 100.0 * (1 + 1e-4) * (1 + 0.0001))
