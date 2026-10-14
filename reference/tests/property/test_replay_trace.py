"""Trace/account mechanics hold for generated market paths, independent of strategy quality."""

import pytest
from backtest import runner
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.fakes import candles

pytestmark = pytest.mark.property


@settings(max_examples=12, deadline=None)
@given(st.lists(st.floats(min_value=50, max_value=200), min_size=35, max_size=40),
       st.sampled_from([0.0, 0.0001, 0.001]), st.sampled_from([0, 1, 20]))
def test_trace_costs_and_accounts_reconcile(prices, fee, slip):
    config = {"initial_capital_in_usd": 1000, "transaction_fee": fee,
              "portfolio": {"usd_per_trade": 300, "slippage_bps": slip}}
    events = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, "decide_entry", lambda *_: True)  # exercise fills, not a model-quality test
        result = runner.run_backtest(config, {"BTC/USDT": candles(prices, start_ms=1735689600000)},
                                     "1h", on_event=events.append)
    cash, qty, buys, sells = 1000.0, 0.0, 0, 0
    for event in events:
        assert event["cash_before"] == pytest.approx(cash)
        assert event["quantity_before"] == pytest.approx(qty, abs=1e-10)
        for fill in event["fills"]:
            sign = 1 if fill["side"] == "BUY" else -1
            buys += sign == 1
            sells += sign == -1
            assert fill["price"] == pytest.approx(event["mark_price"] * (1 + sign * slip / 10000))
            assert fill["fee"] == pytest.approx(fill["price"] * fill["qty"] * fee)
            cash -= sign * fill["price"] * fill["qty"] + fill["fee"]
            qty += sign * fill["qty"]
        assert event["cash_after"] == pytest.approx(cash)
        assert event["quantity_after"] == pytest.approx(qty, abs=1e-10)
        assert event["equity_after"] == pytest.approx(cash + qty * event["mark_price"])
        assert cash >= -1e-9 and qty >= -1e-10
    assert buys > 0 and sells > 0 and abs(qty) < 1e-10
    assert result["per_symbol"]["BTC/USDT"]["entries"] == buys
    assert result["per_symbol"]["BTC/USDT"]["sells"] == sells
