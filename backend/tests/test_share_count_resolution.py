"""Share-count adjudication, and the two listing structures that make it hard.

A share count is not a single fact, and two published sources disagree about
public companies routinely — for opposite reasons:

  - A MULTI-CLASS issuer, where the provider's summary field reports ONE class
    and the filed balance sheet reports the total. One large-cap returned 5.87bn
    against a filed 12.23bn, so its market capitalisation came out at half and
    every per-share figure at double. The filing is right.

  - A DEPOSITARY listing, where the quoted price is per receipt and the filed
    count is in ORDINARY shares. One foundry returned a filed 25.9bn against
    5.19bn receipt-equivalent — a ratio of exactly 5, its receipt ratio — so
    multiplying the receipt price by the filed count overstated the market
    capitalisation fivefold. The provider is right.

Pinning "filed always wins" fixed the first and broke the second, which is why
the choice is made from the SHAPE of the disagreement and lives in one function
that both the valuation and the peer path call.
"""

from __future__ import annotations

import pytest

from backend.data.providers.share_count import (
    _AGREEMENT_TOLERANCE,
    _MIN_CREDIBLE_RECEIPT_RATIO,
    resolve_share_count,
)


def test_agreeing_sources_report_the_filing():
    filed, provider = 7_425_545_491.0, 7_427_000_000.0
    count, basis = resolve_share_count(filed, provider, filed_basis="Ordinary Shares Number")

    assert count == pytest.approx(filed)
    assert "agreed" in basis


def test_small_difference_is_rounding_not_a_disagreement():
    """A buyback moves the count between two filings; that is not a class split."""
    filed, provider = 14_687_356_000.0, 14_594_180_000.0
    count, basis = resolve_share_count(filed, provider, filed_basis="Ordinary Shares Number")

    assert count == pytest.approx(filed)
    assert "rejected" not in basis


# --------------------------------------------------------------------------- #
# Multi-class issuers: the filed total is the market capitalisation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "filed, provider, note",
    [
        (12_229_934_831.0, 5_867_155_790.0, "Class A plus Class C plus Class B"),
        (2_548_377_716.0, 2_205_128_509.0, "Class A plus Class B"),
        (4_424_805_520.0, 3_341_900_000.0, "two share classes of different size"),
    ],
)
def test_ragged_ratio_means_share_classes_and_the_filing_wins(filed, provider, note):
    """A ratio that is not near a whole number is a class structure.

    Companies do not choose class ratios that are round. A market capitalisation
    is defined on the total across all classes, which is what the filing states.
    """
    count, basis = resolve_share_count(filed, provider, filed_basis="Ordinary Shares Number")

    assert count == pytest.approx(filed), note
    assert "single-class figure" in basis, basis


def test_a_company_can_hold_its_value_with_the_total_across_classes():
    """The consequence that matters: a per-share figure moves by the ratio."""
    filed, provider = 12_229_934_831.0, 5_867_155_790.0
    price = 343.92

    count, _ = resolve_share_count(filed, provider, filed_basis="Ordinary Shares Number")

    assert price * count / 1e12 == pytest.approx(4.206, abs=0.01)
    # Taking the provider's single class would have shown 2.02tn — half.
    assert price * provider / 1e12 == pytest.approx(2.018, abs=0.01)


# --------------------------------------------------------------------------- #
# Depositary listings: the price is per receipt
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "filed, provider, ratio",
    [
        (25_932_370_067.0, 5_186_474_013.0, 5),   # 1 receipt = 5 ordinary
        (19_192_691_158.0, 2_486_400_000.0, 8),   # 1 receipt = 8 ordinary
    ],
)
def test_round_large_ratio_means_a_receipt_and_the_provider_wins(filed, provider, ratio):
    """Share counts do not land on 5.000x by accident; receipt ratios are 2, 5, 8, 10.

    Here the price is quoted per receipt, so the count has to be
    receipt-equivalent or the market capitalisation is out by the ratio.
    """
    count, basis = resolve_share_count(filed, provider, filed_basis="Ordinary Shares Number")

    assert count == pytest.approx(provider)
    assert "depositary receipt ratio" in basis, basis
    assert str(ratio) in basis


def test_a_receipt_listing_is_not_overstated_by_its_ordinary_count():
    """The consequence that matters: a fivefold market-cap error."""
    filed, provider = 25_932_370_067.0, 5_186_474_013.0
    price = 450.61

    count, _ = resolve_share_count(filed, provider, filed_basis="Ordinary Shares Number")

    assert price * count / 1e9 == pytest.approx(2_337.0, abs=5.0)
    # Using the ordinary count would have claimed an 11.7tn valuation.
    assert price * filed / 1e9 == pytest.approx(11_685.0, abs=5.0)


def test_a_ratio_too_small_to_be_a_receipt_is_read_as_classes():
    """2:1 is ambiguous, and the class reading is the safe one.

    A 2:1 receipt and a two-class issuer with classes of similar size produce
    the same ratio. Choosing classes keeps the total across classes, which is
    what a market capitalisation means; choosing the receipt would discard a
    whole class.
    """
    filed, provider = 2_000_000_000.0, 1_000_000_000.0
    count, basis = resolve_share_count(filed, provider, filed_basis="Ordinary Shares Number")

    assert count == pytest.approx(filed)
    assert "single-class figure" in basis


def test_the_receipt_floor_is_documented_by_the_constant():
    """The threshold is part of the rule, so a change to it is a visible change."""
    assert _MIN_CREDIBLE_RECEIPT_RATIO >= 4.0


# --------------------------------------------------------------------------- #
# Absent sources
# --------------------------------------------------------------------------- #

def test_only_the_filing_available():
    count, basis = resolve_share_count(1000.0, None, filed_basis="Ordinary Shares Number")

    assert count == pytest.approx(1000.0)
    assert "filed" in basis


def test_only_the_provider_available():
    count, basis = resolve_share_count(None, 1000.0, filed_basis="")

    assert count == pytest.approx(1000.0)
    assert "does not report the line" in basis


def test_neither_available_is_unresolved_not_zero():
    """A missing count must not become a zero, which would imply no shares exist."""
    count, basis = resolve_share_count(None, None)

    assert count is None
    assert basis == "unresolved"


def test_a_zero_provider_does_not_override_the_filing():
    filed, provider = 1000.0, 0.0
    count, _ = resolve_share_count(filed, provider, filed_basis="Ordinary Shares Number")

    assert count == pytest.approx(filed)


def test_the_tolerance_separates_rounding_from_a_real_disagreement():
    """A divergence inside the tolerance is agreement; outside it is not."""
    just_inside = 1.0 + _AGREEMENT_TOLERANCE * 0.9
    just_outside = 1.0 + _AGREEMENT_TOLERANCE * 1.5

    _, inside_basis = resolve_share_count(1000.0 * just_inside, 1000.0, filed_basis="x")
    _, outside_basis = resolve_share_count(1000.0 * just_outside, 1000.0, filed_basis="x")

    assert "agreed" in inside_basis
    assert "rejected" in outside_basis


def test_the_basis_names_both_sources_when_they_disagree():
    """A reader has to be able to see the decision, not infer it."""
    filed, provider = 12_229_934_831.0, 5_867_155_790.0
    _, basis = resolve_share_count(filed, provider, filed_basis="Ordinary Shares Number")

    assert "12,229,934,831" in basis or "12,229.93" in basis
    assert "5,867" in basis
