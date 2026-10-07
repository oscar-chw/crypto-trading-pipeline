"""Stage 05 acceptance tests: risk model and risk gate (blueprint/05-risk.md)."""
import numpy as np
import pandas as pd
import pytest

from pipeline.risk import RiskLimits
from pipeline.types import TargetPortfolio

pytestmark = pytest.mark.risk


def _returns(n, sd, seed):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"A": rng.normal(0, sd, n)}, index=np.arange(1, n + 1, dtype=np.int64))


def test_forecast_is_point_in_time(impl):
    """AT-05-1. The forecast at t is the same whether or not rows after t are present.
    Catches: mutants/risk_uses_future."""
    r = _returns(300, 0.01, 1)
    t = int(r.index[199])
    model = impl.make_risk_model()
    assert model.forecast(t, r).vol["A"] == pytest.approx(model.forecast(t, r.iloc[:200]).vol["A"], rel=1e-12)


def test_vol_responds_to_shock(impl):
    """AT-05-2. After 200 calm bars (sd 1%) then 20 stressed bars (sd 5%), forecast vol at least doubles.
    Catches: a constant-volatility model (mutants/risk_constant_vol)."""
    calm, shock = _returns(200, 0.01, 2), _returns(20, 0.05, 3)
    shock.index = shock.index + 200
    r = pd.concat([calm, shock])
    model = impl.make_risk_model()
    assert model.forecast(220, r).vol["A"] > 2 * model.forecast(200, r).vol["A"]


def test_kill_switch_blocks_new_risk(impl):
    """AT-05-3. With the kill switch tripped, any target becomes all-zero (flatten) and halted.
    Catches: mutants/risk_ignores_kill_switch."""
    engine = impl.make_risk_engine(RiskLimits())
    engine.kill_switch.trip("test")
    d = engine.check(TargetPortfolio(1, {"A": 0.2}), {"A": 0.1, "B": -0.1})
    assert d.halted and all(w == 0.0 for w in d.target.weights.values()) and set(d.target.weights) == {"A", "B"}


def test_drawdown_breach_trips_kill_switch(impl):
    """AT-05-4. Equity 100 then 79 with a 20% drawdown budget trips the kill switch."""
    engine = impl.make_risk_engine(RiskLimits(max_drawdown=0.20, daily_loss_limit=0.5))
    engine.update_equity(0, 100.0)
    assert not engine.kill_switch.tripped
    engine.update_equity(1, 79.0)
    assert engine.kill_switch.tripped


def test_caps_clip_target(impl):
    """AT-05-5. Target +-0.9 with max_weight 0.25 and max_gross 0.4 comes back inside both caps."""
    engine = impl.make_risk_engine(RiskLimits(max_weight=0.25, max_gross=0.4))
    d = engine.check(TargetPortfolio(1, {"A": 0.9, "B": -0.9}), {})
    assert max(abs(w) for w in d.target.weights.values()) <= 0.25 + 1e-12
    assert d.target.gross <= 0.4 + 1e-12
