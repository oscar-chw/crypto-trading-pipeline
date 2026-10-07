"""Stage 08 acceptance tests: purged CV and deflated Sharpe (blueprint/08-validation.md)."""
import numpy as np
import pytest

from pipeline.stats import probabilistic_sharpe_ratio

pytestmark = pytest.mark.validation
H = 3_600_000_000_000


def _labels():
    t0 = np.arange(200, dtype=np.int64) * H
    return t0, t0 + 10 * H  # each label spans 10 hours, so neighbours overlap


def test_no_train_test_overlap(impl):
    """AT-08-1. No training label interval intersects any test label interval.
    Catches: mutants/cv_no_purge."""
    t0, t1 = _labels()
    for train, test in impl.make_cv_splitter().split(t0, t1):
        a0, a1 = t0[train][:, None], t1[train][:, None]
        assert not np.any((a0 <= t1[test][None, :]) & (a1 >= t0[test][None, :]))


def test_folds_partition(impl):
    """AT-08-2. Test folds are disjoint and together cover every sample once."""
    t0, t1 = _labels()
    tests = np.concatenate([te for _, te in impl.make_cv_splitter().split(t0, t1)])
    assert sorted(tests.tolist()) == list(range(len(t0)))


def test_embargo(impl):
    """AT-08-3. No training sample starts within embargo_ns after a test block ends.
    Catches: mutants/cv_no_embargo."""
    sp = impl.make_cv_splitter()
    assert sp.embargo_ns > 0
    t0, t1 = _labels()
    for train, test in sp.split(t0, t1):
        end = t1[test].max()
        assert not np.any((t0[train] > end) & (t0[train] <= end + sp.embargo_ns))


def test_dsr_penalises_trials(impl):
    """AT-08-4. With one trial the deflated Sharpe equals PSR against 0; with 100 trials it is lower.
    Catches: mutants/dsr_ignores_trials."""
    one = impl.deflated_sharpe(0.1, 500, 1, 0.002)
    assert one == pytest.approx(probabilistic_sharpe_ratio(0.1, 0.0, 500))
    assert impl.deflated_sharpe(0.1, 500, 100, 0.002) < one - 0.05
