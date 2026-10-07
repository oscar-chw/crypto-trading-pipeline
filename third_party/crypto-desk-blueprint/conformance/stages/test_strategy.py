"""Stage 03 acceptance tests: strategy (blueprint/03-strategy.md)."""
import math

import pytest

pytestmark = pytest.mark.strategy


def test_missing_features_mean_flat(impl):
    """AT-03-1. NaN inputs give score 0 (no view), not an error and not a trade.
    Catches: mutants/strategy_trades_on_nan."""
    s = impl.make_strategy().signal("X", 10, {f: math.nan for f in impl.STRATEGY_FEATURES})
    assert s.score == 0.0


def test_bounded_and_stamped(impl):
    """AT-03-2. Extreme inputs still give a valid Signal in [-1, 1], stamped at decision time t."""
    strat = impl.make_strategy()
    for x in (-1e9, -1.0, 0.0, 1.0, 1e9):
        s = strat.signal("X", 123, {f: x for f in impl.STRATEGY_FEATURES})
        assert -1.0 <= s.score <= 1.0 and s.t == 123 and s.instrument_id == "X"


def test_deterministic(impl):
    """AT-03-3. Same inputs, same signal: a strategy with hidden randomness cannot be reconciled live."""
    a, b = impl.make_strategy(), impl.make_strategy()
    f = {k: 0.03 for k in impl.STRATEGY_FEATURES}
    assert a.signal("X", 1, f) == b.signal("X", 1, f)
