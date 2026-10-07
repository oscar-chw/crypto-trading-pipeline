"""Stage 01 DataSource over MarketDataProvider.fetch_ohlcv (bot/data/data_provider.py)."""
from typing import Any

from backtest.runner import _timeframe_ms
from pipeline.types import Bar, UtcNanos

NS_PER_MS = 1_000_000


class OhlcvDataSource:
    """Bars from anything with MarketDataProvider's fetch_ohlcv(symbol, timeframe, limit).

    instrument_id is the bot's ccxt symbol ("BTC/USDT"). ccxt rows are stamped by bar OPEN time, so
    close_time = open + timeframe, and a bar is known (available_at) only when it closes: the window
    filter start < close_time <= end therefore drops the still-forming candle ccxt returns last.
    fetch_ohlcv serves only the latest `limit` bars, so a window older than that comes back short.
    """

    def __init__(self, provider: Any, timeframe: str = "1h", limit: int = 1000) -> None:
        self.provider, self.timeframe, self.limit = provider, timeframe, limit
        self._tf_ns = _timeframe_ms(timeframe) * NS_PER_MS

    def bars(self, instrument_id: str, start: UtcNanos, end: UtcNanos) -> list[Bar]:
        rows: list[list[Any]] | None = self.provider.fetch_ohlcv(instrument_id, timeframe=self.timeframe,
                                                                    limit=self.limit)
        if rows is None:  # MarketDataProvider returns None when every source failed; never read as "no bars"
            raise RuntimeError(f"no OHLCV for {instrument_id}: every data source failed")
        out = []
        for ts, o, h, low, c, v in rows:
            open_ns = int(ts) * NS_PER_MS
            close_ns = open_ns + self._tf_ns
            if start < close_ns <= end:
                out.append(Bar(instrument_id, open_ns, close_ns, float(o), float(h), float(low), float(c),
                               float(v), close_ns))
        return out
