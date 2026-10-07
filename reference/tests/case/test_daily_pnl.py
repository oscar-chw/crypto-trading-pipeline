import json
import time

import pytest
from bot.flow_control.daily_rollover import write_daily_pnl
from bot.record.recorder import log_trade_close

pytestmark = pytest.mark.case


class _Cfg:
    raw = {"portfolio": {"usd_per_trade": 10000, "cash_in_hand_usd": 10000, "target_active_coins": 4},
           "crypto_list": {"BTC/USDT": True, "STO/USDT": True}}
    portfolio = raw["portfolio"]
    crypto_list = raw["crypto_list"]


class _Loader:
    def get(self):
        return _Cfg()


def _pnl(record_dir):
    write_daily_pnl(str(record_dir), str(record_dir), _Loader(), {"BTC/USDT": 10000.0, "STO/USDT": 8000.0}, {})
    day = time.strftime("%Y%m%d", time.gmtime())
    return json.loads((record_dir / f"daily_pnl_{day}.json").read_text(encoding="utf-8"))


def test_each_recorded_close_is_counted_once(tmp_path):
    # The recorder writes each close to BOTH the JSONL and the CSV; the original reader summed both.
    log_trade_close(str(tmp_path), pair="BTC/USDT", entry_price=100.0, exit_price=110.0, quantity=1.0, pnl_pct=10.0)
    log_trade_close(str(tmp_path), pair="STO/USDT", entry_price=50.0, exit_price=45.0, quantity=2.0, pnl_pct=-10.0)
    assert len(list(tmp_path.glob("transactions_*.jsonl"))) == 1 and len(list(tmp_path.glob("transactions_*.csv"))) == 1
    data = _pnl(tmp_path)
    assert data["pnl"]["BTC/USDT"] == 10.0
    assert data["pnl"]["STO/USDT"] == -10.0
    assert data["pnl"]["_total"] == 0.0


def test_a_csv_only_day_is_still_read(tmp_path):
    day = time.strftime("%Y%m%d", time.gmtime())
    (tmp_path / f"transactions_{day}.csv").write_text(
        "type,pair,entry_price,price,quantity\ntrade_close,BTC/USDT,100,110,1\n", encoding="utf-8")
    data = _pnl(tmp_path)
    assert data["pnl"]["BTC/USDT"] == 10.0
    assert data["per_coin"]["BTC/USDT"]["alloc_usd"] == 10000.0
    assert "spare_usd" in data["status"]
