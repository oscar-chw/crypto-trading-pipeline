"""Stage 04 acceptance tests: carry pricing and funding (blueprint/04-pricing.md)."""
import math

import pytest

from pipeline.types import NS_PER_YEAR

pytestmark = pytest.mark.pricing


def test_fair_matches_carry(impl):
    """AT-04-1. Spot 100, one year, r_quote 8%, r_base 2% gives 100*exp(0.06); r_quote < r_base gives
    backwardation. Catches: mutants/pricing_carry_sign."""
    p = impl.make_pricing()
    fv = p.fair_value("F", 0, 100.0, NS_PER_YEAR, 0.08, 0.02)
    assert fv.fair_price == pytest.approx(100 * math.exp(0.06), rel=1e-9)
    assert p.fair_value("F", 0, 100.0, NS_PER_YEAR, 0.01, 0.05).fair_price < 100.0


def test_band_brackets_fair(impl):
    """AT-04-2. The no-arbitrage band strictly contains fair value when trading costs are positive."""
    fv = impl.make_pricing().fair_value("F", 0, 100.0, NS_PER_YEAR // 4, 0.05, 0.0)
    assert fv.band_low < fv.fair_price < fv.band_high


def test_long_pays_positive_funding(impl):
    """AT-04-3. Long 2 at mark 100 with rate +0.01% pays 0.02; the short receives 0.02.
    Catches: mutants/pricing_funding_sign."""
    p = impl.make_pricing()
    assert p.funding_cashflow(2.0, 100.0, 0.0001) == pytest.approx(-0.02)
    assert p.funding_cashflow(-2.0, 100.0, 0.0001) == pytest.approx(0.02)


def test_expired_contract_rejected(impl):
    """AT-04-4. Pricing a future at or after its expiry raises instead of returning a number."""
    with pytest.raises(ValueError):
        impl.make_pricing().fair_value("F", NS_PER_YEAR, 100.0, NS_PER_YEAR, 0.05, 0.0)
