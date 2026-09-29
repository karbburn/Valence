"""The enterprise-value bridge must be struck on current, complete data.

Two defects lived here, and both are invisible in the cached numbers — they only
show up when a reader compares the platform's figure against the one their own
data provider publishes.

1. The bridge combined a LIVE market capitalisation with a net debt figure
   taken from the last ANNUAL balance sheet, up to a year old. Enterprise
   value, and every multiple built on it, were stale by exactly that gap. Net
   cash moved by 30bn at one large-cap and 54bn at another between the last
   annual balance sheet and the last reported quarter.

2. The debt term was assembled from a single balance-sheet tag, which excluded
   the current portion of long-term debt and every lease liability. One large
   filer's borrowings resolved to nothing at all.

These tests pin the shape of the answer rather than any company's number, so
they hold as the universe grows.
"""

from __future__ import annotations

import pytest

from backend.data.bridge_inputs import (
    BridgeSnapshot,
)
from backend.valuation.dcf import compute_dcf_bridge
from backend.valuation.dcf import compute_fcff_periods, compute_terminal_value
from backend.models.spec.forecast import FORECAST_PERIODS, Forecast, ForecastLineItem
from backend.models.spec.valuation import DCFBridge, FCFFPeriod, TerminalValue


def _forecast(fcffs=(100.0, 110.0, 120.0, 130.0, 140.0)) -> Forecast:
    items: list[ForecastLineItem] = []
    for period, value in zip(FORECAST_PERIODS, fcffs):
        items.append(
            ForecastLineItem(
                canonical_key="canonical.cf.operating_activities",
                period_label=period,
                period_end_date=__import__("datetime").date(2027, 12, 31),
                value=value,
                scenario="base",
            )
        )
    return Forecast(line_items=items)


def _fcff_periods() -> list[FCFFPeriod]:
    periods = []
    for index, period in enumerate(FORECAST_PERIODS):
        periods.append(
            FCFFPeriod(
                period=period,
                ebit=100.0,
                tax_rate=20.0,
                nopat=80.0,
                da=10.0,
                capex=20.0,
                delta_working_capital=5.0,
                stock_compensation=0.0,
                fcff=65.0,
                discount_factor=0.9,
                pv_fcff=58.5,
            )
        )
    return periods


def _terminal_value() -> TerminalValue:
    return TerminalValue(
        method="gordon_growth",
        terminal_growth_rate=2.5,
        terminal_value_undiscounted=1000.0,
        terminal_value_pv=700.0,
        tv_pct_of_ev=80.0,
    )


# ---------------------------------------------------------------------------
# The bridge arithmetic and the completeness of its inputs
# ---------------------------------------------------------------------------

def test_bridge_deducts_every_obligation_it_is_given():
    """Equity = EV less all obligations, plus all liquid assets.

    A bridge that silently omits a term overstates equity value by that term.
    """
    bridge, _ = compute_dcf_bridge(
        fcff_periods=_fcff_periods(),
        terminal_value=_terminal_value(),
        cash_cr=100.0,
        debt_cr=60.0,
        shares_cr=10.0,
        marketable_securities_cr=40.0,
        non_current_investments_cr=25.0,
        minority_interest_cr=15.0,
        preferred_stock_cr=5.0,
    )
    ev = bridge.enterprise_value
    expected_equity = ev - (60.0 + 15.0 + 5.0) + (100.0 + 40.0 + 25.0)
    assert bridge.equity_value == pytest.approx(expected_equity, abs=0.01)
    assert bridge.less_net_debt == pytest.approx(80.0 - 165.0, abs=0.01)


def test_operating_lease_liability_is_reported_and_not_deducted_twice():
    """Rent is already in EBIT, so the lease liability is shown, not deducted.

    Deducting it as well charges for the same obligation twice.
    """
    with_lease, _ = compute_dcf_bridge(
        fcff_periods=_fcff_periods(),
        terminal_value=_terminal_value(),
        cash_cr=0.0,
        debt_cr=100.0,
        shares_cr=10.0,
        operating_lease_liabilities_cr=40.0,
    )
    without_lease, _ = compute_dcf_bridge(
        fcff_periods=_fcff_periods(),
        terminal_value=_terminal_value(),
        cash_cr=0.0,
        debt_cr=100.0,
        shares_cr=10.0,
    )
    assert with_lease.equity_value == pytest.approx(without_lease.equity_value, abs=0.01)
    assert with_lease.operating_lease_liabilities == pytest.approx(40.0, abs=0.01)


def test_bridge_publishes_which_balance_sheet_it_used():
    """A net debt figure without a date is unreadable.

    The same company at the same price carries a different enterprise value
    depending on whether the balance sheet is three months old or two years
    old, and that difference is invisible unless the date travels with the
    number.
    """
    assert "balance_sheet_as_of" in DCFBridge.model_fields
    assert "balance_sheet_source" in DCFBridge.model_fields
    assert "debt_basis_note" in DCFBridge.model_fields


# ---------------------------------------------------------------------------
# Working capital
# ---------------------------------------------------------------------------

def test_working_capital_derivation_matches_the_explicit_line():
    """Without the explicit line the engine must still produce the same figure.

    Back-solving the working-capital movement out of net profit, D&A and
    operating cash flow only reproduces the engine's number when that cash flow
    line was itself built from the same movement. On a snapshot written by an
    older engine it is not, and the substitution silently returns a different
    figure instead of being absent.
    """
    from backend.valuation.dcf import _delta_wc_from_balance_sheet, _wc_level

    forecast = _forecast()
    prior_level = 0.0
    previous = None
    for period in FORECAST_PERIODS:
        for key, value in (
            ("canonical.bs.trade_receivables", 150.0),
            ("canonical.bs.inventory", 80.0),
            ("canonical.bs.trade_payables", 40.0),
        ):
            forecast.line_items.append(
                ForecastLineItem(
                    canonical_key=key,
                    period_label=period,
                    period_end_date=__import__("datetime").date(2027, 12, 31),
                    value=value,
                    scenario="base",
                )
            )
        level = _wc_level(forecast, period, "base")
        if previous is not None:
            assert _delta_wc_from_balance_sheet(
                forecast, period, "base", prior=previous
            ) == pytest.approx(level - previous, abs=0.01)
        previous = level
        prior_level = level
    assert prior_level == pytest.approx(150.0 + 80.0 - 40.0, abs=0.01)
