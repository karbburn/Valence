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


def test_mezzanine_equity_is_deducted_before_the_common_shareholder_is_told():
    """Mezzanine ranks ahead of common equity, so it leaves the bridge.

    It is redeemable preferred or redeemable noncontrolling interest: a real claim
    on the enterprise that common shareholders rank behind. The balance sheet
    started carrying the line and the bridge did not start deducting it, so Uxin's
    equity value was overstated by its filed 48,056.

    Minority interest and preferred stock were already deducted here. Mezzanine is
    the same claim class under a third name, and it was missed for the same reason
    the others were once: a list of obligations nobody re-read when the taxonomy
    gained a line.
    """
    per = FCFFPeriod(period="FY30", ebit=0.0, tax_rate=0.0, nopat=0.0, da=0.0,
                     capex=0.0, delta_working_capital=0.0, fcff=0.0,
                     discount_factor=1.0, pv_fcff=0.0)
    tv = TerminalValue(method="gordon_growth", terminal_growth_rate=0.0,
                       final_year_fcff=0.0, terminal_value_undiscounted=0.0,
                       final_year_ebitda=0.0, terminal_value_pv=0.0)
    base = dict(fcff_periods=[per], terminal_value=tv, cash_cr=0.0, debt_cr=0.0,
                shares_cr=100.0, marketable_securities_cr=0.0,
                non_current_investments_cr=0.0, minority_interest_cr=0.0,
                preferred_stock_cr=0.0)

    without = compute_dcf_bridge(**base)[0]
    with_mezz = compute_dcf_bridge(**base, mezzanine_equity_cr=48_056.0)[0]

    assert without.equity_value == pytest.approx(with_mezz.equity_value + 48_056.0), (
        "mezzanine equity was not deducted from equity value"
    )
    assert with_mezz.implied_share_price == pytest.approx(
        without.implied_share_price - 480.56, abs=0.01
    )
    assert with_mezz.mezzanine_equity == pytest.approx(48_056.0)
    # And it must not also land in debt, which would charge it twice.
    assert with_mezz.total_debt == without.total_debt


def test_one_declaration_of_what_ranks_ahead_of_common_equity():
    """The claim list is stated once, and every consumer reads that one copy.

    Minority interest, preferred stock and mezzanine equity each had to be added to
    three separate places -- the bridge's arithmetic, the workbook's bridge row, and
    the workbook self-check's independent re-derivation of net debt. Mezzanine was
    missed by all three, and missed by the accounting check as well, so Uxin's equity
    value was overstated by its filed 48,056 and nothing went red.

    The self-check is the one that matters for this test. It exists to catch a
    bridge that does not reconcile, so re-deriving its input from a separately
    maintained list made it a check that agrees with a wrong answer -- and did,
    because the omission was present in both places at once.

    So this asserts the property rather than any one company's number: a claim
    added to the declaration is picked up everywhere, with no second edit.
    """
    from backend.valuation.claims import CLAIMS_AHEAD_OF_COMMON_EQUITY, claims_label

    fields = {c.bridge_field for c in CLAIMS_AHEAD_OF_COMMON_EQUITY}
    keys = {c.canonical_key for c in CLAIMS_AHEAD_OF_COMMON_EQUITY}

    # The three that were each missed at least once. Mezzanine is the one that cost
    # a real filer 48,056.
    assert {"minority_interest", "preferred_stock", "mezzanine_equity"} <= fields
    assert {"canonical.bs.minority_interest",
            "canonical.bs.preferred_stock",
            "canonical.bs.mezzanine_equity"} <= keys

    # No duplicates in either space, which would silently double-charge a claim.
    assert len(fields) == len(CLAIMS_AHEAD_OF_COMMON_EQUITY)
    assert len(keys) == len(CLAIMS_AHEAD_OF_COMMON_EQUITY)

    # Every declared bridge field is an actual field on DCFBridge. Without this, a
    # renamed field would be read as absent and silently contribute zero.
    assert all(c.bridge_field in DCFBridge.model_fields for c in CLAIMS_AHEAD_OF_COMMON_EQUITY)

    assert "Mezzanine" in claims_label()


