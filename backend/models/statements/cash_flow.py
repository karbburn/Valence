from __future__ import annotations

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from backend.normalization.taxonomy.models import CanonicalDatapoint

CFCategoryType = Literal["operating", "investing", "financing", "adjustments", "summary"]

CF_LINE_ITEM_CONFIG: List[tuple[str, str, CFCategoryType]] = [
    ("canonical.cf.operating_activities", "Cash Flow from Operating Activities", "operating"),
    ("canonical.cf.taxes_paid", "Income Taxes Paid", "operating"),
    ("canonical.cf.investing_activities", "Cash Flow from Investing Activities", "investing"),
    ("canonical.cf.capex", "Capital Expenditure (CapEx)", "investing"),
    ("canonical.cf.business_acquisitions", "Payment for Business Acquisitions", "investing"),
    ("canonical.cf.interest_div_received", "Interest & Dividends Received", "investing"),
    ("canonical.cf.escrow_buyback_deposit", "Escrow / Buyback Deposits", "investing"),
    ("canonical.cf.financing_activities", "Cash Flow from Financing Activities", "financing"),
    ("canonical.cf.dividends_paid", "Dividends Paid", "financing"),
    ("canonical.cf.other_adjustments", "Other Operating / Non-Cash Adjustments", "adjustments"),
    ("canonical.cf.net_change_in_cash", "Net Change in Cash & Cash Equivalents", "summary"),
]


class CashFlowLineItem(BaseModel):
    canonical_key: str
    display_label: str
    category: CFCategoryType
    values_by_period: Dict[str, float] = Field(default_factory=dict)
    currency: str = "INR"
    units: str = "crores"
    lineage_ids_by_period: Dict[str, List[str]] = Field(default_factory=dict)


class CashFlowStatement(BaseModel):
    company_id: str
    periods: List[str]
    line_items: List[CashFlowLineItem]
    reconciles_to_bs_by_period: Dict[str, bool] = Field(default_factory=dict)

    def get_line_item(self, canonical_key: str) -> Optional[CashFlowLineItem]:
        for item in self.line_items:
            if item.canonical_key == canonical_key:
                return item
        return None

    def get_value(self, canonical_key: str, period: str) -> Optional[float]:
        item = self.get_line_item(canonical_key)
        if item:
            return item.values_by_period.get(period)
        return None


def assemble_cash_flow(
    canonical_datapoints: list[CanonicalDatapoint],
    target_periods: list[str] | None = None,
) -> CashFlowStatement:
    """Assembles structured Cash Flow Statement from canonical datapoints."""
    if not canonical_datapoints:
        raise ValueError("No canonical datapoints provided for cash flow assembly.")

    company_id = canonical_datapoints[0].company_id
    cf_dps = [d for d in canonical_datapoints if d.canonical_key.startswith("canonical.cf.")]

    all_periods = sorted(set(d.period_label for d in cf_dps), key=lambda p: (len(p), p))
    if target_periods:
        periods = [p for p in target_periods if p in all_periods]
    else:
        periods = all_periods

    dp_map: Dict[tuple[str, str], CanonicalDatapoint] = {}
    for d in cf_dps:
        dp_map[(d.canonical_key, d.period_label)] = d

    items: List[CashFlowLineItem] = []

    for c_key, label, cat in CF_LINE_ITEM_CONFIG:
        values: Dict[str, float] = {}
        lineage: Dict[str, List[str]] = {}
        curr = "INR"
        un = "crores"

        for p in periods:
            dp = dp_map.get((c_key, p))
            if dp is not None:
                values[p] = dp.value
                lineage[p] = dp.source_datapoint_ids
                curr = dp.currency
                un = dp.units

        if values:
            items.append(
                CashFlowLineItem(
                    canonical_key=c_key,
                    display_label=label,
                    category=cat,
                    values_by_period=values,
                    currency=curr,
                    units=un,
                    lineage_ids_by_period=lineage,
                )
            )

    return CashFlowStatement(
        company_id=company_id,
        periods=periods,
        line_items=items,
        reconciles_to_bs_by_period={p: True for p in periods},
    )
