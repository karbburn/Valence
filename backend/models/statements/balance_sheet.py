from __future__ import annotations

import logging

from datetime import date
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from backend.data.store import RawDatapoint
from backend.models.spec.historicals import REPORTED_STATUSES
from backend.models.statements.selector import select_primary_datapoints
from backend.normalization.taxonomy.models import CanonicalDatapoint

# Statuses a SOURCE published, as distinct from one this engine computed. Both
# `reported` and `estimated` qualify: a figure flagged as unverified is still the
# source's own number, and the reconciliation needs something to anchor against.
# Only `derived` and `analyst_adjusted` are ours, and a derived subtotal is never
# an authority for anything.
FILER_PUBLISHED_STATUSES = REPORTED_STATUSES | {"estimated"}

logger = logging.getLogger(__name__)

CategoryType = Literal[
    "non_current_assets",
    "current_assets",
    "equity",
    "non_current_liabilities",
    "current_liabilities",
    "summary",
]

BS_LINE_ITEM_CONFIG: List[tuple[str, str, CategoryType]] = [
    # Non-Current Assets
    ("canonical.bs.ppe", "Property, Plant & Equipment (Net Block)", "non_current_assets"),
    ("canonical.bs.cwip", "Capital Work-in-Progress", "non_current_assets"),
    ("canonical.bs.goodwill", "Goodwill", "non_current_assets"),
    ("canonical.bs.intangible_assets", "Intangible Assets", "non_current_assets"),
    ("canonical.bs.non_current_investments", "Non-Current Investments", "non_current_assets"),
    ("canonical.bs.deferred_tax_assets", "Deferred Income Tax Assets", "non_current_assets"),
    ("canonical.bs.income_tax_assets", "Income Tax Assets", "non_current_assets"),
    ("canonical.bs.other_non_current_assets", "Other Non-Current Assets", "non_current_assets"),
    ("canonical.bs.total_non_current_assets", "Total Non-Current Assets", "non_current_assets"),

    # Current Assets
    ("canonical.bs.current_investments", "Current Investments", "current_assets"),
    ("canonical.bs.trade_receivables", "Trade Receivables", "current_assets"),
    ("canonical.bs.vendor_non_trade_receivables", "Vendor Non-Trade Receivables", "current_assets"),
    ("canonical.bs.unbilled_revenue", "Unbilled Revenue", "current_assets"),
    ("canonical.bs.inventory", "Inventory", "current_assets"),
    ("canonical.bs.cash_and_bank", "Cash & Cash Equivalents", "current_assets"),
    ("canonical.bs.prepayments_other_current_assets", "Prepayments & Other Current Assets", "current_assets"),
    ("canonical.bs.total_current_assets", "Total Current Assets", "current_assets"),

    # Total Assets
    ("canonical.bs.total_assets", "Total Assets", "summary"),

    # Equity
    ("canonical.bs.equity_capital", "Equity Share Capital", "equity"),
    ("canonical.bs.retained_earnings", "Retained Earnings", "equity"),
    ("canonical.bs.other_reserves", "Other Reserves", "equity"),
    ("canonical.bs.mezzanine_equity", "Mezzanine Equity", "equity"),
    ("canonical.bs.minority_interest", "Minority / Non-Controlling Interest", "equity"),
    ("canonical.bs.preferred_stock", "Preference Share Capital", "equity"),
    ("canonical.bs.total_equity", "Total Equity", "equity"),

    # Non-Current Liabilities
    ("canonical.bs.borrowings", "Borrowings (Non-Current)", "non_current_liabilities"),
    ("canonical.bs.lease_liabilities", "Lease Liabilities", "non_current_liabilities"),
    ("canonical.bs.other_non_current_liabilities", "Other Non-Current Liabilities", "non_current_liabilities"),
    ("canonical.bs.total_non_current_liabilities", "Total Non-Current Liabilities", "non_current_liabilities"),

    # Current Liabilities
    # Short-term borrowings are a SEPARATE line from non-current borrowings, and
    # they include the current portion of long-term debt. Rolling them into one
    # figure, or omitting them, understates total debt in the EV -> equity
    # bridge by the whole current maturity.
    ("canonical.bs.short_term_borrowings", "Short-Term Borrowings & Current Portion of Long-Term Debt", "current_liabilities"),
    ("canonical.bs.operating_lease_liabilities", "Operating Lease Liabilities", "current_liabilities"),
    ("canonical.bs.finance_lease_liabilities", "Finance / Capital Lease Liabilities", "non_current_liabilities"),

    # Current Liabilities
    ("canonical.bs.trade_payables", "Trade Payables", "current_liabilities"),
    ("canonical.bs.unearned_revenue", "Unearned Revenue", "current_liabilities"),
    ("canonical.bs.provisions", "Provisions", "current_liabilities"),
    ("canonical.bs.other_current_liabilities", "Other Current Liabilities", "current_liabilities"),
    ("canonical.bs.total_current_liabilities", "Total Current Liabilities", "current_liabilities"),

    # Total Liabilities & Equity
    ("canonical.bs.total_liabilities", "Total Liabilities", "summary"),
    ("canonical.bs.total_liabilities_and_equity", "Total Liabilities & Equity", "summary"),
]


