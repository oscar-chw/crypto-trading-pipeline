"""The factories the blueprint's conformance suites call, for the stages the bot implements:
01 data, 02 features, 03 strategy, and the ExecutionVenue half of 07. scripts/conformance.sh runs only those.

Every factory is offline: market data comes from the bot's SYNTHETIC candle generator, never an exchange.
BOT_FEATURE picks which compute_indicators output the features suite checks (conformance.sh loops over all).
"""
import os

import yaml
from backtest.synthetic import HOUR_MS, START_MS, make_candles

from adapters.data import OhlcvDataSource
from adapters.execution import BrokerVenue
from adapters.features import IndicatorFeature
from adapters.strategy import FEATURES, EntryStrategy

CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot", "config", "config.yaml")
with open(CONFIG) as fh:
    CFG = yaml.safe_load(fh)
FLAGS = CFG.get("signal_portfolio", {}) or {}
PORTFOLIO = CFG.get("portfolio", {}) or {}

NS_PER_MS = 1_000_000
_T0 = START_MS * NS_PER_MS
DATA_SAMPLE = ("BTC/USDT", _T0 + 50 * HOUR_MS * NS_PER_MS, _T0 + 550 * HOUR_MS * NS_PER_MS)
STRATEGY_FEATURES = FEATURES


class SyntheticProvider:
    """MarketDataProvider's fetch_ohlcv over seeded SYNTHETIC candles: the latest `limit` rows, as ccxt serves."""

    def __init__(self, bars: int = 600, seed: int = 7) -> None:
        self.rows = make_candles(bars, seed)

    def fetch_ohlcv(self, symbol, timeframe="1h", limit=200):
        return self.rows[-limit:]


def make_data_source() -> OhlcvDataSource:
    return OhlcvDataSource(SyntheticProvider(), timeframe="1h", limit=1000)


def make_feature() -> IndicatorFeature:
    key, _, lag = os.environ.get("BOT_FEATURE", "rsi").partition("_lag")
    return IndicatorFeature(key, FLAGS, int(lag or 0))


def make_strategy() -> EntryStrategy:
    return EntryStrategy(FLAGS, horizon_ns=int(PORTFOLIO.get("maximum_holding_time", 259200)) * 10**9)


def make_venue() -> BrokerVenue:
    return BrokerVenue(float(CFG.get("transaction_fee", 0.0)), float(PORTFOLIO.get("slippage_bps", 1.0)))
