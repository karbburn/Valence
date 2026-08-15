from __future__ import annotations

from typing import Dict, List, Tuple
from backend.normalization.taxonomy.models import CanonicalDatapoint


DERIVATION_RULES: Dict[str, str] = {
    "canonical.is.ebitda": "ebitda = canonical.is.operating_profit + canonical.is.depreciation_amortization",
    "canonical.is.ebitda_fallback": (
        "ebitda = canonical.is.pbt + canonical.is.finance_cost + canonical.is.depreciation_amortization"
    ),
}


def _build_derived(
    company_id: str,
    period: str,
    metric_raw: str,
    value: float,
    anchor: CanonicalDatapoint,
    source_ids: list[str],
    formula: str,
) -> CanonicalDatapoint:
    return CanonicalDatapoint(
        company_id=company_id,
        canonical_key="canonical.is.ebitda",
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
    """Derive non-reported canonical metrics (such as EBITDA) using explicit formulas.

    Attaches status = 'derived', references source datapoint IDs, and records derivation formula.
    Falls back to a bottom-up EBITDA (PBT + finance cost + D&A) when a company's
    income statement lacks a standalone operating-profit line.
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
            # 1. EBITDA Derivation
            ebitda_key = (company_id, period, "canonical.is.ebitda")
            if ebitda_key not in lookup:
                op_profit_key = (company_id, period, "canonical.is.operating_profit")
                da_key = (company_id, period, "canonical.is.depreciation_amortization")
                pbt_key = (company_id, period, "canonical.is.pbt")
                finance_cost_key = (company_id, period, "canonical.is.finance_cost")

                op_profit = lookup.get(op_profit_key)
                da = lookup.get(da_key)

                if op_profit is not None and da is not None:
                    formula = DERIVATION_RULES["canonical.is.ebitda"]
                    ebitda_dp = _build_derived(
                        company_id=company_id,
                        period=period,
                        metric_raw="EBITDA (Derived)",
                        value=op_profit.value + da.value,
                        anchor=op_profit,
                        source_ids=op_profit.source_datapoint_ids + da.source_datapoint_ids,
                        formula=formula,
                    )
                    new_derived.append(ebitda_dp)
                    lookup[ebitda_key] = ebitda_dp
                else:
                    pbt = lookup.get(pbt_key)
                    finance_cost = lookup.get(finance_cost_key)
                    if pbt is not None and da is not None and finance_cost is not None:
                        formula = DERIVATION_RULES["canonical.is.ebitda_fallback"]
                        ebitda_dp = _build_derived(
                            company_id=company_id,
                            period=period,
                            metric_raw="EBITDA (Derived)",
                            value=pbt.value + finance_cost.value + da.value,
                            anchor=pbt,
                            source_ids=pbt.source_datapoint_ids + finance_cost.source_datapoint_ids + da.source_datapoint_ids,
                            formula=formula,
                        )
                        new_derived.append(ebitda_dp)
                        lookup[ebitda_key] = ebitda_dp

            # 2. Current Investments Derivation Fallback
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

    return new_derived
