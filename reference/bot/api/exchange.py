"""The execution interface the live loop trades through, and its two implementations.

- PaperBroker (the default): fills each market order at the next price its price source quotes, with the
  backtester's fee and slippage model (backtest.runner.BacktestBroker). No keys, no orders leave the machine.
- CcxtBroker: live market orders on any ccxt exchange. CcxtBroker.from_env refuses to start without
  CTP_EXCHANGE, CTP_API_KEY and CTP_API_SECRET.

Both speak symbols in ccxt form (BTC/USDT) and report an Order whose status is FILLED only once the whole
quantity has filled; the trader opens or closes a position on FILLED and nothing else.
"""
from __future__ import annotations

import itertools
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

QUOTE = "USDT"
LIVE_ENV_VARS = ("CTP_EXCHANGE", "CTP_API_KEY", "CTP_API_SECRET")


@dataclass(frozen=True)
class Order:
    """One market order as the venue last reported it. status: FILLED, OPEN, REJECTED or CANCELED."""

    id: str
    symbol: str
    side: str
    status: str
    filled: float = 0.0
    price: float = 0.0
    fee: float = 0.0


class Broker(Protocol):
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Order: ...

    def query_order(self, order_id: str, symbol: str) -> Order: ...

    def fetch_balance(self) -> dict[str, dict[str, float]]:
        """ccxt shape: {"free": {asset: qty}, "total": {asset: qty}}; cash is the QUOTE asset."""
        ...


def require_live_env() -> tuple[str, str, str]:
    """Exit with a clear message, before any network call, when a live credential is absent.

    Named failure: without this the loop started, every signed call failed inside a broad except,
    and the bot ran silently placing nothing.
    """
    missing = [name for name in LIVE_ENV_VARS if not os.getenv(name)]
    if missing:
        raise SystemExit(
            "live trading needs " + ", ".join(missing) + " in the environment (or a local .env). "
            "Paper trading needs none: python -m bot.trader"
        )
    exchange_id, key, secret = (os.environ[name] for name in LIVE_ENV_VARS)
    return exchange_id, key, secret


class PaperBroker:
    """Simulated spot account: one shared cash balance in QUOTE, one long position per symbol.

    Each symbol's position is a BacktestBroker, so a paper fill costs exactly what a backtest fill costs
    (price +/- slippage_bps, fee_rate per side). An order the account cannot cover in full is REJECTED rather
    than partly filled: the trader records the quantity it asked for, so a partial fill would overstate it.
    """

    def __init__(self, price_source: Callable[[str], float], fee_rate: float, slippage_bps: float,
                 cash: float, holdings: dict[str, tuple[float, float]] | None = None) -> None:
        from backtest.runner import BacktestBroker  # deferred: backtest.runner imports the bot's modules

        self._make = lambda: BacktestBroker(fee_rate, starting_cash=0.0, slippage_bps=slippage_bps)
        self.price_source = price_source
        self.cash = float(cash)
        self.books: dict[str, Any] = {}
        for symbol, (qty, avg_price) in (holdings or {}).items():
            book = self._book(symbol)
            book.position_qty, book.avg_price = float(qty), float(avg_price)
        self.orders: dict[str, Order] = {}
        self._ids = itertools.count(1)

    def _book(self, symbol: str) -> Any:
        if symbol not in self.books:
            self.books[symbol] = self._make()
        return self.books[symbol]

    def place_market_order(self, symbol: str, side: str, quantity: float) -> Order:
        side = side.upper()
        oid = str(next(self._ids))
        price = float(self.price_source(symbol) or 0.0)
        book = self._book(symbol)
        qty = float(quantity)
        status = "REJECTED"
        if price > 0 and qty > 0:
            if side == "BUY":
                # the very expression BacktestBroker.buy tests, so a covered order is never clipped there
                if price * (1.0 + book.slippage) * qty * (1.0 + book.fee_rate) <= self.cash:
                    book.cash_usd = self.cash
                    book.buy(price, qty, int(time.time() * 1000))
                    self.cash = book.cash_usd
                    status = "FILLED"
            elif side == "SELL" and qty <= book.position_qty + 1e-12:
                book.cash_usd = self.cash
                book.sell(price, qty, int(time.time() * 1000))
                self.cash = book.cash_usd
                status = "FILLED"
        if status == "FILLED":
            trade = book.trades[-1]
            order = Order(oid, symbol, side, status, trade["qty"], trade["price"], trade["fee"])
        else:
            order = Order(oid, symbol, side, status)
        self.orders[oid] = order
        return order

    def query_order(self, order_id: str, symbol: str) -> Order:
        return self.orders[order_id]

    def fetch_balance(self) -> dict[str, dict[str, float]]:
        assets = {QUOTE: self.cash}
        for symbol, book in self.books.items():
            if book.position_qty > 0:
                assets[symbol.split("/")[0]] = book.position_qty
        return {"free": dict(assets), "total": dict(assets)}


# ccxt's unified order statuses; "closed" means fully filled.
_CCXT_STATUS = {"closed": "FILLED", "open": "OPEN", "canceled": "CANCELED", "expired": "CANCELED",
                "rejected": "REJECTED"}


class CcxtBroker:
    """Live spot market orders through ccxt, quantity rounded to the market's precision."""

    def __init__(self, exchange_id: str, api_key: str, api_secret: str, client: Any = None) -> None:
        if client is None:
            import ccxt  # type: ignore[import-untyped]  # ccxt ships no stubs; imported here so paper trading, the backtest and the tests never need it

            client = getattr(ccxt, exchange_id)({"apiKey": api_key, "secret": api_secret, "enableRateLimit": True})
        self.client = client

    @classmethod
    def from_env(cls) -> CcxtBroker:
        return cls(*require_live_env())

    def _order(self, raw: dict[str, Any], symbol: str, side: str) -> Order:
        status = _CCXT_STATUS.get(str(raw.get("status") or "open"), "OPEN")
        amount, filled = float(raw.get("amount") or 0.0), float(raw.get("filled") or 0.0)
        if status == "FILLED" and amount and filled < amount:
            status = "OPEN"  # a "closed" order short of its amount is not a confirmed full fill
        fee = float((raw.get("fee") or {}).get("cost") or 0.0)
        return Order(str(raw.get("id") or ""), symbol, side, status, filled, float(raw.get("average") or 0.0), fee)

    def place_market_order(self, symbol: str, side: str, quantity: float) -> Order:
        self.client.load_markets()
        amount = float(self.client.amount_to_precision(symbol, quantity))
        raw = self.client.create_order(symbol, "market", side.lower(), amount)
        return self._order(raw, symbol, side.upper())

    def query_order(self, order_id: str, symbol: str) -> Order:
        raw = self.client.fetch_order(order_id, symbol)
        return self._order(raw, symbol, str(raw.get("side") or "").upper())

    def fetch_balance(self) -> dict[str, dict[str, float]]:
        bal = self.client.fetch_balance()
        return {k: {a: float(v or 0.0) for a, v in (bal.get(k) or {}).items()} for k in ("free", "total")}

    def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return self.client.fetch_open_orders(symbol)

    def cancel_open_orders(self, symbol: str | None = None) -> list[str]:
        """Cancel every open order (of one symbol, if given); returns the cancelled ids."""
        ids = []
        for o in self.fetch_open_orders(symbol):
            self.client.cancel_order(o["id"], o["symbol"])
            ids.append(str(o["id"]))
        return ids
