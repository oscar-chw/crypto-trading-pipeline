"""Stage 06 acceptance tests: portfolio construction (blueprint/06-portfolio.md)."""
import pytest

from pipeline.types import RiskForecast, Signal

pytestmark = pytest.mark.portfolio
H = 3_600_000_000_000


def test_gross_cap(impl):
    """AT-06-1. Ten full-conviction signals on low-vol assets never exceed the constructor's max_gross.
    Catches: mutants/portfolio_no_gross_cap."""
    pc = impl.make_portfolio()
    sigs = [Signal(f"C{i}", 1, 1.0, H, "t") for i in range(10)]
    risk = RiskForecast(1, {f"C{i}": 1e-4 for i in range(10)}, 8760)
    assert pc.target(1, sigs, risk).gross <= pc.max_gross + 1e-12


def test_zero_signal_zero_weight(impl):
    """AT-06-2. A score of 0 gives a weight of 0."""
    tp = impl.make_portfolio().target(1, [Signal("A", 1, 0.0, H, "t")], RiskForecast(1, {"A": 0.01}, 8760))
    assert tp.weights.get("A", 0.0) == 0.0


def test_inverse_vol_scaling(impl):
    """AT-06-3. Same small signal, doubled forecast vol: the position must shrink.
    Catches: mutants/portfolio_ignores_vol."""
    pc = impl.make_portfolio()
    s = [Signal("A", 1, 0.05, H, "t")]
    w1 = pc.target(1, s, RiskForecast(1, {"A": 0.01}, 8760)).weights["A"]
    w2 = pc.target(1, s, RiskForecast(1, {"A": 0.02}, 8760)).weights["A"]
    assert 0 < w2 < w1
