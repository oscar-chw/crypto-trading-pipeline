#!/usr/bin/env python3
"""
Show open orders on the live exchange, with an optional SYMBOL filter.

Usage:
  python -m bot.console.pending
  SYMBOL=BTC/USDT python -m bot.console.pending
"""

import json
import os

from bot.api.exchange import CcxtBroker


def main() -> None:
    from bot.trader import _load_dotenv

    _load_dotenv()
    orders = CcxtBroker.from_env().fetch_open_orders(os.getenv("SYMBOL") or None)
    print(json.dumps(orders, indent=2, default=str))


if __name__ == "__main__":
    main()
