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
    SNAPSHOT_MAX_RATIO,
    SNAPSHOT_MIN_RATIO,
    BridgeSnapshot,
    _plausible,
    resolve_bridge_inputs,
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
# Snapshot plausibility
# ---------------------------------------------------------------------------

def test_a_wildly_moving_balance_is_refused():
    """A feed defect must not be allowed into the bridge.

    Statement feeds report in inconsistent units across listings; one came
    through a hundredfold away from the company's own accounts, which turned a
    3x multiple into a 790x one. A genuine quarter-on-quarter move in cash or
    debt stays well inside the band, so a wide band still catches the errors
    that matter.
    """
    assert not _plausible(20_299_000_000.0, 2_015_000_000.0)
    assert not _plausible(0.0, 1000.0)
    assert _plausible(950.0, 1000.0)
    assert _plausible(4000.0, 1000.0)
    assert SNAPSHOT_MAX_RATIO >= 4.0, "genuine debt issuance of several times must remain admissible"
    assert SNAPSHOT_MIN_RATIO <= 0.5


def test_a_statement_denominated_in_the_wrong_currency_is_refused():
    """A unit mismatch lands far outside the band, in either direction."""
    assert not _plausible(2_015_000_000.0, 2_015_000_000_000.0)   # 1000x too small
    assert not _plausible(2_015_000_000_000_000.0, 2_015_000_000.0)  # 1e6x too large


def test_no_snapshot_yields_a_reason_rather_than_a_silent_zero(monkeypatch):
    """A company with no reported balance sheet must not value at zero net debt."""
    import backend.data.bridge_inputs as module

    monkeypatch.setattr(
        module, "fetch_bridge_snapshot", lambda _cid: BridgeSnapshot()
    )
    snapshot, reason = module.resolve_bridge_inputs("any_us", {"total_debt": 0.0, "liquid_assets": 0.0})
    assert snapshot is None
    assert reason and "no reported balance sheet" in reason


def test_refused_terms_fall_back_to_the_filed_accounts(monkeypatch):
    """A bad line in a snapshot must not poison the good ones beside it.

    Validation is per term: a snapshot whose debt looks wrong does not make its
    cash wrong, and throwing the whole statement away because of one line
    discards the freshness that matters most.
    """
    import backend.data.bridge_inputs as module

    snapshot = BridgeSnapshot(
        as_of="2026-06-30",
        source="reported_quarter",
        terms={
            "cash_and_bank": 20_000.0,
            "marketable_securities": 40_000.0,
            "debt_non_current": 900_000.0,   # 90x the filed figure: refused
            "debt_current": 5_000.0,
        },
        total_debt=905_000.0,
        total_liquid_assets=60_000.0,
    )
    monkeypatch.setattr(module, "fetch_bridge_snapshot", lambda _cid: snapshot)

    resolved, note = module.resolve_bridge_inputs(
        "any_us",
        {
            "cash_and_bank": 18_000.0,
            "marketable_securities": 42_000.0,
            "non_current_investments": 0.0,
            "debt_non_current": 10_000.0,
            "debt_current": 5_000.0,
            "total_debt": 15_000.0,
            "liquid_assets": 60_000.0,
        },
    )
    assert resolved is not None
    # Cash and securities survived; the debt term did not.
    assert "cash_and_bank" in resolved.terms
    assert "debt_non_current" not in resolved.terms
    # Debt falls back to the FILED TOTAL, not to a partial sum of the surviving
    # components. A partial sum would understate the obligation by whatever the
    # refused piece was, overstating equity value by the same amount.
    assert resolved.total_debt == pytest.approx(15_000.0, abs=0.01)
    assert note and "filed accounts" in note


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
