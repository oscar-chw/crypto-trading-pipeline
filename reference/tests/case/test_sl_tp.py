import pytest
from bot.data.types import Position
from bot.flow_control.stop_loss_take_profit import evaluate_dynamic_sl_tp

pytestmark = pytest.mark.case

LADDER = {
    "dynamic": True, "0_stop_loss": 0.02,
    "1_take_gain": 0.015, "1_stop_loss_by_cost": 0.0, "1_sell_portion": 0.3,
    "2_take_gain": 0.03, "2_stop_loss_by_cost": 0.015, "2_sell_portion": 0.3,
    "3_take_gain": 0.05, "3_stop_loss_by_cost": 0.03, "3_sell_portion": 0.4,
}


def pos(tier=0):
    p = Position(symbol="BTC/USDT", quantity=1.0, avg_price=100.0, entry_price=100.0)
    p.highest_tier_reached = tier
    return p


def test_below_first_target_holds_with_the_initial_stop():
    a = evaluate_dynamic_sl_tp(pos(), 101.0, LADDER)
    assert a["action"] == "hold" and a["tier"] == 0
    assert a["new_stop"] == pytest.approx(98.0)


def test_first_target_sells_30_percent_and_moves_stop_to_cost():
    a = evaluate_dynamic_sl_tp(pos(), 101.5, LADDER)
    assert (a["action"], a["sell_fraction"], a["tier"]) == ("partial_take", 0.3, 1)
    assert a["new_stop"] == pytest.approx(100.0)


def test_second_target_raises_stop_to_plus_1_5_percent():
    a = evaluate_dynamic_sl_tp(pos(tier=1), 103.0, LADDER)
    assert (a["action"], a["tier"]) == ("partial_take", 2)
    assert a["new_stop"] == pytest.approx(101.5)


def test_third_target_exits_everything():
    a = evaluate_dynamic_sl_tp(pos(tier=2), 105.0, LADDER)
    assert (a["action"], a["sell_fraction"], a["tier"]) == ("exit", 1.0, 3)


def test_a_reached_tier_keeps_its_stop_after_the_price_falls_back():
    a = evaluate_dynamic_sl_tp(pos(tier=2), 100.5, LADDER)
    assert (a["action"], a["tier"]) == ("hold", 2)
    assert a["new_stop"] == pytest.approx(101.5)


def test_fees_are_added_to_the_target():
    # 1.5% gross is not enough when each side costs 0.1%: the target is 1.5% + 2 x 0.1%
    assert evaluate_dynamic_sl_tp(pos(), 101.5, LADDER, fee_rate=0.001)["action"] == "hold"
    assert evaluate_dynamic_sl_tp(pos(), 101.7, LADDER, fee_rate=0.001)["action"] == "partial_take"


def test_static_mode_exits_on_rsi_above_70():
    cfg = {"dynamic": False, "0_stop_loss": 0.02}
    assert evaluate_dynamic_sl_tp(pos(), 100.5, cfg, rsi_value=71.0)["action"] == "exit"
    assert evaluate_dynamic_sl_tp(pos(), 100.5, cfg, rsi_value=60.0)["action"] == "hold"


def test_static_mode_stops_out_two_percent_below_entry():
    cfg = {"dynamic": False, "0_stop_loss": 0.02}
    assert evaluate_dynamic_sl_tp(pos(), 97.9, cfg)["action"] == "exit"
