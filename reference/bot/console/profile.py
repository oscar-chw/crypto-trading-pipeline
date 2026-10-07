#!/usr/bin/env python3
"""
Show the live account: equity, free USDT, non-zero assets and open orders.

Usage:
  python -m bot.console.profile
"""

from bot.api.exchange import QUOTE, CcxtBroker


def main() -> None:
    from bot.trader import _load_dotenv

    _load_dotenv()
    broker = CcxtBroker.from_env()
    bal = broker.fetch_balance()
    total = bal.get("total", {})
    equity = float(total.get(QUOTE, 0.0))
    held = sorted(((a, q) for a, q in total.items() if a != QUOTE and q > 0), key=lambda x: (-x[1], x[0]))
    for asset, qty in held:
        try:
            equity += qty * float(broker.client.fetch_ticker(f"{asset}/{QUOTE}").get("last") or 0.0)
        except Exception:
            pass  # an asset with no USDT market is left out of equity, not guessed
    print(f"Equity: {equity:.2f} {QUOTE}")
    print(f"{QUOTE} free: {float(bal.get('free', {}).get(QUOTE, 0.0)):.2f}")
    print("Non-zero assets:" if held else "Non-zero assets: (none)")
    for asset, qty in held:
        print(f"  {asset}: {qty}")
    try:
        print(f"Open orders: {len(broker.fetch_open_orders())}")
    except Exception as e:
        print(f"Open orders: N/A ({e})")


if __name__ == "__main__":
    main()
