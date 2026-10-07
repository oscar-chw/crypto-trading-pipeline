import os
from typing import Any, Dict, List, Optional


class ExchangeAdapter:
    def __init__(self, exchange_id: str = "binance", api_key: Optional[str] = None, secret: Optional[str] = None) -> None:
        api_key = api_key or os.getenv("EXCHANGE_API_KEY")
        secret = secret or os.getenv("EXCHANGE_API_SECRET")
        import ccxt  # imported here so the offline backtest and tests do not need ccxt installed

        klass = getattr(ccxt, exchange_id)
        self.client = klass({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
        })

    def fetch_ticker_price(self, symbol: str) -> float:
        t = self.client.fetch_ticker(symbol)
        return float(t.get("last") or t.get("close") or 0.0)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> List[List[Any]]:
        return self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def create_limit_order(self, symbol: str, side: str, price: float, amount: float) -> Dict[str, Any]:
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        return self.client.create_order(symbol, type="limit", side=side, amount=amount, price=price)

    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        return self.client.cancel_order(order_id, symbol)

    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.client.fetch_open_orders(symbol)

    def fetch_balance(self) -> Dict[str, Any]:
        return self.client.fetch_balance()

    def fetch_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """Fetch order book (market depth) for a symbol.
        
        Returns:
            {
                'bids': [[price, amount], ...],  # sorted by price descending
                'asks': [[price, amount], ...],  # sorted by price ascending
                'timestamp': int,
            }
        """
        return self.client.fetch_order_book(symbol, limit=limit)


