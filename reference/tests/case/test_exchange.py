"""The execution interface: PaperBroker fills like the backtester, CcxtBroker maps ccxt orders. No network."""
import pytest
from backtest.runner import BacktestBroker
from bot.api.exchange import CcxtBroker, PaperBroker

pytestmark = pytest.mark.case

FEE, SLIP = 0.001, 10.0


class Prices:
    def __init__(self, price):
        self.price = price

    def __call__(self, symbol):
        return self.price


def test_paper_buy_and_sell_fill_at_the_next_price_with_the_backtest_costs():
    prices = Prices(100.0)
    paper = PaperBroker(prices, FEE, SLIP, cash=1_000.0)
    ref = BacktestBroker(FEE, starting_cash=1_000.0, slippage_bps=SLIP)
    buy = paper.place_market_order("BTC/USDT", "BUY", 2.0)
    ref.buy(100.0, 2.0, 0)
    assert (buy.status, buy.filled, buy.price, buy.fee) == ("FILLED", 2.0, ref.trades[-1]["price"], ref.trades[-1]["fee"])
    assert paper.fetch_balance()["free"] == {"USDT": ref.cash_usd, "BTC": 2.0}
    prices.price = 110.0  # the price moved after the decision: the sell fills at the new one
    sell = paper.place_market_order("BTC/USDT", "SELL", 2.0)
    ref.sell(110.0, 2.0, 0)
    assert (sell.status, sell.price, sell.fee) == ("FILLED", ref.trades[-1]["price"], ref.trades[-1]["fee"])
    assert paper.fetch_balance()["total"] == {"USDT": ref.cash_usd}
    assert paper.query_order(buy.id, "BTC/USDT") == buy


def test_paper_rejects_what_the_account_cannot_cover_and_changes_nothing():
    paper = PaperBroker(Prices(100.0), FEE, SLIP, cash=100.0, holdings={"ETH/USDT": (1.0, 90.0)})
    before = paper.fetch_balance()
    assert paper.place_market_order("BTC/USDT", "BUY", 1.0).status == "REJECTED"  # 100 * slip * fee > 100 cash
    assert paper.place_market_order("ETH/USDT", "SELL", 1.5).status == "REJECTED"  # holds only 1.0
    assert paper.fetch_balance() == before
    assert paper.place_market_order("ETH/USDT", "SELL", 1.0).status == "FILLED"


class FakeCcxt:
    """The slice of a ccxt exchange CcxtBroker calls; `reply` is what create_order and fetch_order return."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def load_markets(self):
        return {}

    def amount_to_precision(self, symbol, amount):
        return f"{amount:.3f}"

    def create_order(self, symbol, type, side, amount):
        self.calls.append((symbol, type, side, amount))
        return self.reply

    def fetch_order(self, order_id, symbol):
        return self.reply


@pytest.mark.parametrize("reply, status", [
    ({"id": "7", "status": "closed", "amount": 0.123, "filled": 0.123, "average": 100.0, "fee": {"cost": 0.01}}, "FILLED"),
    ({"id": "7", "status": "closed", "amount": 0.123, "filled": 0.1}, "OPEN"),  # closed short of the amount
    ({"id": "7", "status": "open", "amount": 0.123, "filled": 0.0}, "OPEN"),
    ({"id": "7", "status": "rejected"}, "REJECTED"),
])
def test_ccxt_market_order_is_rounded_and_only_a_full_fill_counts(reply, status):
    fake = FakeCcxt(reply)
    order = CcxtBroker("binance", "k", "s", client=fake).place_market_order("BTC/USDT", "BUY", 0.123456)
    assert fake.calls == [("BTC/USDT", "market", "buy", 0.123)]
    assert (order.id, order.status) == ("7", status)


def test_ccxt_broker_refuses_to_start_without_credentials(monkeypatch):
    monkeypatch.setenv("CTP_EXCHANGE", "binance")
    monkeypatch.setenv("CTP_API_KEY", "k")
    monkeypatch.delenv("CTP_API_SECRET", raising=False)
    with pytest.raises(SystemExit, match="CTP_API_SECRET"):
        CcxtBroker.from_env()