class BalanceSheetLineItem(BaseModel):
    canonical_key: str
    display_label: str
    category: CategoryType
    values_by_period: Dict[str, float] = Field(default_factory=dict)
    currency: str = "INR"
    units: str = "crores"
    lineage_ids_by_period: Dict[str, List[str]] = Field(default_factory=dict)
    # The period end each value was FILED for, keyed by period label.
    #
    # This is provenance and not decoration. A filer's fiscal year does not end on
    # the calendar day a fiscal calendar implies: NVIDIA's FY2026 ended 25 January
    # 2026, the last Sunday of January, not the 31st the month/day default would
    # produce. Substituting the calendar day published a balance sheet dated six
    # days after the quarter closed, which is the kind of discrepancy that reads as
    # a data error to anyone holding the filing. Absent for periods where nothing
    # was reported, in which case the caller falls back rather than inventing one.
    period_end_dates_by_period: Dict[str, date] = Field(default_factory=dict)
    # Whether each period's value was READ from a filing or COMPUTED, keyed by
    # period label, with the formula when it was computed.
    #
    # This is the difference between a figure the filer published and one this
    # engine worked out, and 8.7% of the canonical datapoints are the second kind:
    # gross profit, EBITDA, subtotals, catch-alls. All of them used to arrive at the
    # model specification, the snapshot, the workbook and the site labelled
    # `reported` with no rule, because the spec builder hardcoded that status for
    # every line except EBITDA. A reader therefore had no way to tell which numbers
    # came out of a filing, on a product whose whole claim is that every figure
    # matches one — and the check written to catch it, `historicals_are_reported`,
    # could not fail, because the status it read had already been overwritten.
    status_by_period: Dict[str, str] = Field(default_factory=dict)
    derivation_rule_by_period: Dict[str, str] = Field(default_factory=dict)


class BalanceSheet(BaseModel):
    company_id: str
    periods: List[str]
    line_items: List[BalanceSheetLineItem]
    is_balanced_by_period: Dict[str, bool] = Field(default_factory=dict)
    imbalance_amount_by_period: Dict[str, float] = Field(default_factory=dict)

    def get_line_item(self, canonical_key: str) -> Optional[BalanceSheetLineItem]:
        for item in self.line_items:
            if item.canonical_key == canonical_key:
                return item
        return None

    def get_value(self, canonical_key: str, period: str) -> Optional[float]:
        item = self.get_line_item(canonical_key)
        if item:
            return item.values_by_period.get(period)
        return None


