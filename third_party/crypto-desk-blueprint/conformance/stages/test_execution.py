"""Stage 07 acceptance tests: order generation and fills (blueprint/07-execution.md)."""
import pytest

from pipeline.types import AccountState, OrderIntent, TargetPortfolio

pytestmark = pytest.mark.execution


def _apply(account, orders):
    pos = dict(account.positions)
    for o in orders:
        pos[o.instrument_id] = pos.get(o.instrument_id, 0.0) + o.qty
    return pos


def test_orders_reach_target(impl):
    """AT-07-1. Equity 10,000, long 0.5 A at 100, target weight 0.2: after the orders the position is 20.
    Catches: mutants/execution_sends_target_not_delta."""
    acct = AccountState(1, 10_000.0, {"A": 0.5}, {"A": 100.0})
    pos = _apply(acct, impl.make_executor().orders(TargetPortfolio(1, {"A": 0.2}), acct))
    assert pos["A"] == pytest.approx(20.0, rel=1e-9)


def test_no_orders_at_target(impl):
    """AT-07-2. Already at target: no orders (no churn, no fees)."""
    acct = AccountState(1, 10_000.0, {"A": 20.0}, {"A": 100.0})
    assert impl.make_executor().orders(TargetPortfolio(1, {"A": 0.2}), acct) == []


def test_reduce_only_flags(impl):
    """AT-07-3. Shrinking 30 -> 20 is reduce-only; growing 10 -> 20 is not.
    Catches: mutants/execution_never_reduce_only."""
    ex = impl.make_executor()
    shrink = ex.orders(TargetPortfolio(1, {"A": 0.2}), AccountState(1, 10_000.0, {"A": 30.0}, {"A": 100.0}))
    grow = ex.orders(TargetPortfolio(1, {"A": 0.2}), AccountState(1, 10_000.0, {"A": 10.0}, {"A": 100.0}))
    assert [o.reduce_only for o in shrink] == [True] and [o.reduce_only for o in grow] == [False]


def test_fills_pay_costs(impl):
    """AT-07-4. A buy and a sell of 1 unit at mid 100 each cost more than zero against mid.
    Catches: mutants/execution_free_fills."""
    venue = impl.make_venue()
    for qty in (1.0, -1.0):
        f = venue.submit(OrderIntent("A", 1, qty, False, f"id{qty}"), mid=100.0, bar_volume=1_000.0)
        assert (f.price - 100.0) * f.qty + f.fee > 0
