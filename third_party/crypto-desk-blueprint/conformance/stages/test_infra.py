"""Stage 00 acceptance tests: clock and point-in-time store (blueprint/00-infrastructure.md)."""
import pytest

from pipeline.store import LookAheadError

pytestmark = pytest.mark.infra


def test_clock_monotonic(impl):
    """AT-00-1. A clock at 0 advanced by 5 reads 5; any step back raises. Catches: mutants/clock_goes_back."""
    clock = impl.make_clock(0)
    assert clock.advance(5) == 5 and clock.now() == 5
    with pytest.raises(ValueError):
        clock.advance(-1)
    with pytest.raises(ValueError):
        clock.set(3)
    assert clock.now() == 5


def test_store_refuses_read_after_as_of(impl):
    """AT-00-2. A record published at 12 is invisible as of 11, and reading past as_of raises.
    Catches: mutants/store_no_guard."""
    store = impl.make_store()
    store.append("k", event_time=10, available_at=12, value=1.0)
    assert store.view(as_of=11).read("k", 0, 11) == []
    with pytest.raises(LookAheadError):
        store.view(as_of=11).read("k", 0, 20)
    assert [r.value for r in store.view(as_of=12).read("k", 0, 12)] == [1.0]


def test_revision_visible_only_after_publication(impl):
    """AT-00-3. A correction published at 20 must not change what a view as of 15 sees."""
    store = impl.make_store()
    store.append("k", 10, 12, 1.0)
    store.append("k", 10, 20, 2.0)
    assert store.view(15).latest("k").value == 1.0
    assert store.view(25).latest("k").value == 2.0
