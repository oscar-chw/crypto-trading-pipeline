"""SYNTHETIC hourly candles for the offline demo and tests. Not market data.

    python -m backtest.synthetic OUT_DIR [--bars 1500] [--seed 7] [--symbols BTC/USDT,STO/USDT]

A seeded random walk whose drift switches between up, flat and down regimes every 50-200 bars, so
both trend and pullback signals get a chance to fire. Python's `random` module only: the same seed
gives the same files on every machine and Python version.
"""
import argparse
import csv
import os
import random

START_MS = 1_735_689_600_000  # 2025-01-01T00:00:00Z
HOUR_MS = 3_600_000


def make_candles(bars: int, seed: int, start_price: float = 100.0) -> list[list[float]]:
    rng = random.Random(seed)
    rows, price, drift, regime_left = [], start_price, 0.0, 0
    for i in range(bars):
        if regime_left <= 0:
            drift = rng.choice((0.0015, 0.0, -0.0012))
            regime_left = rng.randint(50, 200)
        regime_left -= 1
        ret = drift + rng.gauss(0.0, 0.008)
        open_ = price
        close = max(0.01, price * (1.0 + ret))
        high = max(open_, close) * (1.0 + abs(rng.gauss(0.0, 0.003)))
        low = min(open_, close) * (1.0 - abs(rng.gauss(0.0, 0.003)))
        volume = 1000.0 * rng.lognormvariate(0.0, 0.5) * (1.0 + 20.0 * abs(ret))
        rows.append([START_MS + i * HOUR_MS, round(open_, 6), round(high, 6), round(low, 6), round(close, 6), round(volume, 3)])
        price = close
    return rows


def write_csv(path: str, rows: list[list[float]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ts", "open", "high", "low", "close", "volume"])
        w.writerows(rows)


def main() -> None:
    p = argparse.ArgumentParser(description="Write SYNTHETIC hourly candles, one CSV per symbol.")
    p.add_argument("out_dir")
    p.add_argument("--bars", type=int, default=1500)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--symbols", default="BTC/USDT,STO/USDT,PAXG/USDT,ICP/USDT")
    args = p.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    for n, sym in enumerate(args.symbols.split(",")):
        write_csv(os.path.join(args.out_dir, sym.replace("/", "_") + ".csv"), make_candles(args.bars, args.seed + n))
    print(f"SYNTHETIC: {args.bars} hourly bars x {len(args.symbols.split(','))} symbols -> {args.out_dir}")


if __name__ == "__main__":
    main()
