from __future__ import annotations

from typing import Dict, List, Tuple
from backend.normalization.taxonomy.models import CanonicalDatapoint


DERIVATION_RULES: Dict[str, str] = {
    "canonical.is.ebitda": "ebitda = canonical.is.operating_profit + canonical.is.depreciation_amortization",
}


def derive_canonical_metrics(datapoints: list[CanonicalDatapoint]) -> list[CanonicalDatapoint]:
    """Derive non-reported canonical metrics (such as EBITDA) using explicit formulas.

    Attaches status = 'derived', references source datapoint IDs, and records derivation formula.
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
            ebitda_key = (company_id, period, "canonical.is.ebitda")
            if ebitda_key in lookup:
                continue

            op_profit_key = (company_id, period, "canonical.is.operating_profit")
            da_key = (company_id, period, "canonical.is.depreciation_amortization")

            op_profit = lookup.get(op_profit_key)
            da = lookup.get(da_key)

            if op_profit is not None and da is not None:
                formula = DERIVATION_RULES["canonical.is.ebitda"]
                ebitda_dp = CanonicalDatapoint(
                    company_id=company_id,
                    canonical_key="canonical.is.ebitda",
                    metric_raw="EBITDA (Derived)",
                    period_label=period,
                    period_end_date=op_profit.period_end_date,
                    value=op_profit.value + da.value,
                    currency=op_profit.currency,
                    units=op_profit.units,
                    status="derived",
                    source_datapoint_ids=sorted(set(op_profit.source_datapoint_ids + da.source_datapoint_ids)),
                    derivation_rule=formula,
                )
                new_derived.append(ebitda_dp)
                lookup[ebitda_key] = ebitda_dp

    return new_derived