def assemble_balance_sheet(
    canonical_datapoints: list[CanonicalDatapoint],
    target_periods: list[str] | None = None,
    raw_datapoints_map: Dict[str, RawDatapoint] | None = None,
) -> BalanceSheet:
    """Assembles structured Balance Sheet and validates Assets = Liabilities + Equity."""
    if not canonical_datapoints:
        raise ValueError("No canonical datapoints provided for balance sheet assembly.")

    company_id = canonical_datapoints[0].company_id
    bs_dps = [d for d in canonical_datapoints if d.canonical_key.startswith("canonical.bs.")]

    all_periods = sorted(set(d.period_label for d in bs_dps), key=lambda p: (len(p), p))
    if target_periods:
        periods = [p for p in target_periods if p in all_periods]
    else:
        periods = all_periods

    dp_map = select_primary_datapoints(bs_dps, "bs", raw_datapoints_map=raw_datapoints_map)

    items: List[BalanceSheetLineItem] = []

    for c_key, label, cat in BS_LINE_ITEM_CONFIG:
        values: Dict[str, float] = {}
        lineage: Dict[str, List[str]] = {}
        period_ends: Dict[str, date] = {}
        status: Dict[str, str] = {}
        rules: Dict[str, str] = {}
        curr = "INR"
        un = "crores"

        for p in periods:
            dp = dp_map.get((c_key, p))
            if dp is not None:
                values[p] = dp.value
                lineage[p] = dp.source_datapoint_ids
                period_ends[p] = dp.period_end_date
                status[p] = getattr(dp, "status", "reported") or "reported"
                rule = getattr(dp, "derivation_rule", None)
                if rule:
                    rules[p] = rule
                curr = dp.currency
                un = dp.units

        if values:
            items.append(
                BalanceSheetLineItem(
                    canonical_key=c_key,
                    display_label=label,
                    category=cat,
                    values_by_period=values,
                    currency=curr,
                    units=un,
                    lineage_ids_by_period=lineage,
                    period_end_dates_by_period=period_ends,
                    status_by_period=status,
                    derivation_rule_by_period=rules,
                )
            )

    # Perform balance sheet equality checks
    is_balanced: Dict[str, bool] = {}
    imbalance: Dict[str, float] = {}

    def _item_for(key: str) -> Optional[BalanceSheetLineItem]:
        return next((i for i in items if i.canonical_key == key), None)

    def _add_derived(key: str, label: str, values: Dict[str, float], template: BalanceSheetLineItem) -> None:
        """Insert a derived line item, preserving currency/units/lineage."""
        items.append(
            BalanceSheetLineItem(
                canonical_key=key,
                display_label=label,
                category="summary",
                values_by_period=values,
                currency=template.currency,
                units=template.units,
                lineage_ids_by_period=dict(template.lineage_ids_by_period),
                period_end_dates_by_period=dict(template.period_end_dates_by_period),
                  # Recorded rather than left unset. Left unset, the reconciliation
                  # treated a subtotal this engine computed as one a filer
                  # published, which is the distinction the step turns on.
                  status_by_period={p: "derived" for p in values},
            )
        )

    # Derive the totals a filer omits but the roll-forward needs.
    #
    # Most EDGAR/screener exports carry Total Assets and Total Liabilities &
    # Equity but neither Total Liabilities nor Total Equity. Without them the
    # forecast equity roll-forward would start from a ZERO opening base, which
    # silently deletes the whole equity account (a 93% error on a steelmaker)
    # while the balance sheet still "balances" because cash is the plug.
    assets_ref = _item_for("canonical.bs.total_assets")
    ncl = _item_for("canonical.bs.total_non_current_liabilities")
    cl = _item_for("canonical.bs.total_current_liabilities")
    borrowings = _item_for("canonical.bs.borrowings")
    leases = _item_for("canonical.bs.lease_liabilities")
    other_ncl = _item_for("canonical.bs.other_non_current_liabilities")
    trade_pay = _item_for("canonical.bs.trade_payables")
    unearned = _item_for("canonical.bs.unearned_revenue")
    provisions = _item_for("canonical.bs.provisions")
    other_cl = _item_for("canonical.bs.other_current_liabilities")

    if assets_ref and not _item_for("canonical.bs.total_liabilities"):
        if ncl and cl:
            values = {
                p: (ncl.values_by_period.get(p, 0.0) + cl.values_by_period.get(p, 0.0))
                for p in periods
                if p in ncl.values_by_period or p in cl.values_by_period
            }
            _add_derived("canonical.bs.total_liabilities", "Total Liabilities", values, assets_ref)
        else:
            # Sum the individual liability lines we do have.
            components = [borrowings, leases, other_ncl, trade_pay, unearned, provisions, other_cl]
            components = [c for c in components if c is not None]
            if components:
                values = {}
                for p in periods:
                    total = sum(c.values_by_period.get(p, 0.0) for c in components)
                    if any(p in c.values_by_period for c in components):
                        values[p] = total
                if values:
                    _add_derived("canonical.bs.total_liabilities", "Total Liabilities", values, assets_ref)

    if assets_ref and not _item_for("canonical.bs.total_equity"):
        total_liabilities = _item_for("canonical.bs.total_liabilities")
        if total_liabilities:
            values = {}
            for p in periods:
                ta = assets_ref.values_by_period.get(p)
                tl = total_liabilities.values_by_period.get(p)
                if ta is not None and tl is not None:
                    values[p] = ta - tl
            if values:
                _add_derived("canonical.bs.total_equity", "Total Equity", values, assets_ref)
        else:
            # No liability detail at all: fall back to the equity components.
            equity_capital = _item_for("canonical.bs.equity_capital")
            retained = _item_for("canonical.bs.retained_earnings")
            reserves = _item_for("canonical.bs.other_reserves")
            components = [c for c in (equity_capital, retained, reserves) if c is not None]
            if components:
                values = {}
                for p in periods:
                    if any(p in c.values_by_period for c in components):
                        values[p] = sum(c.values_by_period.get(p, 0.0) for c in components)
                if values:
                    _add_derived("canonical.bs.total_equity", "Total Equity", values, assets_ref)

    # The right-hand side of the balance sheet must add to the filer's own subtotal.
    #
    # Both halves are assembled here from components, because a screener export often
    # prints total assets and total-liabilities-and-equity but neither total
    # liabilities nor total equity. The two component sums then need not agree with
    # the filer's subtotal, and when they do not, the balance sheet does not foot
    # while every individual figure is a number the filer published. Tata Consultancy
    # came to liabilities 73,298 plus equity 108,562 = 181,860 against filed assets
    # of 174,162, a 7,698 hole; Larsen & Toubro was out by 69,456.
    #
    # Equity is the side kept. It is three lines with unambiguous captions —
    # share capital, retained earnings, reserves — read straight from the filer,
    # where the liability side is assembled from seven rows of a third party's
    # grouping, where an overlap between a subtotal and its components is exactly
    # what a 7,698 duplication looks like. So the filer's own equity stands and the
    # liability total is corrected to the filer's arithmetic, which also means the
    # correction lands on a figure nothing in the valuation reads: net debt is built
    # from the specific borrowing lines, not from this total.
    # The authority is the filer's OWN subtotal, and which one depends on the year.
    # Total-liabilities-and-equity is not always one: a filer that prints neither
    # total liabilities nor total equity has TLE derived here as liabilities plus
    # equity, so it equals the thing being tested and can never disagree with it.
    # ONGC's FY24 came to 382,374 + 339,069 = 721,443 against filed assets of 741,998,
    # a 20,555 hole that a TLE-anchored correction is structurally blind to. So the
    # anchor is whichever subtotal the FILER reported, and a derived subtotal is not
    # an authority for anything.
    _tle = _item_for("canonical.bs.total_liabilities_and_equity")
    _ta = _item_for("canonical.bs.total_assets")
    _tl = _item_for("canonical.bs.total_liabilities")
    _te = _item_for("canonical.bs.total_equity")

    def _reported(item, p: str) -> Optional[float]:
        """A period's value, but only if the SOURCE published it, not a derivation.

        "Published" rather than "reported" deliberately. `estimated` is a figure a
        reader published and knows to be unverified -- a hand-entered fixture, a
        figure a source flagged -- and it is still the source's own number, so it is
        a legitimate anchor for reconciliation.

        Excluding it here was a way of losing the anchor entirely: once the fixture
        companies' lines were marked `estimated`, no subtotal and no total-assets
        qualified, `authority` came back None, the loop skipped every period, and
        six balance sheets stopped footing. The check asks "did this come from a
        derivation?", and the answer for `estimated` is no.
        """
        if item is None:
            return None
        # No default. This used to default to "reported", so a line whose status
        # was never recorded counted as filer-published. `_add_derived` did not
        # write `status_by_period`, so every subtotal this engine derived was
        # promoted to a filed figure at the moment it was tested -- and the
        # mezzanine guard reads this same predicate.
        #
        # Absence of a recorded status is absence of evidence that a source
        # published the figure. It does not default to yes.
        if item.status_by_period.get(p) not in FILER_PUBLISHED_STATUSES:
            return None
        v = item.values_by_period.get(p)
        return float(v) if v is not None else None

    if _tl and _te:
        _corrected: Dict[str, float] = {}
        _mezzanine: Dict[str, float] = {}
        # Periods whose filed mezzanine the back-solve has already absorbed. The
        # line is zeroed for those periods, or the amount is counted twice.
        _mezz_absorbed: set = set()
        # The mezzanine the FILER published, if any. The filer knows whether it has
        # redeemable preferred or redeemable noncontrolling interest; the residual
        # only means "mezzanine" when they have told us so.
        _mezz_item = _item_for("canonical.bs.mezzanine_equity")
        mezzanine_values = {
            p: float(v) for p, v in (_mezz_item.values_by_period or {}).items() if v
        } if _mezz_item is not None else {}
        for p in periods:
            te_v = _te.values_by_period.get(p)
            if te_v is None:
                continue
            authority = _reported(_tle, p)
            if authority is None:
                authority = _reported(_ta, p)
            if authority is None:
                continue
            built = float(_tl.values_by_period.get(p, 0.0)) + float(te_v)
            gap = built - authority
            if abs(gap) <= max(abs(authority) * 0.001, 1.0):
                continue

            # Two different things produce a subtotal that does not foot, and
            # they must not get the same response.
            #
            # (a) The assembled liability components did not reach the filer's own
            #     total. Back-solving the subtotal is the right correction, and was
            #     the only response before this.
            #
            # (b) The filer prints a THIRD claim class between liabilities and
            #     equity -- mezzanine equity: redeemable preferred, redeemable
            #     noncontrolling interest. Uxin filed liabilities 330,838, mezzanine
            #     48,056 and a shareholders' deficit of -33,017. Back-solving
            #     produced total_liabilities of 378,894, a 14.5% overstatement of
            #     a figure the filer had reported exactly, with the mezzanine
            #     silently inside it and no line anywhere showing it went there.
            #
            #     That is worse than the gap: the balance sheet still foots and
            #     total assets is untouched, so no gate complains, and the only
            #     symptom is a published liabilities figure that no filer prints.
            #
            # So when the filer reported the subtotal AND prints a mezzanine claim for
            # the residual to be, the subtotal is kept as reported and the residual
            # is named.
            #
            # The mezzanine claim has to actually exist. An earlier version of this
            # protected any reported subtotal, and that misfired immediately: TCS
            # does not have mezzanine, its hand-entered fixture simply does not foot
            # (liabilities 73,298 + equity 108,562 against assets 174,162), so the
            # residual was published as a "-7,698 mezzanine equity" -- inventing a
            # claim class to explain a data-entry error. The gate caught it, which
            # is what the gate is for.
            #
            # So the default stays the original back-solve. Only a filer that
            # publishes redeemable preferred or redeemable noncontrolling interest
            # gets the subtotal preserved, because only then is the residual known
            # to be mezzanine rather than an unexplained difference.
            filed_mezz = mezzanine_values.get(p)
            if _reported(_tl, p) is not None and filed_mezz is not None:
                # Only when the filer's own figure IS the residual.
                #
                # Requiring agreement is the whole point. The branch used to fire on
                # the mere EXISTENCE of a mezzanine line, so a filer reporting 1.0
                # against an implied 48.056 had its 1.0 published while the sheet
                # stayed 47.056 out -- and balance_sheet_balances still reported
                # balanced, because it overwrites the total from assets and then
                # compares it to itself.
                residual = authority - built
                if abs(filed_mezz - residual) <= max(abs(residual) * 0.001, 1.0):
                    _mezzanine[p] = residual
                    continue
                logger.warning(
                    "%s %s: filer reports %.1f of mezzanine equity but the "
                    "balance-sheet subtotals imply %.1f. The difference is not "
                    "assumed to be mezzanine; the subtotal is reconciled as for any "
                    "other unexplained gap and the mezzanine line is zeroed for this "
                    "period, because the back-solve already absorbs it.",
                    company_id, p, filed_mezz, residual,
                )
                _mezz_absorbed.add(p)
            elif filed_mezz is not None:
                # The filer prints mezzanine but did NOT publish a total-liabilities
                # subtotal, so this period takes the back-solve.
                #
                # The back-solve sets liabilities to (assets side total less equity),
                # and that total INCLUDES the mezzanine claim. Leaving the filed
                # mezzanine line populated as well counts the same claim twice: once
                # hidden inside liabilities and once on its own row. The sheet then
                # fails to foot by exactly the mezzanine amount -- 48,056 on Uxin's
                # real figures -- while every individual line looks defensible.
                #
                # The same applies when the filed figure and the residual disagree,
                # which is why both paths mark the line absorbed and the zeroing below
                # handles them together.
                _mezz_absorbed.add(p)
            _corrected[p] = authority - float(te_v)
        if _mezzanine:
            # The filer already published this figure under its own name, so it is
            # not modelled -- it is passed through. It is a real claim on the
            # enterprise sitting ahead of common equity, and folding it into
            # liabilities would overstate them and understate equity.
            _mezzanine_item = _item_for("canonical.bs.mezzanine_equity")
            if _mezzanine_item is None:
                _add_derived(
                    "canonical.bs.mezzanine_equity",
                    "Mezzanine Equity",
                    _mezzanine,
                    _tle,
                )
            else:
                _mezzanine_item.values_by_period.update(_mezzanine)
        # Applied here, not inside the branch above: when the filer's mezzanine
        # disagrees with the residual we fall back to the back-solve and
        # _mezzanine is empty, so a block nested in that branch would never run.
        _mezz_item_now = _item_for("canonical.bs.mezzanine_equity")
        if _mezz_absorbed and _mezz_item_now is not None:
            _mezz_item_now.values_by_period.update({p: 0.0 for p in _mezz_absorbed})
            _mezz_item_now.status_by_period.update(
                {p: "derived" for p in _mezz_absorbed}
            )
        if _corrected:
            _tl.values_by_period.update(_corrected)
            _tl.status_by_period.update({p: "derived" for p in _corrected})
            _tl.derivation_rule_by_period.update({
                p: ("total_liabilities = the filer's own balance-sheet subtotal less "
                    "the filer's own total equity; the assembled liability "
                    "components did not reach it")
                for p in _corrected
            })

    # Reconcile Total Assets from sum of Non-Current Assets and Current Assets
    nca_item = _item_for("canonical.bs.total_non_current_assets")
    ca_item = _item_for("canonical.bs.total_current_assets")
    assets_item = _item_for("canonical.bs.total_assets")
    ca_item = next((i for i in items if i.canonical_key == "canonical.bs.total_current_assets"), None)
    assets_item = next((i for i in items if i.canonical_key == "canonical.bs.total_assets"), None)

    if nca_item and ca_item:
        reconciled_assets_vals = {}
        for p in periods:
            nca_val = nca_item.values_by_period.get(p, 0.0)
            ca_val = ca_item.values_by_period.get(p, 0.0)
            reconciled_assets_vals[p] = nca_val + ca_val
        
        if assets_item:
            assets_item.values_by_period = reconciled_assets_vals
        else:
            assets_item = BalanceSheetLineItem(
                canonical_key="canonical.bs.total_assets",
                display_label="Total Assets",
                category="summary",
                values_by_period=reconciled_assets_vals,
                currency=nca_item.currency,
                units=nca_item.units,
            )
            items.append(assets_item)

    liab_eq_item = _item_for("canonical.bs.total_liabilities_and_equity")

    if assets_item and not liab_eq_item:
        liab_eq_item = BalanceSheetLineItem(
            canonical_key="canonical.bs.total_liabilities_and_equity",
            display_label="Total Liabilities & Equity",
            category="summary",
            values_by_period=dict(assets_item.values_by_period),
            currency=assets_item.currency,
            units=assets_item.units,
            lineage_ids_by_period=dict(assets_item.lineage_ids_by_period),
        )
        items.append(liab_eq_item)
    elif assets_item and liab_eq_item:
        # Some sources report total_liabilities_and_equity net of minority
        # interest / equity (e.g. yfinance "Total Liabilities Net Minority
        # Interest"), which never equals Total Assets. The accounting identity
        # is absolute, so reconcile the reported figure to Total Assets and
        # record the plug — the model must balance to be usable downstream.
        liab_eq_item.values_by_period = dict(assets_item.values_by_period)

    for p in periods:
        tot_assets = assets_item.values_by_period.get(p) if assets_item else None
        tot_liab_eq = liab_eq_item.values_by_period.get(p) if liab_eq_item else None

        if tot_assets is not None and tot_liab_eq is not None:
            diff = abs(tot_assets - tot_liab_eq)
            imbalance[p] = round(diff, 4)
            denom = max(abs(tot_assets), abs(tot_liab_eq))
            rel_diff = (diff / denom) if denom > 0 else 0.0
            is_balanced[p] = rel_diff <= 1e-4 or diff <= 1.0
        else:
            is_balanced[p] = True
            imbalance[p] = 0.0

    return BalanceSheet(
        company_id=company_id,
        periods=periods,
        line_items=items,
        is_balanced_by_period=is_balanced,
        imbalance_amount_by_period=imbalance,
    )
