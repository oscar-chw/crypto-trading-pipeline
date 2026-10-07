"""The data and execution adapters translate the bot's types without changing them."""
import pytest
from adapters.data import OhlcvDataSource
from adapters.impl import make_venue
from backtest.runner import BacktestBroker
from pipeline.types import OrderIntent
from tests.fakes import FakeMarketData, candles

pytestmark = pytest.mark.case
H_NS = 3_600_000_000_000
MS = 1_000_000


def test_bars_are_stamped_by_close_and_the_forming_candle_is_dropped():
    rows = candles([100.0, 101.0, 102.0], start_ms=0)
    src = OhlcvDataSource(FakeMarketData(rows))
    # "now" is inside the third candle: it has not closed, so it is not known yet
    bars = src.bars("X", 0, 2 * H_NS + 30 * 60_000 * MS)
    assert [b.close_time for b in bars] == [H_NS, 2 * H_NS]
    assert [b.close for b in bars] == [100.0, 101.0] and all(b.available_at == b.close_time for b in bars)


def test_a_failed_fetch_raises_instead_of_reading_as_no_bars():
    class Down:
        def fetch_ohlcv(self, symbol, timeframe="1h", limit=200):
            return None  # what MarketDataProvider returns when every source failed

    with pytest.raises(RuntimeError, match="every data source failed"):
        OhlcvDataSource(Down()).bars("X", 0, H_NS)


@pytest.mark.parametrize("qty", [2.0, -2.0])
def test_venue_fill_is_the_backtest_brokers_fill(qty):
    venue = make_venue()
    fill = venue.submit(OrderIntent("X", 1, qty, qty < 0, "id"), mid=100.0, bar_volume=1_000.0)
    ref = BacktestBroker(venue.fee_rate, starting_cash=1e9, slippage_bps=venue.slippage_bps)
    if qty > 0:
        ref.buy(100.0, qty, 1)
    else:
        ref.buy(100.0, -qty, 0)
        ref.sell(100.0, -qty, 1)
    trade = ref.trades[-1]
    assert (fill.qty, fill.price, fill.fee) == (qty, trade["price"], trade["fee"])
    assert venue.fee_rate > 0 and venue.slippage_bps > 0  # the bundled config prices both
