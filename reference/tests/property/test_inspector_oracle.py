"""Independent exact-decimal oracle on binary-rational accounting controls."""

import json
from decimal import Decimal

import pytest
from backtest import runner
from backtest.audit import write_audit
from hypothesis import example, given, settings
from hypothesis import strategies as st
from tests.fakes import candles
from tests.integration.test_audit_inspector import inspect_command

pytestmark = pytest.mark.property


@settings(max_examples=6, deadline=None)
@example(price=64, fee=0.125, bars=35)
@example(price=128, fee=0.0, bars=5)
@given(price=st.sampled_from([32, 64, 128]), fee=st.sampled_from([0.0, 0.125]), bars=st.sampled_from([5, 35]))
def test_inspector_agrees_with_exact_accounting_oracle(tmp_path_factory, price, fee, bars):
    cfg = {"crypto_list": {"BTC/USDT": True, "ETH/USDT": True}, "initial_capital_in_usd": 1024,
           "transaction_fee": fee, "portfolio": {"usd_per_trade": 128, "slippage_bps": 0}}
    data = {symbol: candles([price] * bars, start_ms=1735689600000) for symbol in cfg["crypto_list"]}
    root = tmp_path_factory.mktemp("inspector-oracle")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, "decide_entry", lambda *_: True)
        write_audit(str(root / "run"), cfg, data, "1h", 3600000,
                    lambda sink: runner.run_backtest(cfg, data, "1h", on_event=sink), [])
    result = inspect_command(root / "run", "--json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    events = [json.loads(line) for line in (root / "run/events.jsonl").read_text().splitlines()]
    for symbol, actual in report["symbols"].items():
        fills = [fill for e in events if e.get("symbol") == symbol for fill in e["fills"]]
        total_fees = sum((Decimal(str(f["price"])) * Decimal(str(f["qty"])) * Decimal(str(fee))
                          for f in fills), Decimal(0))
        assert Decimal(str(actual["cash_final"])) == Decimal(1024) - total_fees
        assert Decimal(str(actual["fees"])) == total_fees and actual["quantity_final"] == 0
        assert actual["bars"] == bars
        if bars == 5:
            assert fills == []
        else:
            assert actual["buys"] > 0 and actual["sells"] > 0
