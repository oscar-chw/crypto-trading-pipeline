from typing import Any, Dict, List, Optional

from bot.core.exchange import ExchangeAdapter


class CCXTClient:
    def __init__(self, exchange_id: str = "binance", api_key: Optional[str] = None, secret: Optional[str] = None) -> None:
        self.adapter = ExchangeAdapter(exchange_id=exchange_id, api_key=api_key, secret=secret)

    def fetch_ticker_price(self, symbol: str) -> float:
        return self.adapter.fetch_ticker_price(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> List[List[Any]]:
        return self.adapter.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def create_limit_order(self, symbol: str, side: str, price: float, amount: float) -> Dict[str, Any]:
        return self.adapter.create_limit_order(symbol, side, price, amount)

    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        return self.adapter.cancel_order(symbol, order_id)

    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.adapter.fetch_open_orders(symbol)

    def fetch_balance(self) -> Dict[str, Any]:
        return self.adapter.fetch_balance()

    def fetch_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """Fetch order book (market depth) for a symbol."""
        return self.adapter.fetch_order_book(symbol, limit=limit)


