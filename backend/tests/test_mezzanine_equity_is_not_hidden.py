"""A filer's reported total liabilities must not be overwritten by a back-solve.

The balance sheet reconciles its subtotals: when total liabilities plus total
equity does not equal the filer's own total-liabilities-and-equity, one side is
adjusted. For most filers the reason is that the assembled liability components
fell short, and back-solving the subtotal is the correct response.

For a filer that prints MEZZANINE EQUITY -- redeemable preferred, redeemable
noncontrolling interest -- the reason is different: there is a third claim class
between liabilities and equity that the model had no line for. Uxin filed
liabilities 330,838, mezzanine 48,056, and a shareholders' deficit of -33,017.
The back-solve produced total_liabilities of 378,894: a 14.5% overstatement of a
figure the filer had reported exactly, with the mezzanine silently inside it.

The failure is close to invisible. The balance sheet still foots, total assets is
untouched, no QA check fires, and the only symptom is a published liabilities
number that appears in no filing. A sampling tie-out over 45 filers found total
assets exact in every case and flagged this line as the only systematic
disagreement -- which is the argument for running the harness at all.

So a reported subtotal is kept as reported, and the residual is named.
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.models.statements.balance_sheet import assemble_balance_sheet
from backend.normalization.taxonomy.models import CanonicalDatapoint

COMPANY = "mezzco_us"


def _dp(key: str, value: float, status: str = "reported") -> CanonicalDatapoint:
    return CanonicalDatapoint(
        id=f"{COMPANY}-{key}-FY25",
        company_id=COMPANY,
        canonical_key=key,
        metric_raw=key.rsplit(".", 1)[-1],
        period_label="FY25",
        period_end_date=date(2025, 12, 31),
        value=value,
        currency="USD",
        units="millions",
        status=status,
        source_datapoint_ids=[f"{COMPANY}-fixture"],
    )


def _build(dps):
    result = assemble_balance_sheet(dps, target_periods=["FY25"])
    items = result.line_items if hasattr(result, "line_items") else result
    return {i.canonical_key: i for i in items}


# Uxin's filed FY25 balance sheet, in millions: liabilities 330.838, mezzanine
# equity 48.056, shareholders' deficit -33.017, total 345.877.
#
# The mezzanine line is present because the filer published it. That is the
# discriminator: an earlier version of the fix preserved ANY reported subtotal that
# did not foot, which published TCS's -7,698 fixture imbalance as "mezzanine
# equity" -- inventing a claim class to explain a data-entry error. Only a filer
# that says it has redeemable preferred or redeemable noncontrolling interest gets
# its subtotal preserved.
MEZZANINE_ROWS = [
    ("canonical.bs.total_assets", 345.877),
    ("canonical.bs.total_liabilities", 330.838),
    ("canonical.bs.mezzanine_equity", 48.056),
    ("canonical.bs.total_equity", -33.017),
    ("canonical.bs.total_liabilities_and_equity", 345.877),
]


class TestAnUnexplainedResidualIsNotCalledMezzanine:
    def test_a_reported_subtotal_that_does_not_foot_still_gets_back_solved(self) -> None:
        """TCS's case: no mezzanine, the numbers simply do not foot.

        Preserving the reported subtotal here would publish a "-7,698 mezzanine
        equity" that the filer never reported, for a hand-entered fixture whose
        liability components fall short. The back-solve is the right answer when
        there is no known claim class to point at.
        """
        by_key = _build([
            _dp("canonical.bs.total_assets", 174.162),
            _dp("canonical.bs.total_liabilities", 73.298),
            _dp("canonical.bs.total_equity", 108.562),
            _dp("canonical.bs.total_liabilities_and_equity", 174.162),
        ])
        tl = by_key["canonical.bs.total_liabilities"]
        assert tl.values_by_period["FY25"] == pytest.approx(65.600, abs=0.01), (
            "without a published mezzanine line the subtotal must still be "
            f"back-solved; got {tl.values_by_period['FY25']}"
        )
        assert "canonical.bs.mezzanine_equity" not in by_key, (
            "a mezzanine line was invented for a filer that published none"
        )


class TestReportedSubtotalSurvives:
    def test_reported_total_liabilities_is_kept_as_reported(self) -> None:
        by_key = _build([_dp(k, v) for k, v in MEZZANINE_ROWS])
        tl = by_key["canonical.bs.total_liabilities"]
        assert tl.values_by_period["FY25"] == pytest.approx(330.838), (
            "the filer's reported total liabilities was overwritten by a back-solve; "
            f"published {tl.values_by_period['FY25']} against a filed 330.838"
        )
        assert tl.status_by_period.get("FY25") == "reported", (
            "a figure the filer reported must not be re-statused as derived"
        )

    def test_the_residual_is_named_rather_than_dropped(self) -> None:
        by_key = _build([_dp(k, v) for k, v in MEZZANINE_ROWS])
        mezz = by_key.get("canonical.bs.mezzanine_equity")
        assert mezz is not None, (
            "the 48.056 residual was dropped instead of named; the balance sheet "
            "would then be missing a real claim sitting ahead of common equity"
        )
        assert mezz.values_by_period["FY25"] == pytest.approx(48.056, abs=0.01)

    def test_the_balance_sheet_still_foots(self) -> None:
        by_key = _build([_dp(k, v) for k, v in MEZZANINE_ROWS])
        built = (
            by_key["canonical.bs.total_liabilities"].values_by_period["FY25"]
            + by_key["canonical.bs.mezzanine_equity"].values_by_period["FY25"]
            + by_key["canonical.bs.total_equity"].values_by_period["FY25"]
        )
        assert built == pytest.approx(345.877, abs=0.01), (
            "naming the residual must not stop the balance sheet footing"
        )


class TestTheBackSolveStillWorksWhereItBelongs:
    def test_a_derived_subtotal_is_still_back_solved(self) -> None:
        """The original correction must survive.

        A filer whose assembled liability components fall short of its own subtotal
        is the case the back-solve was written for, and it is still right there.
        Only a REPORTED subtotal is protected. If this fails, the mezzanine fix has
        swallowed the correction it was meant to sit beside.

        The subtotal is supplied as `derived`, which is how an assembled-components
        total reaches this code: `_reported` returns None for it, so the correction
        engages.
        """
        by_key = _build([
            _dp("canonical.bs.total_assets", 400.0),
            _dp("canonical.bs.total_liabilities", 250.0, status="derived"),
            _dp("canonical.bs.total_equity", 100.0),
            _dp("canonical.bs.total_liabilities_and_equity", 400.0),
        ])
        tl = by_key["canonical.bs.total_liabilities"]
        assert tl.values_by_period["FY25"] == pytest.approx(300.0, abs=0.01), (
            "a DERIVED subtotal must still be back-solved from the filer's own "
            "balance-sheet subtotal less its equity; got "
            f"{tl.values_by_period['FY25']}"
        )
        assert "canonical.bs.mezzanine_equity" not in by_key, (
            "no residual exists when the correction applies; nothing should be named"
        )

    def test_subtotals_that_foot_produce_no_residual_line(self) -> None:
        by_key = _build([
            _dp("canonical.bs.total_assets", 400.0),
            _dp("canonical.bs.total_liabilities", 300.0),
            _dp("canonical.bs.total_equity", 100.0),
            _dp("canonical.bs.total_liabilities_and_equity", 400.0),
        ])
        assert "canonical.bs.mezzanine_equity" not in by_key, (
            "a mezzanine line appeared for a filer whose subtotals already foot; "
            "that would invent a claim class that does not exist"
        )


class TestAFilersMezzanineMustEqualTheResidual:
    """The mezzanine branch used to fire on the mere EXISTENCE of a mezzanine line.

    A filer reporting 1.0 of mezzanine against a residual of 48.056 would have had
    its 1.0 published while the sheet stayed 47.056 out, and
    `balance_sheet_balances` would still have reported balanced: it overwrites the
    total from assets and then compares it to itself, which is `x == x`.

    The two numbers agreeing is the only evidence that the residual IS mezzanine.
    Where they disagree, the residual is some other difference and the subtotal is
    reconciled the ordinary way.
    """

    def test_a_filers_mezzanine_that_is_not_the_residual_is_not_published_as_it(self) -> None:
        by_key = _build([
            _dp("canonical.bs.total_assets", 345.877),
            _dp("canonical.bs.total_liabilities", 330.838),
            # The filer says 1.0. The three subtotals imply 48.056.
            _dp("canonical.bs.mezzanine_equity", 1.0),
            _dp("canonical.bs.total_equity", -33.017),
            _dp("canonical.bs.total_liabilities_and_equity", 345.877),
        ])
        tl = by_key["canonical.bs.total_liabilities"]
        mezz = by_key.get("canonical.bs.mezzanine_equity")

        # The subtotal is back-solved instead of being preserved on the strength of
        # a mezzanine line that does not account for the gap.
        assert tl.values_by_period["FY25"] == pytest.approx(378.894, abs=0.01), (
            "with the filer's mezzanine inconsistent with the residual, the "
            f"subtotal must be reconciled the ordinary way; got "
            f"{tl.values_by_period['FY25']}"
        )
        if mezz is not None:
            assert mezz.values_by_period["FY25"] != pytest.approx(1.0, abs=0.01), (
                "published the filer's 1.0 of mezzanine as the reconciling figure "
                "while the sheet is 47.056 out of balance"
            )
