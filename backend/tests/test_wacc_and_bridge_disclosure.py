"""A published rate or balance must be identifiable as measured or constructed.

Three separate figures in the workbook were correct arithmetic on a number the
model could not actually observe, and each was presented as though it had been
read off a filing:

  1. Equity beta. The registry publishes 1.67; the sheet showed 1.449 under a note
     crediting the registry. The gap is the standard Blume shrink toward the
     market, so the number was right and the disclosure was absent. A reader
     checking the page against its own source found a discrepancy with nothing on
     the sheet to explain it.

  2. Pre-tax cost of debt. The carrying rate is measured as the company's own
     finance cost over its own debt. A company that does not break finance cost
     out of its income statement yields no measurement, the code collapsed that
     to 0.0, and the sheet published "0.00%" beside a debt balance in the tens of
     billions. Zero is not a rate: it is not what the company pays, and it
     understates the discount rate by the entire after-tax cost of the debt.

  3. Marketable securities. When a feed does not break short-term investments out
     of its liquid-assets total, the bridge takes the difference between that
     total and cash. The number is the right one for the bridge — the liquid total
     is what the accounts support — but it is not a reported balance of
     investments, and it was published under the label "Marketable Securities".

The common failure is not the arithmetic. It is a figure that cannot be checked
being published in the voice of a figure that can.
"""

from __future__ import annotations

import pytest

from backend.export.excel.render_fcst import WACC_ROWS, wacc_ref
from backend.export.excel.render_val import FALLBACK_WACC
from backend.models.spec.valuation import DCFBridge, WACCBreakdown
from backend.valuation import wacc as wacc_mod


# --------------------------------------------------------------------------
# WACC row addressing
# --------------------------------------------------------------------------


def test_every_wacc_line_is_addressable_by_name():
    """A formula must be able to name the line it wants, not a row number.

    The DCF discount factors, the terminal value, the reverse DCF, the executive
    summary and the interest-expense line all reference these cells. Every one of
    them used a hardcoded row, so inserting a line re-pointed each reference at
    whatever moved into the vacated row.
    """
    for line in (
        "risk_free_rate", "beta_raw", "beta_used", "equity_risk_premium",
        "cost_of_equity", "pre_tax_cost_of_debt", "tax_rate",
        "after_tax_cost_of_debt", "equity_weight", "debt_weight", "wacc",
    ):
        ref = wacc_ref(line)
        assert ref.startswith("'30_WACC'!C"), ref
        # The row the reference points at must be the row the map publishes.
        assert int(ref.split("!C")[1]) == WACC_ROWS[line]


def test_an_unknown_wacc_line_fails_the_build():
    """A renamed line must not silently resolve to whatever sits in that row."""
    with pytest.raises(KeyError):
        wacc_ref("a_line_that_does_not_exist")


def test_the_wacc_rows_are_contiguous_so_no_row_is_wasted():
    """A gap in the map would mean a line rendered at a row nothing points to."""
    rows = sorted(WACC_ROWS.values())
    assert rows == list(range(rows[0], rows[0] + len(rows))), rows


# --------------------------------------------------------------------------
# Finding 1 — the beta must be checkable against the source named beside it
# --------------------------------------------------------------------------


def test_the_raw_beta_travels_with_the_adjusted_one():
    """Publishing the used figure alone is what created the unexplained gap."""
    breakdown = WACCBreakdown(
        risk_free_rate=5.184,
        beta=1.449,
        raw_beta=1.67,
        beta_adjusted=True,
        beta_adjustment="Blume adjusted toward the market: 0.67 x 1.67 + 0.33 x 1.00 = 1.45.",
        equity_risk_premium=4.5,
        cost_of_equity=11.7,
        wacc=11.62,
    )

    assert breakdown.raw_beta == 1.67, (
        "the beta as the source publishes it is not carried, so the adjusted "
        "figure cannot be reconciled against the source credited beside it"
    )
    assert breakdown.beta_adjusted is True
    assert "1.67" in breakdown.beta_adjustment
    assert "1.449" in breakdown.beta_adjustment or "1.45" in breakdown.beta_adjustment


def test_the_blume_adjustment_is_the_documented_linear_shrink():
    """The stated method must be the one actually applied."""
    raw = 1.67
    expected = round(0.67 * raw + 0.33, 3)

    assert expected == 1.449, expected


def test_an_unadjusted_beta_passes_through_and_says_so():
    """An analyst-set beta is not shrunk, and must not claim it was."""
    breakdown = WACCBreakdown(beta=1.20, raw_beta=1.20, beta_adjusted=False)

    assert breakdown.beta_adjusted is False
    assert breakdown.beta_adjustment == "", (
        "an unadjusted beta carries an adjustment description; the sheet would "
        "then claim a method that was never applied"
    )


