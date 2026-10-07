import json
import time

import pytest
from backtest.runner import BacktestBroker
from bot.data.types import Position
from bot.flow_control.daily_rollover import write_daily_pnl
from bot.flow_control.stop_loss_take_profit import evaluate_dynamic_sl_tp
from bot.record.recorder import log_trade_close
from bot.strategy import SIGNAL_KEYS, entry_signal_ok
from hypothesis import given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.property

flag_values = st.sampled_from([True, False, None])  # None: the key is absent from the config


def original_rule(statuses, flags):
    """The entry rule as written inline in the original trader, before it moved to bot/strategy.py."""
    dash = {k: statuses.get(k, True) for k in ("rsi", "bb", "macd", "volume", "price", "engulfing")}
    dash.update({k: statuses.get(k, False) for k in ("ob_imbalance", "ob_depth", "ob_pressure", "ob_large_orders")})
    mode = str(flags.get("entry_mode", "any_two")).lower()
    enabled_keys = [k for k in SIGNAL_KEYS if bool(flags.get(k, True))]
    true_count = sum(1 for k in enabled_keys if dash.get(k, False))
    if mode == "any_two":
        return true_count >= 2
    return all(dash.get(k, False) for k in enabled_keys)


@given(st.dictionaries(st.sampled_from(SIGNAL_KEYS), st.booleans()),
       st.fixed_dictionaries({k: flag_values for k in SIGNAL_KEYS}),
       st.sampled_from(["any_two", "all", "ALL", None]))
def test_extracted_entry_rule_equals_the_original_rule(statuses, flags, mode):
    flags = {k: v for k, v in flags.items() if v is not None}
    if mode is not None:
        flags["entry_mode"] = mode
    # Real statuses (bot/strategy.signal_statuses) hold every enabled candle signal and no disabled
    # one. The rules differ only off that domain: the original dict defaulted a missing candle
    # status to True ("fired"); the extracted rule treats it as not fired.
    statuses = {k: statuses.get(k, False) for k in SIGNAL_KEYS
                if (k.startswith("ob_") and k in statuses) or (not k.startswith("ob_") and flags.get(k, True))}
    assert entry_signal_ok(statuses, flags) == original_rule(statuses, flags)


LADDER = {"dynamic": True, "0_stop_loss": 0.02,
          "1_take_gain": 0.015, "1_stop_loss_by_cost": 0.0, "1_sell_portion": 0.3,
          "2_take_gain": 0.03, "2_stop_loss_by_cost": 0.015, "2_sell_portion": 0.3,
          "3_take_gain": 0.05, "3_stop_loss_by_cost": 0.03, "3_sell_portion": 0.4}


@given(st.lists(st.floats(min_value=50.0, max_value=200.0), min_size=1, max_size=40), st.sampled_from([0.0, 0.0001, 0.001]))
def test_the_ladder_never_lowers_the_tier_or_the_stop(path, fee):
    pos = Position(symbol="X", quantity=1.0, avg_price=100.0, entry_price=100.0)
    last_tier, last_stop = 0, None
    for price in path:
        a = evaluate_dynamic_sl_tp(pos, price, LADDER, fee_rate=fee)
        assert a["tier"] >= last_tier
        if a["tier"] > 0:
            # a tier is only ever reached at its target, net of fees on both sides
            target = LADDER[f"{a['tier']}_take_gain"] + 2 * fee
            assert price >= 100.0 * (1 + target) - 1e-6 or a["tier"] == last_tier
            if last_stop is not None:
                assert a["new_stop"] >= last_stop - 1e-9
        if a["action"] == "exit":
            break
        pos.highest_tier_reached = a["tier"]
        last_tier = a["tier"]
        last_stop = a["new_stop"] if a["tier"] > 0 else None


@given(st.lists(st.tuples(st.booleans(), st.floats(min_value=0.0, max_value=1.0)), max_size=30),
       st.floats(min_value=10.0, max_value=1000.0))
def test_broker_conserves_value_at_a_constant_price_without_costs(ops, price):
    b = BacktestBroker(fee_rate=0.0, starting_cash=10_000.0, slippage_bps=0.0)
    for is_buy, frac in ops:
        if is_buy:
            b.buy(price, b.cash_usd * frac / price, 0)
        else:
            b.sell(price, b.position_qty * frac, 0)
        assert b.cash_usd >= -1e-6
        assert b.cash_usd + b.position_qty * price == pytest.approx(10_000.0, rel=1e-9)


closes = st.lists(st.tuples(st.sampled_from(["BTC/USDT", "STO/USDT"]),
                            st.integers(min_value=1, max_value=10_000),
                            st.integers(min_value=1, max_value=10_000),
                            st.integers(min_value=1, max_value=100)), min_size=1, max_size=15)


class _Loader:
    class _Cfg:
        raw = {"portfolio": {}, "crypto_list": {"BTC/USDT": True, "STO/USDT": True}}
        portfolio, crypto_list = raw["portfolio"], raw["crypto_list"]

    def get(self):
        return self._Cfg()


@settings(max_examples=40, deadline=None)
@given(closes)
def test_daily_pnl_counts_every_recorded_close_exactly_once(tmp_path_factory, trades):
    d = tmp_path_factory.mktemp("rec")
    expected = 0
    for pair, entry, exit_, qty in trades:  # integer prices: the sum is exact in floating point
        log_trade_close(str(d), pair=pair, entry_price=entry, exit_price=exit_, quantity=qty, pnl_pct=None)
        expected += (exit_ - entry) * qty
    write_daily_pnl(str(d), str(d), _Loader(), {}, {})
    day = time.strftime("%Y%m%d", time.gmtime())
    got = json.loads((d / f"daily_pnl_{day}.json").read_text())["pnl"]["_total"]
    assert got == expected
