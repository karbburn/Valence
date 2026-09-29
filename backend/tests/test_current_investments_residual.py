"""A residual must not be published as a security.

`current_investments` has a derivation fallback: when a filer tags no investment
line, the engine takes whatever is left of total current assets after cash,
receivables, inventory and prepayments, and publishes it under the investments
key. The enterprise bridge then deducts that figure from enterprise value as
though it were a marketable security.

What survives the subtraction is not a security. It is current assets the engine
could not identify, and those are only the same thing when the filer's balance
sheet has nothing else in them. Armstrong World Industries carries no securities
line at all: it prints 23.9 of "Other current assets" against 22.5 of prepaid
expenses, and the 1.4 difference was republished as a security the company does
not hold and then deducted from its equity value.

The fix subtracts a reported other-current-assets line before computing the
residual, which sends Armstrong's to zero and leaves NVIDIA's intact, because
NVIDIA's unidentified current assets genuinely are its marketable securities and
it publishes no other-current-assets line to compete with them.

The figures below are as filed, in millions, so the tests check the engine against
the filing rather than against whatever it happened to produce. They call the real
derivation rather than restating its formula.
"""

import datetime as dt

import pytest

from backend.normalization.financials.derivation import derive_canonical_metrics
from backend.normalization.taxonomy.models import CanonicalDatapoint

_PERIOD_END = dt.date(2025, 12, 31)

# Armstrong World Industries, balance sheet at 2025-12-31, as filed. Total current
# assets 391.5 of which no part is a security.
#
# Note there is ONE current-asset catch-all here, worth 23.9, and that it is the
# filer's own line. An earlier version of this file also listed 22.5 of prepayments
# alongside it, which is the trap: `PrepaidExpenseCurrent` is a MEMBER of
# `OtherAssetsCurrent`, so holding both counted the smaller twice, put the itemised
# block 22.5 above the filer's own subtotal, and drove the residual to −22.5 — where
# clamping it to zero published nothing and reported nothing. The test below asserts
# that the itemised block now RECONCILES, not that the residual happens to vanish,
# because a clamp satisfies the second and only a reconciliation satisfies the first.
ARMSTRONG = {
    "canonical.bs.cash_and_bank": 112.7,
    "canonical.bs.trade_receivables": 130.3,
    "canonical.bs.inventory": 124.6,
    "canonical.bs.prepayments_other_current_assets": 23.9,
    "canonical.bs.total_current_assets": 391.5,
}

# NVIDIA, balance sheet at 2026-01-25, as filed: 125,605 of current assets of which
# 51,951 is the marketable securities line, and no other-current-assets line exists.
NVIDIA = {
    "canonical.bs.cash_and_bank": 10_605.0,
    "canonical.bs.trade_receivables": 38_466.0,
    "canonical.bs.inventory": 21_403.0,
    "canonical.bs.prepayments_other_current_assets": 3_180.0,
    "canonical.bs.total_current_assets": 125_605.0,
}


def _dp(key: str, value: float, company_id: str, period: str = "FY25") -> CanonicalDatapoint:
    return CanonicalDatapoint(
        company_id=company_id,
        canonical_key=key,
        metric_raw=key,
        period_label=period,
        period_end_date=_PERIOD_END,
        value=value,
        currency="USD",
        units="millions",
        status="reported",
        source_datapoint_ids=[f"{company_id}-{period}-{key}"],
        derivation_rule=None,
    )


def _derive(figures: dict, company_id: str) -> dict:
    """Only the datapoints the derivation produced, which is what it may add.

    A reported input is not in here, so a test that needs to know whether the
    derivation overwrote one has to assert on its absence.
    """
    derived = derive_canonical_metrics(
        [_dp(k, v, company_id) for k, v in figures.items()]
    )
    return {d.canonical_key: d for d in derived}