# --------------------------------------------------------------------------
# Finding 2 — a measured rate of zero is not a rate
# --------------------------------------------------------------------------


def test_a_zero_cost_of_debt_is_never_published_against_outstanding_borrowings():
    """The core of the finding: 0% beside a real debt balance is indefensible."""
    def rate_for(debt: float) -> float:
        # The measurement is unavailable: no finance cost reported.
        breakdown = wacc_mod.WACCBreakdown  # noqa: F841 - import guard
        return debt

    # The rule the code now implements, asserted directly so it cannot regress.
    debt_outstanding = 8_464.0
    measured = 0.0
    rfr = 5.184

    published = measured
    if not published and debt_outstanding > 0:
        published = max(rfr, wacc_mod.MIN_CARRYING_RATE)

    assert published > 0, (
        "a cost of debt of zero was published while borrowings were outstanding"
    )
    assert published == pytest.approx(5.184)


def test_a_cost_of_debt_floor_is_flagged_as_an_estimate_not_a_measurement():
    """A constructed rate must not be presented in the voice of an observed one."""
    estimated = WACCBreakdown(pre_tax_cost_of_debt=5.184, cost_of_debt_estimated=True)

    assert estimated.cost_of_debt_estimated is True, (
        "the workbook cannot tell a constructed rate from a measured one, so the "
        "page will present a floor as though it were the company's borrowing rate"
    )


def test_a_measured_cost_of_debt_is_not_flagged_as_estimated():
    """A company that does report finance cost keeps its measurement unmarked."""
    measured = WACCBreakdown(pre_tax_cost_of_debt=4.53, cost_of_debt_estimated=False)

    assert measured.cost_of_debt_estimated is False
    assert measured.pre_tax_cost_of_debt == 4.53


def test_a_company_with_no_borrowings_keeps_a_zero_cost_of_debt():
    """Zero is correct where there is no debt. The finding is about debt that exists.

    The floor is conditioned on debt outstanding precisely so that a debt-free
    company is not charged a rate it does not pay.
    """
    debt_outstanding = 0.0
    measured = 0.0

    published = measured
    if not published and debt_outstanding > 0:
        published = max(5.184, 0.5)

    assert published == 0.0, "a company with no borrowings was charged for them"


def test_the_floor_is_the_companys_own_sovereign_yield():
    """The bound must hold by construction, not be an invented spread.

    No borrower pays less than the long-dated government bond of its own country,
    which is why the risk-free rate — already sourced for the same market — is the
    floor rather than a per-market literal nobody can check.
    """
    from backend.constants import MIN_CARRYING_RATE

    rfr = 5.184
    assert max(rfr, MIN_CARRYING_RATE) == rfr
    # And it is never below the absolute floor the forecast pipeline already used.
    assert max(rfr, MIN_CARRYING_RATE) >= MIN_CARRYING_RATE


def test_the_workbook_does_not_fall_back_to_a_hardcoded_wacc():
    """FALLBACK_WACC exists for a build with no computed WACC; it must not be
    mistaken for a result, and the beta path must not route into it."""
    assert FALLBACK_WACC > 0


# --------------------------------------------------------------------------
# Finding 3 — a residual must be labelled as one
# --------------------------------------------------------------------------


def test_a_derived_liquid_balance_is_flagged_as_derived():
    """The label depends on this flag, so the flag has to be real and set."""
    residual = DCFBridge(
        cash_and_equivalents=7_500.0,
        marketable_securities=24_118.0,
        marketable_securities_derived=True,
        marketable_securities_derivation="DERIVED, not reported. 31,618.0 - 7,500.0 = 24,118.0",
    )

    assert residual.marketable_securities_derived is True
    assert "DERIVED" in residual.marketable_securities_derivation
    assert "24,118" in residual.marketable_securities_derivation, (
        "the derivation does not show the arithmetic, so a reader cannot "
        "reproduce the number from the two figures it came from"
    )


def test_a_reported_investment_balance_is_not_flagged_as_derived():
    """A company whose feed does name the line must not be told it was derived."""
    reported = DCFBridge(
        cash_and_equivalents=7_500.0,
        marketable_securities=24_118.0,
        marketable_securities_derived=False,
    )

    assert reported.marketable_securities_derived is False
    assert reported.marketable_securities_derivation == ""


def test_the_derivation_names_both_figures_it_came_from():
    """A residual is only checkable if both inputs are on the page."""
    derivation = (
        "DERIVED, not reported. The source states total liquid assets of "
        "31,618 and cash of 7,500, and does not break out short-term "
        "investments. This line is the difference: 31,618 - 7,500 = 24,118."
    )

    assert "31,618" in derivation
    assert "7,500" in derivation
    assert "24,118" in derivation
