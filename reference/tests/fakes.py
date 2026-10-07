"""Offline stand-ins for the market-data source and the broker."""
import os
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(REPO, "bot", "config", "config.yaml")


def candles(closes, step_ms=3_600_000, start_ms=None):
    start = start_ms if start_ms is not None else int(time.time() * 1000) - len(closes) * step_ms
    return [[start + i * step_ms, c, c * 1.001, c * 0.999, c, 100.0 + i] for i, c in enumerate(closes)]


class FakeMarketData:
    """Serves a fixed candle list; the live loop asks for the last `limit` candles."""

    def __init__(self, ohlcv):
        self.ohlcv = ohlcv

    def fetch_ohlcv(self, symbol, timeframe="1h", limit=200):
        return self.ohlcv[-limit:]

    def fetch_order_book(self, symbol, limit=20):
        return None

    def fetch_ticker_price(self, symbol):
        return float(self.ohlcv[-1][4])


class FakeBroker:
    """Records every order; `fill` decides whether orders report FILLED or stay OPEN. Holds 50,000 USDT."""

    def __init__(self, fill=True):
        self.fill = fill
        self.orders = []

    def _order(self, oid, symbol, side):
        from bot.api.exchange import Order

        return Order(oid, symbol, side, "FILLED" if self.fill else "OPEN")

    def fetch_balance(self):
        return {"total": {"USDT": 50000.0}, "free": {"USDT": 50000.0}}

    def place_market_order(self, symbol, side, quantity):
        self.orders.append((symbol, side, float(quantity)))
        return self._order(str(len(self.orders)), symbol, side)

    def query_order(self, order_id, symbol):
        return self._order(order_id, symbol, "")


def make_trader(ohlcv, symbol="BTC/USDT", fill=True, signal_overrides=None, broker=None):
    """A Trader on the bundled config, one symbol, fakes injected (or `broker`), execution filters off.

    Call inside a temporary working directory: the trader writes record/ and log/ there.
    """
    from bot.trader import Trader

    broker = broker if broker is not None else FakeBroker(fill=fill)
    t = Trader(CONFIG, broker=broker, market_data=FakeMarketData(ohlcv))
    raw = t.cfg_loader._config.raw
    raw["crypto_list"] = {symbol: True}
    raw["execution_filter"] = {"enabled": False, "momentum_enabled": False, "iceberg_enabled": False}
    sp = dict(raw["signal_portfolio"])
    sp.update({"use_htf": False, "use_micro_signals": False, "ob_imbalance": False, "ob_depth": False,
               "ob_pressure": False, "ob_large_orders": False})
    sp.update(signal_overrides or {})
    raw["signal_portfolio"] = sp
    raw.setdefault("runtime", {})["slow_stop"] = False
    t._alloc = {}
    return t, broker
