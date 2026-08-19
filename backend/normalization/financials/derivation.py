from __future__ import annotations

from typing import Dict, List, Tuple
from backend.normalization.taxonomy.models import CanonicalDatapoint


DERIVATION_RULES: Dict[str, str] = {
    "canonical.is.ebitda": "ebitda = canonical.is.operating_profit + canonical.is.depreciation_amortization",
    "canonical.is.ebitda_fallback": (
        "ebitda = canonical.is.pbt + canonical.is.finance_cost + canonical.is.depreciation_amortization"
    ),
    "canonical.is.operating_profit": "operating_profit = canonical.is.ebitda - canonical.is.depreciation_amortization",
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
                finance_cost = lookup.get((company_id, period, "canonical.is.finance_cost"))
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
                elif pbt is not None and finance_cost is not None:
                    other_inc_val = other_income.value if other_income else 0.0
                    source_ids = pbt.source_datapoint_ids + finance_cost.source_datapoint_ids
                    if other_income:
                        source_ids += other_income.source_datapoint_ids
                    op_dp = _build_derived(
                        company_id=company_id,
                        canonical_key="canonical.is.operating_profit",
                        period=period,
                        metric_raw="Operating Profit (Derived)",
                        value=pbt.value + finance_cost.value - other_inc_val,
                        anchor=pbt,
                        source_ids=source_ids,
                        formula="operating_profit = pbt + finance_cost - other_income",
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
            ci_key = (company_id, period, "canonical.bs.current_investments")
            tca_key = (company_id, period, "canonical.bs.total_current_assets")
            if ci_key not in lookup and tca_key in lookup:
                tca = lookup[tca_key]
                cash = lookup.get((company_id, period, "canonical.bs.cash_and_bank"))
                rec = lookup.get((company_id, period, "canonical.bs.trade_receivables"))
                inv = lookup.get((company_id, period, "canonical.bs.inventory"))
                prep = lookup.get((company_id, period, "canonical.bs.prepayments_other_current_assets"))
                
                cash_val = cash.value if cash else 0.0
                rec_val = rec.value if rec else 0.0
                inv_val = inv.value if inv else 0.0
                prep_val = prep.value if prep else 0.0
                
                derived_ci_val = max(0.0, tca.value - (cash_val + rec_val + inv_val + prep_val))
                if derived_ci_val > 0.0:
                    source_ids = tca.source_datapoint_ids
                    if cash: source_ids += cash.source_datapoint_ids
                    if rec: source_ids += rec.source_datapoint_ids
                    if inv: source_ids += inv.source_datapoint_ids
                    if prep: source_ids += prep.source_datapoint_ids
                    
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
                        derivation_rule="current_investments = total_current_assets - (cash + receivables + inventory + prepayments)",
                    )
                    new_derived.append(ci_dp)
                    lookup[ci_key] = ci_dp

            # 5. Total Assets Reconciliation Derivation
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

            # 6. Total Equity Derivation
            te_key = (company_id, period, "canonical.bs.total_equity")
            if te_key not in lookup:
                ta_dp = lookup.get(ta_key)
                tl_dp = lookup.get((company_id, period, "canonical.bs.total_liabilities"))
                sc_dp = lookup.get((company_id, period, "canonical.bs.equity_share_capital"))
                res_dp = lookup.get((company_id, period, "canonical.bs.other_equity")) or lookup.get((company_id, period, "canonical.bs.retained_earnings"))

                if ta_dp is not None and tl_dp is not None:
                    derived_te_val = ta_dp.value - tl_dp.value
                    te_dp = _build_derived(
                        company_id=company_id,
                        canonical_key="canonical.bs.total_equity",
                        period=period,
                        metric_raw="Total Equity (Derived)",
                        value=derived_te_val,
                        anchor=ta_dp,
                        source_ids=ta_dp.source_datapoint_ids + tl_dp.source_datapoint_ids,
                        formula="total_equity = total_assets - total_liabilities",
                    )
                    new_derived.append(te_dp)
                    lookup[te_key] = te_dp
                elif sc_dp is not None and res_dp is not None:
                    derived_te_val = sc_dp.value + res_dp.value
                    te_dp = _build_derived(
                        company_id=company_id,
                        canonical_key="canonical.bs.total_equity",
                        period=period,
                        metric_raw="Total Equity (Derived)",
                        value=derived_te_val,
                        anchor=sc_dp,
                        source_ids=sc_dp.source_datapoint_ids + res_dp.source_datapoint_ids,
                        formula="total_equity = equity_share_capital + reserves",
                    )
                    new_derived.append(te_dp)
                    lookup[te_key] = te_dp

            # 7. Total Liabilities & Equity Reconciliation Derivation
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
