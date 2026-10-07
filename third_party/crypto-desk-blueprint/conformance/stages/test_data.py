"""Stage 01 acceptance tests: market data source (blueprint/01-data.md)."""
import pytest

pytestmark = pytest.mark.data


def _sample(impl):
    src = impl.make_data_source()
    inst, start, end = impl.DATA_SAMPLE
    return src, inst, start, end


def test_ordered_unique(impl):
    """AT-01-1. Bars come strictly increasing in close_time, with no duplicates.
    Catches: mutants/data_duplicate."""
    src, inst, start, end = _sample(impl)
    times = [b.close_time for b in src.bars(inst, start, end)]
    assert len(times) > 10
    assert all(a < b for a, b in zip(times, times[1:]))


def test_window_respected(impl):
    """AT-01-2. Every bar satisfies start < close_time <= end, and a shorter window is an exact prefix.
    Catches: mutants/data_window_leak."""
    src, inst, start, end = _sample(impl)
    full = src.bars(inst, start, end)
    assert all(start < b.close_time <= end for b in full)
    mid = full[len(full) // 2].close_time
    assert src.bars(inst, start, mid) == [b for b in full if b.close_time <= mid]


def test_replayable(impl):
    """AT-01-3. Two reads of the same window return identical bars."""
    src, inst, start, end = _sample(impl)
    assert src.bars(inst, start, end) == src.bars(inst, start, end)
