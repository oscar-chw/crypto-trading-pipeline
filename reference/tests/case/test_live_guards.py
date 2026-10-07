import pytest
from bot.api.exchange import require_live_env
from bot.data.types import Position
from bot.flow_control.on_end_liquidate import persist_rotation
from bot.flow_control.per_coin_drawdown import is_coin_drawdown_exceeded

pytestmark = pytest.mark.case


def test_live_trading_refuses_to_start_without_credentials(monkeypatch):
    monkeypatch.delenv("CTP_API_KEY", raising=False)
    monkeypatch.setenv("CTP_EXCHANGE", "binance")
    monkeypatch.setenv("CTP_API_SECRET", "x")
    with pytest.raises(SystemExit, match="CTP_API_KEY"):
        require_live_env()


def test_live_trading_starts_when_credentials_are_set(monkeypatch):
    for n in ("CTP_EXCHANGE", "CTP_API_KEY", "CTP_API_SECRET"):
        monkeypatch.setenv(n, "x")
    assert require_live_env() == ("x", "x", "x")


def test_per_coin_drawdown_uses_entry_price():
    pos = Position(symbol="BTC/USDT", quantity=1.0, avg_price=100.0, entry_price=120.0)
    assert is_coin_drawdown_exceeded(pos, current_price=90.0, max_usd_loss=25.0) is True
    assert is_coin_drawdown_exceeded(pos, current_price=110.0, max_usd_loss=25.0) is False


def test_max_hold_close_removes_the_symbol_from_the_pack(tmp_path):
    updated = persist_rotation(str(tmp_path / "alloc.json"), {"BTC/USDT": 10000.0, "STO/USDT": 10000.0},
                               "BTC/USDT", freed_usd=5000.0, dest_symbols=[], weights=None, cfg_loader=None)
    assert updated == {"BTC/USDT": 0.0, "STO/USDT": 10000.0}
