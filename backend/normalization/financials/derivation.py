from __future__ import annotations

from typing import Dict, List, Tuple

import logging

from backend.normalization.taxonomy.models import CanonicalDatapoint

logger = logging.getLogger(__name__)


DERIVATION_RULES: Dict[str, str] = {
    "canonical.is.ebitda": "ebitda = canonical.is.operating_profit + canonical.is.depreciation_amortization",
    "canonical.is.ebitda_fallback": (
        "ebitda = canonical.is.pbt + canonical.is.finance_cost + canonical.is.depreciation_amortization"
    ),
    "canonical.is.operating_profit": "operating_profit = canonical.is.ebitda - canonical.is.depreciation_amortization",
    # Used when there is no EBITDA to subtract depreciation from. Finance cost is
    # deliberately absent: it may already sit inside the other income line, and
    # adding it back counts the interest charge twice. See the note at the call.
    "canonical.is.operating_profit_from_pbt": "operating_profit = canonical.is.pbt - canonical.is.other_income",
    "canonical.is.gross_profit": "gross_profit = canonical.is.revenue - canonical.is.cost_of_sales",
}


def _build_derived(
    company_id: str,
    canonical_key: str,
    period: str,
    metric_raw: str,
    value: float,
    anchor: CanonicalDatapoint,
    source_ids: list[str],
    formula: str,
) -> CanonicalDatapoint:
    return CanonicalDatapoint(
        company_id=company_id,
        canonical_key=canonical_key,
        metric_raw=metric_raw,
        period_label=period,
        period_end_date=anchor.period_end_date,
        value=value,
        currency=anchor.currency,
        units=anchor.units,
        status="derived",
        source_datapoint_ids=sorted(set(source_ids)),
        derivation_rule=formula,
    )


