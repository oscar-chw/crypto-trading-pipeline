#!/usr/bin/env python3
"""
Liquidation utility for the live exchange (CTP_EXCHANGE, CTP_API_KEY, CTP_API_SECRET).

Usage:
  SYMBOL=BTC/USDT python -m bot.console.liquidate   # cancel open orders for that symbol only
  python -m bot.console.liquidate                   # cancel every open order, then market-sell every coin into USDT
"""

import os

from bot.api.exchange import QUOTE, CcxtBroker


def _sell_all(broker: CcxtBroker) -> None:
    """Market SELL every non-USDT asset with a free balance; dust under 1 USDT of notional is skipped."""
    try:
        print("Canceled open orders:", broker.cancel_open_orders() or "(none)")
    except Exception as e:
        print("Warning: cancel all open orders failed:", e)
    free = broker.fetch_balance().get("free", {})
    for asset, qty in sorted(free.items()):
        if asset == QUOTE or qty <= 0:
            continue
        symbol = f"{asset}/{QUOTE}"
        try:
            price = float(broker.client.fetch_ticker(symbol).get("last") or 0.0)
        except Exception as e:
            print(f"Skip {symbol}: no price ({e})")
            continue
        if qty * price < 1.0:
            print(f"Skip {symbol} qty={qty} (notional ~ {qty * price:.6f} {QUOTE} < 1.0)")
            continue
        try:
            order = broker.place_market_order(symbol, "SELL", qty)
        except Exception as e:
            print(f"Failed to liquidate {symbol} qty={qty} ->", e)
            continue
        print(f"Liquidated {symbol} qty={qty}: {order.status} (order {order.id})")


def main() -> None:
    from bot.trader import _load_dotenv

    _load_dotenv()
    broker = CcxtBroker.from_env()
    symbol = os.getenv("SYMBOL")
    if symbol:
        print("Canceled:", broker.cancel_open_orders(symbol) or "(none)")
        return
    _sell_all(broker)


if __name__ == "__main__":
    main()
