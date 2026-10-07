"""Stage 02 acceptance tests: features (blueprint/02-features.md)."""
import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.features


@pytest.fixture(scope="module")
def frame():
    rng = np.random.default_rng(11)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    idx = pd.Index(np.arange(1, 401, dtype=np.int64) * 3_600_000_000_000, name="close_time")
    return pd.DataFrame({"open": close, "high": close * 1.001, "low": close * 0.999, "close": close,
                         "volume": rng.lognormal(3, 0.5, 400)}, index=idx)


def test_point_in_time(impl, frame):
    """AT-02-1. A value computed at t does not change when bars after t are appended.
    Input: 400 random-walk bars, cut at three points. Catches: mutants/feature_peeks_ahead."""
    feat = impl.make_feature()
    full = feat.compute(frame)
    for k in (feat.lookback + 3, 200, 399):
        pd.testing.assert_series_equal(feat.compute(frame.iloc[:k]), full.iloc[:k], check_names=False)


def test_warmup_is_nan(impl, frame):
    """AT-02-2. The first lookback-1 values are NaN, never filled; from lookback on they are finite.
    Catches: mutants/feature_fills_warmup."""
    feat = impl.make_feature()
    out = feat.compute(frame)
    assert out.iloc[: feat.lookback - 1].isna().all()
    assert np.isfinite(out.iloc[feat.lookback - 1:]).all()


def test_index_aligned(impl, frame):
    """AT-02-3. Output index equals the input index (stamped by bar close)."""
    assert impl.make_feature().compute(frame).index.equals(frame.index)
