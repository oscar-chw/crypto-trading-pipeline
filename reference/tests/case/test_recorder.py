import csv
import json

import pytest
from bot.record.recorder import log_order

pytestmark = pytest.mark.case


def test_an_order_lands_in_the_jsonl_and_the_csv_of_the_same_utc_day(tmp_path, monkeypatch):
    # 2025-11-06 23:30 UTC is already 2025-11-07 in Hong Kong: both copies must use the UTC day.
    monkeypatch.setenv("TZ", "Asia/Hong_Kong")
    import time
    time.tzset()
    try:
        monkeypatch.setattr(time, "time", lambda: 1762471800.0)
        log_order(str(tmp_path), pair="BTC/USDT", side="buy", price=100.0, quantity=0.5, order_id="7", signals={"macd": True})
    finally:
        monkeypatch.undo()
        time.tzset()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["transactions_20251106.csv", "transactions_20251106.jsonl"]
    event = json.loads((tmp_path / "transactions_20251106.jsonl").read_text(encoding="utf-8"))
    assert (event["action"], event["order_id"], event["signal_macd"]) == ("BUY", "7", True)
    with open(tmp_path / "transactions_20251106.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["action"] == "BUY" and rows[0]["datetime"] == "2025-11-06 23:30:00"
