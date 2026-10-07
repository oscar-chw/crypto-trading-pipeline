import os
from typing import Any, Dict, List, Optional

import requests


class HorusClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.base_url = base_url or os.getenv("HORUS_BASE_URL", "")
        self.api_key = api_key or os.getenv("HORUS_API_KEY", "")
        if not self.base_url:
            raise RuntimeError("HORUS_BASE_URL not set")

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def fetch_ticker_price(self, symbol: str) -> float:
        r = requests.get(f"{self.base_url}/market/ticker", params={"symbol": symbol}, headers=self._headers(), timeout=10)
        r.raise_for_status()
        data = r.json()
        return float(data.get("last") or data.get("price") or data.get("close") or 0.0)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> List[List[Any]]:
        r = requests.get(f"{self.base_url}/market/ohlcv", params={"symbol": symbol, "timeframe": timeframe, "limit": limit}, headers=self._headers(), timeout=15)
        r.raise_for_status()
        return r.json()

    def create_limit_order(self, symbol: str, side: str, price: float, amount: float) -> Dict[str, Any]:
        payload = {"symbol": symbol, "side": side, "type": "limit", "price": price, "amount": amount}
        r = requests.post(f"{self.base_url}/orders/place", json=payload, headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()

    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        r = requests.post(f"{self.base_url}/orders/cancel", json={"symbol": symbol, "order_id": order_id}, headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()

    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        r = requests.get(f"{self.base_url}/orders/open", params=params, headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()

    def fetch_balance(self) -> Dict[str, Any]:
        r = requests.get(f"{self.base_url}/account/balance", headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()

    # Referencing official docs: https://api-horus.com/docs#tag/Blockchain/operation/get_transaction_count
    def get_transaction_count(self, address: str, chain: str = "ethereum") -> Dict[str, Any]:
        """Get blockchain transaction count for an address."""
        params = {"address": address, "chain": chain}
        r = requests.get(f"{self.base_url}/blockchain/transaction_count", params=params, headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()