def derive_canonical_metrics(datapoints: list[CanonicalDatapoint]) -> list[CanonicalDatapoint]:
    """Derive non-reported canonical metrics (such as Operating Profit and EBITDA) using explicit formulas.

    Attaches status = 'derived', references source datapoint IDs, and records derivation formula.
    Falls back to Operating Profit (EBITDA - D&A) when a company's statement reports EBITDA directly.
    """
    # Index datapoints by (company_id, period_label, canonical_key)
    lookup: Dict[Tuple[str, str, str], CanonicalDatapoint] = {}
    periods_by_company: Dict[str, set[str]] = {}

    for dp in datapoints:
        key = (dp.company_id, dp.period_label, dp.canonical_key)
        lookup[key] = dp
        periods_by_company.setdefault(dp.company_id, set()).add(dp.period_label)

    new_derived: List[CanonicalDatapoint] = []

    for company_id, periods in periods_by_company.items():
        for period in periods:
            # 1. Operating Profit Derivation
            op_profit_key = (company_id, period, "canonical.is.operating_profit")
            if op_profit_key not in lookup:
                ebitda = lookup.get((company_id, period, "canonical.is.ebitda"))
                da = lookup.get((company_id, period, "canonical.is.depreciation_amortization"))
                pbt = lookup.get((company_id, period, "canonical.is.pbt"))
                other_income = lookup.get((company_id, period, "canonical.is.other_income"))

                if ebitda is not None and da is not None:
                    formula = DERIVATION_RULES["canonical.is.operating_profit"]
                    op_dp = _build_derived(
                        company_id=company_id,
                        canonical_key="canonical.is.operating_profit",
                        period=period,
                        metric_raw="Operating Profit (Derived)",
                        value=ebitda.value - da.value,
                        anchor=ebitda,
                        source_ids=ebitda.source_datapoint_ids + da.source_datapoint_ids,
                        formula=formula,
                    )
                    new_derived.append(op_dp)
                    lookup[op_profit_key] = op_dp
                elif pbt is not None and other_income is not None:
                    # Take out the filer's own whole non-operating block and add
                    # nothing back to it.
                    #
                    # This used to also add finance cost, on the reasoning that
                    # profit before tax is operating profit less interest plus
                    # other income, so all three had to be undone. That holds only
                    # when a filer reports interest *outside* its other income
                    # line. A filer whose "Other (income) expense, net" already
                    # contains its interest has it inside that block, and adding
                    # finance cost on top counts the same charge twice.
                    #
                    # One large-cap pharma presents it that way and says so in the
                    # filing: interest expense is a component of other (income)
                    # expense, net. The double count landed on the only year that
                    # filer tags operating income, inflating it by exactly the
                    # interest charge, and because the result is a self-consistent
                    # identity no check flagged it. The three-year average operating
                    # margin the forecast then anchored on came out at 5.8% for a
                    # business earning nearer thirty, and the enterprise value came
                    # out nineteen times too small.
                    #
                    # Removing the whole block does not actually need to know
                    # which of the two presentations a filer uses. Both were
                    # checked against filings: one pharma, where interest sits
                    # inside other (income) expense, net and 19,912 ties to its
                    # filed total costs; and a software filer, where the same tag
                    # is a larger net figure and 107,787 - (-1,646) returns
                    # 109,433, exactly the operating income it reports. Whether
                    # interest is inside the block stops mattering once the whole
                    # block is taken out.
                    #
                    # The residual risk is a filer that tags only part of the
                    # non-operating section under this key, which would leave the
                    # rest deducted and read low by that much. Erring low is the
                    # recoverable direction: a low figure stays visible and
                    # drags the valuation down, while an inflated one is
                    # indistinguishable from a good result once it is published.
                    finance_cost = lookup.get((company_id, period, "canonical.is.finance_cost"))
                    source_ids = pbt.source_datapoint_ids + other_income.source_datapoint_ids
                    if finance_cost is not None:
                        source_ids += finance_cost.source_datapoint_ids
                    op_dp = _build_derived(
                        company_id=company_id,
                        canonical_key="canonical.is.operating_profit",
                        period=period,
                        metric_raw="Operating Profit (Derived)",
                        value=pbt.value - other_income.value,
                        anchor=pbt,
                        source_ids=source_ids,
                        formula=DERIVATION_RULES["canonical.is.operating_profit_from_pbt"],
                    )
                    new_derived.append(op_dp)
                    lookup[op_profit_key] = op_dp

            # 2. EBITDA Derivation
            ebitda_key = (company_id, period, "canonical.is.ebitda")
            if ebitda_key not in lookup:
                op_profit = lookup.get((company_id, period, "canonical.is.operating_profit"))
                da = lookup.get((company_id, period, "canonical.is.depreciation_amortization"))
                pbt = lookup.get((company_id, period, "canonical.is.pbt"))
                finance_cost = lookup.get((company_id, period, "canonical.is.finance_cost"))

                if op_profit is not None and da is not None:
                    formula = DERIVATION_RULES["canonical.is.ebitda"]
                    ebitda_dp = _build_derived(
                        company_id=company_id,
                        canonical_key="canonical.is.ebitda",
                        period=period,
                        metric_raw="EBITDA (Derived)",
                        value=op_profit.value + da.value,
                        anchor=op_profit,
                        source_ids=op_profit.source_datapoint_ids + da.source_datapoint_ids,
                        formula=formula,
                    )
                    new_derived.append(ebitda_dp)
                    lookup[ebitda_key] = ebitda_dp
                elif pbt is not None and da is not None and finance_cost is not None:
                    formula = DERIVATION_RULES["canonical.is.ebitda_fallback"]
                    ebitda_dp = _build_derived(
                        company_id=company_id,
                        canonical_key="canonical.is.ebitda",
                        period=period,
                        metric_raw="EBITDA (Derived)",
                        value=pbt.value + finance_cost.value + da.value,
                        anchor=pbt,
                        source_ids=pbt.source_datapoint_ids + finance_cost.source_datapoint_ids + da.source_datapoint_ids,
                        formula=formula,
                    )
                    new_derived.append(ebitda_dp)
                    lookup[ebitda_key] = ebitda_dp

            # 3. Gross Profit Derivation
            gp_key = (company_id, period, "canonical.is.gross_profit")
            if gp_key not in lookup:
                rev = lookup.get((company_id, period, "canonical.is.revenue"))
                cogs = lookup.get((company_id, period, "canonical.is.cost_of_sales"))
                if rev is not None and cogs is not None:
                    gp_dp = _build_derived(
                        company_id=company_id,
                        canonical_key="canonical.is.gross_profit",
                        period=period,
                        metric_raw="Gross Profit (Derived)",
                        value=rev.value - abs(cogs.value),
                        anchor=rev,
                        source_ids=rev.source_datapoint_ids + cogs.source_datapoint_ids,
                        formula="gross_profit = revenue - cost_of_sales",
                    )
                    new_derived.append(gp_dp)
                    lookup[gp_key] = gp_dp

            # 4. Current Investments Derivation Fallback
            #
            # What survives this subtraction is current assets the engine has not
            # identified, which is a residual, not a security. Publishing it under
            # the investments key let the enterprise bridge deduct unidentified
            # current assets as though they were marketable securities: a filer
            # whose balance sheet printed 23,900 of "other current assets" against
            # 22,500 of prepayments had the 1,400 difference presented as a
            # security it does not hold.
            #
            # The subtraction has to cover every current-asset line the renderer
            # prints, or the residual absorbs the ones it misses and republishes
            # them as a security. Unbilled revenue is on that list: it is a rendered
            # line, it is in the sheet contract, and it is mapped, so a filer with
            # unbilled revenue and no tagged securities line had its unbilled
            # revenue deducted from enterprise value as though it were one.
            #
            # There is exactly ONE current-asset catch-all to subtract, and it
            # carries the filer's own caption. `OtherAssetsCurrent` and
            # `PrepaidExpenseCurrent` are not two independent lines: the second is
            # a member of the first, so holding both double-counted the smaller
            # inside the larger. Armstrong's identified current assets came to
            # 414.0 against a filed subtotal of 391.5, and the clamp below turned
            # that 22.5 of overlap into silence rather than a report.
            ci_key = (company_id, period, "canonical.bs.current_investments")
            tca_key = (company_id, period, "canonical.bs.total_current_assets")
            if ci_key not in lookup and tca_key in lookup:
                tca = lookup[tca_key]
                cash = lookup.get((company_id, period, "canonical.bs.cash_and_bank"))
                rec = lookup.get((company_id, period, "canonical.bs.trade_receivables"))
                inv = lookup.get((company_id, period, "canonical.bs.inventory"))
                unbilled = lookup.get((company_id, period, "canonical.bs.unbilled_revenue"))
                vendor = lookup.get((company_id, period, "canonical.bs.vendor_non_trade_receivables"))
                prep = lookup.get((company_id, period, "canonical.bs.prepayments_other_current_assets"))

                cash_val = cash.value if cash else 0.0
                rec_val = rec.value if rec else 0.0
                inv_val = inv.value if inv else 0.0
                unbilled_val = unbilled.value if unbilled else 0.0
                vendor_val = vendor.value if vendor else 0.0
                prep_val = prep.value if prep else 0.0

                identified = cash_val + rec_val + inv_val + unbilled_val + vendor_val + prep_val
                derived_ci_val = tca.value - identified
                if derived_ci_val > 0.0:
                    # A copy, not the anchor's own list: `source_ids = tca.` followed
                    # by `+=` extends the very list pydantic holds on the total-current-
                    # assets model, so that line's published lineage became the union
                    # of itself and every line subtracted from it.
                    source_ids = list(tca.source_datapoint_ids)
                    for anchor in (cash, rec, inv, unbilled, vendor, prep):
                        if anchor:
                            source_ids += list(anchor.source_datapoint_ids)

                    ci_dp = CanonicalDatapoint(
                        company_id=company_id,
                        canonical_key="canonical.bs.current_investments",
                        metric_raw="Current Investments (Derived)",
                        period_label=period,
                        period_end_date=tca.period_end_date,
                        value=derived_ci_val,
                        currency=tca.currency,
                        units=tca.units,
                        status="derived",
                        source_datapoint_ids=sorted(set(source_ids)),
                        derivation_rule="current_investments = total_current_assets - (cash + receivables + inventory + unbilled revenue + vendor non-trade receivables + prepayments and other current assets)",
                    )
                    new_derived.append(ci_dp)
                    lookup[ci_key] = ci_dp
                elif abs(derived_ci_val) > 0.5:
                    # The identified lines EXCEED the filer's own subtotal, which
                    # means two of them overlap. Publishing nothing and saying
                    # nothing hides a real disagreement between the engine and the
                    # filing, so it is surfaced here rather than clamped away.
                    logger.warning(
                        "%s %s: identified current assets (%.1f) exceed the filed "
                        "total_current_assets (%.1f) by %.1f — at least two of the "
                        "subtracted lines are the same money counted twice",
                        company_id, period, identified, tca.value, -derived_ci_val,
                    )

            # 5. Total Non-Current Assets Derivation Fallback
            #
            # Section 7 derives total assets from non-current plus current. The
            # reverse was never derived, so a filer that reports total assets and
            # total current assets but not the non-current subtotal published an
            # empty row against a balance sheet that visibly did not add up: this
            # filer showed 206,803 of total assets and 125,605 of current assets,
            # leaving 81,198 unaccounted for with the only non-current line shown
            # being 10,383 of property, plant and equipment.
            #
            # Reported figures stay authoritative in both directions. A derived
            # subtotal is only produced where the filer publishes none, which is
            # what the arithmetic of the two reported lines is actually worth.
            tnca_key = (company_id, period, "canonical.bs.total_non_current_assets")
            tca_for_nca = lookup.get((company_id, period, "canonical.bs.total_current_assets"))
            ta_for_nca = lookup.get((company_id, period, "canonical.bs.total_assets"))

            if tnca_key not in lookup and ta_for_nca is not None and tca_for_nca is not None:
                derived_nca = ta_for_nca.value - tca_for_nca.value
                if derived_nca > 0.0:
                    nca_dp = CanonicalDatapoint(
                        company_id=company_id,
                        canonical_key="canonical.bs.total_non_current_assets",
                        metric_raw="Total Non-Current Assets (Derived)",
                        period_label=period,
                        period_end_date=ta_for_nca.period_end_date,
                        value=derived_nca,
                        currency=ta_for_nca.currency,
                        units=ta_for_nca.units,
                        status="derived",
                        source_datapoint_ids=sorted(
                            set(ta_for_nca.source_datapoint_ids + tca_for_nca.source_datapoint_ids)
                        ),
                        derivation_rule="total_non_current_assets = total_assets - total_current_assets",
                    )
                    new_derived.append(nca_dp)
                    lookup[tnca_key] = nca_dp

            # 6. Non-Current Assets Against the Filer's Own Subtotal
            #
            # A filer reports its other non-current assets either itemised or as a
            # catch-all, and the catch-all often already contains one of the lines
            # named beside it. Publishing both then counts that line twice, and the
            # named lines come to exceed the subtotal they belong to: one filer's
            # named lines totalled 226,869 against a reported 209,017, which is
            # worse than naming nothing, because the reader is told the company
            # holds more than it does.
            #
            # Which line is the duplicate is settled by the filer's own subtotal,
            # not by comparing sizes. Sizes cannot distinguish a line that sits
            # inside the catch-all from one that merely happens to be smaller, and
            # guessing nets an unrelated pair: one filer's deferred tax of 17,852
            # was subtracted from a catch-all that did contain it, while its
            # 100,544 of marketable securities, which that catch-all never
            # contained, was left standing. The statement then came up 56,946
            # short, having previously been over.
            #
            # So the itemised lines are added up and compared with the reported
            # subtotal. Where they exceed it, the catch-all is reduced by the
            # amount that closes the difference, being the part of it already
            # itemised among the others. The reduction is bounded by the catch-all,
            # so a filer whose lines really are disjoint is left untouched.
            # Without a reported subtotal nothing is assumed, and the section above derives
            # one for the following period to be compared against.
            nci_key = (company_id, period, "canonical.bs.non_current_investments")
            other_nca_key = (company_id, period, "canonical.bs.other_non_current_assets")
            nci = lookup.get(nci_key)
            other_nca = lookup.get(other_nca_key)
            reported_nca = lookup.get(
                (company_id, period, "canonical.bs.total_non_current_assets")
            )
            if nci is not None and other_nca is not None and reported_nca is not None:
                # The lines a filer itemises beside its catch-all. The catch-all is
                # not among them, being the line the question is about.
                itemised = (
                    "canonical.bs.ppe",
                    "canonical.bs.cwip",
                    "canonical.bs.goodwill",
                    "canonical.bs.intangible_assets",
                    "canonical.bs.non_current_investments",
                    "canonical.bs.deferred_tax_assets",
                )
                named = 0.0
                for key in itemised:
                    dp = lookup.get((company_id, period, key))
                    if dp is not None:
                        named += dp.value
                excess = (named + other_nca.value) - reported_nca.value
                if excess > 0.0:
                    absorbed = CanonicalDatapoint(
                        company_id=company_id,
                        canonical_key="canonical.bs.other_non_current_assets",
                        metric_raw="Other Non-Current Assets (Net of Overlap)",
                        period_label=period,
                        period_end_date=other_nca.period_end_date,
                        value=max(0.0, other_nca.value - excess),
                        currency=other_nca.currency,
                        units=other_nca.units,
                        status="derived",
                        source_datapoint_ids=sorted(
                            set(other_nca.source_datapoint_ids + nci.source_datapoint_ids)
                        ),
                        derivation_rule=(
                            "other_non_current_assets = filer catch-all less the part "
                            "of it already itemised among the named lines"
                        ),
                    )
                    new_derived.append(absorbed)
                    lookup[other_nca_key] = absorbed

            # 7. Total Assets Reconciliation Derivation
            ta_key = (company_id, period, "canonical.bs.total_assets")
            tnca = lookup.get((company_id, period, "canonical.bs.total_non_current_assets"))
            tca_dp = lookup.get((company_id, period, "canonical.bs.total_current_assets"))

            if tnca is not None and tca_dp is not None:
                calculated_ta = tnca.value + tca_dp.value
                existing_ta = lookup.get(ta_key)
                # Reported Total Assets is authoritative — only derive a reconciled value
                # when the company does NOT report it at all. Never overwrite a reported value.
                if existing_ta is None:
                    ta_dp = _build_derived(
                        company_id=company_id,
                        canonical_key="canonical.bs.total_assets",
                        period=period,
                        metric_raw="Total Assets (Reconciled)",
                        value=calculated_ta,
                        anchor=tnca,
                        source_ids=tnca.source_datapoint_ids + tca_dp.source_datapoint_ids,
                        formula="total_assets = total_non_current_assets + total_current_assets",
                    )
                    new_derived.append(ta_dp)
                    lookup[ta_key] = ta_dp

            # 8. Selling and Administrative Expense Derivation
            #
            # Filers split the same total two ways. One reports a single combined
            # selling, general and administrative line. Another reports selling and
            # marketing and general and administrative as two lines, and the
            # marketing line alone runs to tens of billions. Reading only the
            # combined tag left the second kind of filer publishing nothing, so
            # gross profit less operating expense stopped reconciling to reported
            # operating profit by a gap that grew every year.
            #
            # The reported combined figure is always kept as reported. The two
            # components are summed only where the filer publishes no combined
            # line at all, and they are summed into the same canonical key rather
            # than published beside it, because for the filers that do report a
            # combined line those same tags are a breakdown of it: one technology
            # issuer's marketing plus administrative is exactly its combined
            # figure, and adding them would double count the whole amount.
            sa_key = (company_id, period, "canonical.is.selling_admin_exp")
            if sa_key not in lookup:
                sm = lookup.get((company_id, period, "canonical.is.sales_marketing"))
                ga = lookup.get((company_id, period, "canonical.is.general_admin"))
                # Both halves, or nothing.
                #
                # One half on its own is not the total, and publishing it under a
                # label that says selling and administrative expense states a
                # number the filer never reported. A filer that tags only general
                # and administrative has given half the figure at best, and
                # whether the other half exists is not knowable from what it
                # tagged. Deriving from one half therefore understates operating
                # expense by an unknown amount, which is worse than publishing
                # nothing and saying so.
                if sm is not None and ga is not None:
                    anchor = sm or ga
                    parts = [p for p in (sm, ga) if p is not None]
                    sa_dp = CanonicalDatapoint(
                        company_id=company_id,
                        canonical_key="canonical.is.selling_admin_exp",
                        metric_raw="Selling and Admin Expense (Derived)",
                        period_label=period,
                        period_end_date=anchor.period_end_date,
                        value=sum(p.value for p in parts),
                        currency=anchor.currency,
                        units=anchor.units,
                        status="derived",
                        source_datapoint_ids=sorted(
                            {sid for p in parts for sid in p.source_datapoint_ids}
                        ),
                        derivation_rule=(
                            "selling_admin_exp = selling_and_marketing + general_and_administrative"
                        ),
                    )
                    new_derived.append(sa_dp)
                    lookup[sa_key] = sa_dp

            # 9. Total Equity Derivation
            #
            # Preference order, and it matters: the two routes that reconcile with
            # the filer's own balance sheet come first, and summing components comes
            # last because it is the only route that can silently disagree with them.
            #
            # A filer's screener export often carries no total-liabilities line, so
            # this fell straight through to the component sum. For Tata Consultancy
            # that published equity of 108,562 from share capital 362 plus reserves
            # 108,200, while the filer's own total assets were 174,162: derived
            # liabilities of 73,298 then came to 181,860 against those same assets, a
            # 7,698 hole. Nothing caught it, because `balance_sheet_balances` compares
            # total assets to the filer's REPORTED total-liabilities-and-equity, and
            # that pair ties. The components were never cross-checked against
            # anything.
            te_key = (company_id, period, "canonical.bs.total_equity")
            if te_key not in lookup:
                ta_dp = lookup.get(ta_key)
                tl_dp = lookup.get((company_id, period, "canonical.bs.total_liabilities"))
                tle_dp = lookup.get(
                    (company_id, period, "canonical.bs.total_liabilities_and_equity")
                )
                # Equity components use the canonical keys produced by the taxonomy
                # registry: share capital plus reserves and/or retained earnings.
                component_dps = [
                    lookup.get((company_id, period, k))
                    for k in (
                        "canonical.bs.equity_capital",
                        "canonical.bs.retained_earnings",
                        "canonical.bs.other_reserves",
                    )
                ]
                present = [dp for dp in component_dps if dp is not None]

                te_dp = None
                if ta_dp is not None and tl_dp is not None:
                    te_dp = _build_derived(
                        company_id=company_id,
                        canonical_key="canonical.bs.total_equity",
                        period=period,
                        metric_raw="Total Equity (Derived)",
                        value=ta_dp.value - tl_dp.value,
                        anchor=ta_dp,
                        source_ids=ta_dp.source_datapoint_ids + tl_dp.source_datapoint_ids,
                        formula="total_equity = total_assets - total_liabilities",
                    )
                elif tle_dp is not None and tl_dp is not None:
                    # The filer prints the whole right-hand side of the balance sheet
                    # but not its liabilities line, so equity is the difference.
                    # Reconciles with the filer's own subtotal by construction, which
                    # the component sum does not.
                    te_dp = _build_derived(
                        company_id=company_id,
                        canonical_key="canonical.bs.total_equity",
                        period=period,
                        metric_raw="Total Equity (Derived)",
                        value=tle_dp.value - tl_dp.value,
                        anchor=tle_dp,
                        source_ids=tle_dp.source_datapoint_ids + tl_dp.source_datapoint_ids,
                        formula="total_equity = total_liabilities_and_equity - total_liabilities",
                    )
                elif len(present) >= 2:
                    total_from_parts = sum(dp.value for dp in present)
                    # Say so when the parts do not agree with the filer's own subtotal.
                    # The sum is still published, because it is the only equity figure
                    # available, but a reader is entitled to know it is not the
                    # filer's arithmetic.
                    if tle_dp is not None:
                        gap = total_from_parts - (tle_dp.value - (tl_dp.value if tl_dp else 0.0))
                        if abs(gap) > max(abs(tle_dp.value) * 0.005, 1.0):
                            logger.warning(
                                "%s %s: equity components sum to %.1f, which is %.1f "
                                "away from the filer's own total-liabilities-and-equity "
                                "less liabilities. The components are not the filer's "
                                "equity arithmetic; published as the only figure "
                                "available, and flagged.",
                                company_id, period, total_from_parts, gap,
                            )
                    source_ids: list[str] = []
                    for dp in present:
                        source_ids += list(dp.source_datapoint_ids)
                    te_dp = _build_derived(
                        company_id=company_id,
                        canonical_key="canonical.bs.total_equity",
                        period=period,
                        metric_raw="Total Equity (Derived)",
                        value=total_from_parts,
                        anchor=present[0],
                        source_ids=source_ids,
                        formula="total_equity = equity_capital + retained_earnings + other_reserves (reported components)",
                    )
                if te_dp is not None:
                    new_derived.append(te_dp)
                    lookup[te_key] = te_dp

            # 10. Total Liabilities & Equity Reconciliation Derivation
            tle_key = (company_id, period, "canonical.bs.total_liabilities_and_equity")
            tl_dp = lookup.get((company_id, period, "canonical.bs.total_liabilities"))
            te_dp = lookup.get((company_id, period, "canonical.bs.total_equity"))
            # Reported TLE is authoritative — only derive when the company does not report it.
            if tle_key not in lookup and tl_dp is not None and te_dp is not None:
                calculated_tle = tl_dp.value + te_dp.value
                tle_dp = _build_derived(
                    company_id=company_id,
                    canonical_key="canonical.bs.total_liabilities_and_equity",
                    period=period,
                    metric_raw="Total Liabilities & Equity (Reconciled)",
                    value=calculated_tle,
                    anchor=tl_dp,
                    source_ids=tl_dp.source_datapoint_ids + te_dp.source_datapoint_ids,
                    formula="total_liabilities_and_equity = total_liabilities + total_equity",
                )
                new_derived.append(tle_dp)
                lookup[tle_key] = tle_dp

    return new_derived