def test_a_claim_added_to_the_declaration_is_picked_up_with_no_second_edit(monkeypatch):
    """Adding a claim class must require exactly one edit: the declaration.

    This is the property the previous shape did not have. Mezzanine equity was
    missing from the bridge, the workbook row and the workbook self-check, so Uxin's
    equity value was overstated by its filed 48,056 and the self-check -- whose whole
    job is catching a bridge that does not reconcile -- agreed with the wrong answer,
    because the omission sat in both places at once.

    A shape assertion cannot catch that: the list would still contain mezzanine and
    still look right. So this adds a claim nobody has written code for and asserts
    it changes the bridge's arithmetic on its own. If a consumer ever hardcodes a
    field again, this turns red.
    """
    from backend.valuation import claims

    per = FCFFPeriod(period="FY30", ebit=0.0, tax_rate=0.0, nopat=0.0, da=0.0,
                     capex=0.0, delta_working_capital=0.0, fcff=0.0,
                     discount_factor=1.0, pv_fcff=0.0)
    tv = TerminalValue(method="gordon_growth", terminal_growth_rate=0.0,
                       final_year_fcff=0.0, terminal_value_undiscounted=0.0,
                       final_year_ebitda=0.0, terminal_value_pv=0.0)

    def bridge_with(**kw):
        return compute_dcf_bridge(
            fcff_periods=[per], terminal_value=tv, cash_cr=0.0, debt_cr=0.0,
            shares_cr=100.0, marketable_securities_cr=0.0,
            non_current_investments_cr=0.0, minority_interest_cr=0.0,
            preferred_stock_cr=0.0, **kw,
        )[0]

    before = bridge_with()
    baseline = before.equity_value

    # A fourth claim class, carrying an amount the bridge was never told about. The
    # point is that nobody wrote `claims_warranty_cr` anywhere; the declaration is
    # the only thing that changed.
    warrant = claims.ClaimAheadOfCommonEquity(
        "canonical.bs.warrant_liability", "warrant_liability", "Warrant Liability"
    )
    monkeypatch.setattr(
        claims, "CLAIMS_AHEAD_OF_COMMON_EQUITY",
        claims.CLAIMS_AHEAD_OF_COMMON_EQUITY + (warrant,),
    )

    after = bridge_with(warrant_liability_cr=7_500.0)
    assert after.equity_value == pytest.approx(baseline - 7_500.0), (
        "a claim class added to the declaration did not reach the bridge, so a "
        "reader told there is a claim ranking ahead of them would not be charged "
        "for it"
    )

    # And the charge must be PUBLISHED, not merely applied. This is the half that was
    # actually broken: `warrant_liability` has no named field on DCFBridge, and every
    # reader -- the workbook's bridge row, the export self-check that exists to catch
    # a bridge that does not reconcile -- read named fields only. So the arithmetic
    # would have been right and every published figure would have said zero.
    assert after.other_claims == pytest.approx({"warrant_liability": 7_500.0}), (
        "the bridge charged a claim it did not publish"
    )

    # Every consumer resolves through the one helper, so none of them can read zero
    # for a charge the bridge genuinely applied.
    assert claims.claims_total(after) == pytest.approx(7_500.0)
    assert claims.resolve_claim(after, warrant) == pytest.approx(7_500.0)

    # ...and a named claim still resolves from its own field, not the channel, so it
    # is not counted twice. Built with the declaration restored, because the bridge
    # now refuses to run at all when a declared claim arrives with no amount -- which
    # is the other half of the fix and is asserted separately below.
    monkeypatch.undo()
    named = claims.ClaimAheadOfCommonEquity(
        "canonical.bs.mezzanine_equity", "mezzanine_equity", "Mezzanine Equity"
    )
    me = bridge_with(mezzanine_equity_cr=100.0)
    assert claims.resolve_claim(me, named) == pytest.approx(100.0)
    assert "mezzanine_equity" not in (me.other_claims or {}), (
        "a claim with a named field must not also sit in the open channel, or every "
        "consumer that sums the two would charge for it twice"
    )