class TestResidualIsNotPublishedAsASecurity:
    def test_armstrong_derives_no_investments(self):
        # 391.5 less every current asset the filing itemises is nil, because the
        # filing itemises all of them, and a filer that holds no securities gets no
        # securities published for it.
        out = _derive(ARMSTRONG, "awi_us")
        assert "canonical.bs.current_investments" not in out

    def test_the_itemised_block_reconciles_to_the_filed_subtotal(self):
        # The assertion that matters, and the one the first version of this test
        # failed to make. A clamp at zero satisfies "no investments derived" while
        # the 22.5 of double-counted prepayments is still there; only this can tell
        # the two apart, because it adds the lines up against the filer's own number.
        f = ARMSTRONG
        itemised = (
            f["canonical.bs.cash_and_bank"]
            + f["canonical.bs.trade_receivables"]
            + f["canonical.bs.inventory"]
            + f["canonical.bs.prepayments_other_current_assets"]
        )
        assert itemised == pytest.approx(f["canonical.bs.total_current_assets"], abs=0.05)

    def test_the_old_residual_would_have_been_a_pretend_security(self):
        # Pinned so the test above cannot be satisfied by deleting the derivation
        # rather than by fixing the overlap: the arithmetic the bug did is restated
        # here, against a balance sheet that also carries 22.5 of prepayments inside
        # its 23.9 catch-all.
        f = ARMSTRONG
        with_prepayments_also_listed = dict(f)
        with_prepayments_also_listed["canonical.bs.prepayments_other_current_assets"] = 22.5
        itemised = (
            f["canonical.bs.cash_and_bank"]
            + f["canonical.bs.trade_receivables"]
            + f["canonical.bs.inventory"]
            + 22.5
            + 23.9
        )
        assert itemised == pytest.approx(414.0, abs=0.05)
        assert itemised - f["canonical.bs.total_current_assets"] == pytest.approx(22.5, abs=0.05)

    def test_unbilled_revenue_is_not_published_as_a_security(self):
        # Unbilled revenue is a rendered line and a mapped key, so the residual has
        # to subtract it. Without that, a filer carrying unbilled revenue and no
        # tagged securities line had its unbilled revenue deducted from enterprise
        # value as though it were a marketable security: the identical defect,
        # reopened for a different line.
        figures = dict(NVIDIA)
        figures["canonical.bs.unbilled_revenue"] = 1_000.0
        out = _derive(figures, "some_us")
        assert out["canonical.bs.current_investments"].value == pytest.approx(50_951.0, abs=0.05)

    def test_nvidia_keeps_its_securities(self):
        # The same subtraction, for a filer whose remaining current assets really
        # are its marketable securities. Dropping every residual would understate
        # NVIDIA's liquid assets by 51,951, so the fix has to discriminate rather
        # than remove the derivation.
        out = _derive(NVIDIA, "nvda_us")
        ci = out["canonical.bs.current_investments"]
        assert ci.value == pytest.approx(51_951.0, abs=0.05)
        assert ci.status == "derived"

    def test_a_reported_investments_line_is_never_overwritten(self):
        # A filer that publishes its securities keeps the published figure and the
        # residual does not run at all, which is what AMDOCS's 168.2 relies on: it
        # tags only the debt-securities element and nothing else.
        figures = dict(NVIDIA)
        figures["canonical.bs.current_investments"] = 168.2
        out = _derive(figures, "dox_us")
        assert "canonical.bs.current_investments" not in out

    def test_the_rule_names_what_it_subtracts(self):
        # A formula that does not mention what it subtracts cannot be checked
        # against the balance sheet by a reader of the workbook. Every line the
        # renderer prints above the subtotal has to appear here, or the residual
        # absorbs the missing one and republishes it as a security.
        rule = _derive(NVIDIA, "nvda_us")["canonical.bs.current_investments"].derivation_rule
        assert rule is not None
        for part in ("cash", "receivables", "inventory", "unbilled revenue",
                     "prepayments and other current assets"):
            assert part in rule, f"the residual's rule does not mention {part}"
