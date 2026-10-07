from typing import Any, Dict, List, Optional

from bot.api.ccxt.client import CCXTClient
from bot.api.horus.client import HorusClient


class MarketDataProvider:
    def __init__(self, exchange_id: str = "binance", preferred_source: str = "ccxt") -> None:
        self.ccxt = CCXTClient(exchange_id=exchange_id)
        # Horus optional: requires HORUS_* env
        try:
            self.horus = HorusClient()
        except Exception:
            self.horus = None
        self.preferred_source = (preferred_source or "ccxt").lower()

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> Optional[List[List[Any]]]:
        # Preferred → fallback
        sources = [self.preferred_source, "ccxt" if self.preferred_source != "ccxt" else "horus"]
        for src in sources:
            try:
                if src == "horus" and self.horus is not None:
                    return self.horus.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                if src == "ccxt":
                    return self.ccxt.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            except Exception:
                continue
        return None

    def fetch_ticker_price(self, symbol: str) -> Optional[float]:
        sources = [self.preferred_source, "ccxt" if self.preferred_source != "ccxt" else "horus"]
        for src in sources:
            try:
                if src == "horus" and self.horus is not None:
                    return float(self.horus.fetch_ticker_price(symbol))
                if src == "ccxt":
                    return float(self.ccxt.fetch_ticker_price(symbol))
            except Exception:
                continue
        return None

    def fetch_order_book(self, symbol: str, limit: int = 20) -> Optional[Dict[str, Any]]:
        """Fetch order book with fallback between sources."""
        sources = [self.preferred_source, "ccxt" if self.preferred_source != "ccxt" else "horus"]
        for src in sources:
            try:
                if src == "ccxt":
                    return self.ccxt.fetch_order_book(symbol, limit=limit)
                # Add horus support if available
            except Exception:
                continue
        return None