def test_a_declared_claim_with_no_amount_is_refused_rather_than_deducted_at_zero(monkeypatch):
    """Silence is the failure mode here, not a wrong number.

    When mezzanine was missing from the bridge, nothing raised and nothing looked
    wrong: the claim existed in the taxonomy, the arithmetic ran, and the reader was
    simply never charged. A default of zero reproduces that exactly, one refactor
    away. So a declared claim that arrives with no amount stops the build.

    This also means the pipeline must supply every claim the declaration lists. That
    is the intended pressure -- adding a claim class now fails loudly on the first
    company that does not carry it, instead of quietly understating every one.
    """
    from backend.valuation import claims

    per = FCFFPeriod(period="FY30", ebit=0.0, tax_rate=0.0, nopat=0.0, da=0.0,
                     capex=0.0, delta_working_capital=0.0, fcff=0.0,
                     discount_factor=1.0, pv_fcff=0.0)
    tv = TerminalValue(method="gordon_growth", terminal_growth_rate=0.0,
                       final_year_fcff=0.0, terminal_value_undiscounted=0.0,
                       final_year_ebitda=0.0, terminal_value_pv=0.0)

    extra = claims.ClaimAheadOfCommonEquity(
        "canonical.bs.warrant_liability", "warrant_liability", "Warrant Liability"
    )
    monkeypatch.setattr(
        claims, "CLAIMS_AHEAD_OF_COMMON_EQUITY",
        claims.CLAIMS_AHEAD_OF_COMMON_EQUITY + (extra,),
    )

    common = dict(fcff_periods=[per], terminal_value=tv, cash_cr=0.0, debt_cr=0.0,
                  shares_cr=100.0, marketable_securities_cr=0.0,
                  non_current_investments_cr=0.0, minority_interest_cr=0.0,
                  preferred_stock_cr=0.0)

    with pytest.raises(ValueError, match="warrant_liability"):
        compute_dcf_bridge(**common)

    # And an amount matching no declared claim is refused too, so a typo cannot
    # deduct nothing while appearing to have been charged.
    with pytest.raises(ValueError, match="no declared claim"):
        compute_dcf_bridge(**common, mezzanine_equity_cr=0.0,
                           warrant_liabilty_cr=5_000.0)


def test_no_consumer_keeps_its_own_enumeration_of_claims():
    """The workbook and its self-check must not name a claim class at all.

    This asserts on source text, which is normally the wrong thing to do. Here it is
    the property itself: these two files must contain no enumeration of what ranks
    ahead of common equity, so there is nothing for them to fall behind on.

    The mutation run is why. Restoring a hardcoded list inside the export self-check
    -- the one whose entire job is catching a bridge that does not reconcile -- left
    the whole suite green, because both of my new tests were on the bridge and
    neither could see it. That is precisely the failure mode the module docstring
    describes: a check that agrees with a wrong answer.

    So this refuses the shape rather than asserting a number. If a claim class ever
    needs naming here, the failure says why instead of passing quietly.
    """
    import re
    from pathlib import Path

    from backend.valuation.claims import CLAIMS_AHEAD_OF_COMMON_EQUITY

    root = Path(__file__).resolve().parents[2]
    fields = [c.bridge_field for c in CLAIMS_AHEAD_OF_COMMON_EQUITY]

    for rel in ("backend/export/excel/render_val.py",
                "backend/export/excel/self_check.py"):
        # Comments may name a claim to explain it; code may not.
        code = re.sub(r"#.*", "", (root / rel).read_text(encoding="utf-8"))
        for f in fields:
            offenders = [ln.strip() for ln in code.splitlines()
                         if re.search(r"\b" + re.escape(f) + r"\b", ln)]
            assert not offenders, (
                f"{rel} names the claim '{f}' in code again:\n  "
                + "\n  ".join(offenders)
                + "\nCall backend.valuation.claims.claims_total() instead."
            )
