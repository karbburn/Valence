from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from backend.data.store import RawDatapoint
from backend.models.statements.selector import select_primary_datapoints
from backend.normalization.taxonomy.models import CanonicalDatapoint


IS_LINE_ITEM_CONFIG: List[tuple[str, str]] = [
    ("canonical.is.revenue", "Revenue from Operations"),
    ("canonical.is.cost_of_sales", "Cost of Sales"),
    ("canonical.is.gross_profit", "Gross Profit"),
    ("canonical.is.employee_cost", "Employee Cost"),
    ("canonical.is.selling_admin_exp", "Selling & Administrative Expenses"),
    ("canonical.is.other_mfr_exp", "Other Manufacturing Expenses"),
    ("canonical.is.power_fuel", "Power & Fuel"),
    ("canonical.is.other_exp", "Other Expenses"),
    ("canonical.is.total_opex", "Total Operating Expenses"),
    ("canonical.is.operating_profit", "Operating Profit / EBIT"),
    ("canonical.is.depreciation_amortization", "Depreciation & Amortization"),
    ("canonical.is.ebitda", "EBITDA"),
    ("canonical.is.finance_cost", "Finance Cost"),
    ("canonical.is.other_income", "Other Income"),
    ("canonical.is.pbt", "Profit Before Tax (PBT)"),
    ("canonical.is.tax", "Income Tax Expense"),
    ("canonical.is.net_profit", "Net Profit"),
    ("canonical.is.non_controlling_interests", "Non-Controlling Interests"),
    ("canonical.is.eps_basic", "Basic EPS (₹)"),
    ("canonical.is.eps_diluted", "Diluted EPS (₹)"),
]


class IncomeStatementLineItem(BaseModel):
    canonical_key: str
    display_label: str
    values_by_period: Dict[str, float] = Field(default_factory=dict)
    currency: str = "INR"
    units: str = "crores"
    lineage_ids_by_period: Dict[str, List[str]] = Field(default_factory=dict)


class IncomeStatement(BaseModel):
    company_id: str
    periods: List[str]
    line_items: List[IncomeStatementLineItem]

    def get_line_item(self, canonical_key: str) -> Optional[IncomeStatementLineItem]:
        for item in self.line_items:
            if item.canonical_key == canonical_key:
                return item
        return None

    def get_value(self, canonical_key: str, period: str) -> Optional[float]:
        item = self.get_line_item(canonical_key)
        if item:
            return item.values_by_period.get(period)
        return None


def assemble_income_statement(
    canonical_datapoints: list[CanonicalDatapoint],
    target_periods: list[str] | None = None,
    raw_datapoints_map: Dict[str, RawDatapoint] | None = None,
) -> IncomeStatement:
    """Assembles structured Income Statement from canonical datapoints."""
    if not canonical_datapoints:
        raise ValueError("No canonical datapoints provided for income statement assembly.")

    company_id = canonical_datapoints[0].company_id
    is_dps = [d for d in canonical_datapoints if d.canonical_key.startswith("canonical.is.")]

    all_periods = sorted(set(d.period_label for d in is_dps), key=lambda p: (len(p), p))
    if target_periods:
        periods = [p for p in target_periods if p in all_periods]
    else:
        periods = all_periods

    dp_map = select_primary_datapoints(is_dps, "is", raw_datapoints_map=raw_datapoints_map)

    items: List[IncomeStatementLineItem] = []

    for c_key, label in IS_LINE_ITEM_CONFIG:
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
                IncomeStatementLineItem(
                    canonical_key=c_key,
                    display_label=label,
                    values_by_period=values,
                    currency=curr,
                    units=un,
                    lineage_ids_by_period=lineage,
                )
            )

    # Derivation Fallback: Ensure canonical.is.operating_profit exists if missing
    op_item = next((i for i in items if i.canonical_key == "canonical.is.operating_profit"), None)
    if op_item is None or not op_item.values_by_period:
        rev_item = next((i for i in items if i.canonical_key == "canonical.is.revenue"), None)
        cos_item = next((i for i in items if i.canonical_key == "canonical.is.cost_of_sales"), None)
        gp_item = next((i for i in items if i.canonical_key == "canonical.is.gross_profit"), None)
        other_exp_item = next((i for i in items if i.canonical_key == "canonical.is.other_exp"), None)
        selling_admin_item = next((i for i in items if i.canonical_key == "canonical.is.selling_admin_exp"), None)

        derived_op: Dict[str, float] = {}
        for p in periods:
            r_val = rev_item.values_by_period.get(p) if rev_item else None
            gp_val = gp_item.values_by_period.get(p) if gp_item else None
            cos_val = cos_item.values_by_period.get(p) if cos_item else None
            if gp_val is None and r_val is not None and cos_val is not None:
                gp_val = r_val - cos_val

            oe_val = (other_exp_item.values_by_period.get(p) if other_exp_item else 0.0) or 0.0
            sa_val = (selling_admin_item.values_by_period.get(p) if selling_admin_item else 0.0) or 0.0
            opex = oe_val + sa_val

            if gp_val is not None and opex > 0:
                derived_op[p] = round(gp_val - opex, 2)

        if derived_op:
            items.append(
                IncomeStatementLineItem(
                    canonical_key="canonical.is.operating_profit",
                    display_label="Operating Profit / EBIT",
                    values_by_period=derived_op,
                    currency=items[0].currency if items else "USD",
                    units=items[0].units if items else "millions",
                    lineage_ids_by_period={},
                )
            )

    return IncomeStatement(
        company_id=company_id,
        periods=periods,
        line_items=items,
    )
