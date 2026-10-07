#!/usr/bin/env python3
"""
Cancel open orders on the live exchange (CTP_EXCHANGE, CTP_API_KEY, CTP_API_SECRET).

Usage:
  SYMBOL=BTC/USDT python -m bot.console.cancel_pending   # one symbol
  python -m bot.console.cancel_pending                   # every open order
"""

import os

from bot.api.exchange import CcxtBroker


def main() -> None:
    from bot.trader import _load_dotenv

    _load_dotenv()
    broker = CcxtBroker.from_env()
    ids = broker.cancel_open_orders(os.getenv("SYMBOL") or None)
    print(f"Canceled {len(ids)} order(s):", ", ".join(ids) or "(none)")


if __name__ == "__main__":
    main()
