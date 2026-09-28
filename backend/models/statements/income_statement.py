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
    ("canonical.is.research_development", "Research and Development"),
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

    # Derivation fallback: fill in any period that has no reported operating profit.
    #
    # This has to be per period, not all-or-nothing. It used to run only when the
    # line was missing for *every* period, so a filer that tagged operating income
    # in one year and not the others ended up with a line populated in one year
    # and empty in the rest, and nothing downstream noticed.
    #
    # The derivation is gross profit less the operating expense lines, and only
    # where those lines are actually itemised.
    #
    # An earlier version also offered profit before tax plus finance cost less
    # other income, on the reasoning that the three lines form an identity. They
    # are not an identity in the way it assumed. A filer whose "Other (income)
    # expense, net" already contains its interest expense double counts the whole
    # interest charge when finance cost is added back on top, and one large-cap
    # pharma does present it that way, noting so explicitly in the filing. The
    # error lands on the single year the filer does tag, and the arithmetic still
    # reconciles, so nothing catches it.
    #
    # The second derivation is kept only where the expense lines are genuinely
    # present. An absent line is not a zero line: treating a filer that does not
    # break out its operating expenses as having none returns gross profit, and a
    # 100% margin, which is how a company ends up valued at a hundredth of its
    # worth while every check passes. Better to leave the figure absent and say so.
    op_item = next((i for i in items if i.canonical_key == "canonical.is.operating_profit"), None)
    if op_item is None or any(
        op_item.values_by_period.get(p) is None for p in periods
    ):
        rev_item = next((i for i in items if i.canonical_key == "canonical.is.revenue"), None)
        cos_item = next((i for i in items if i.canonical_key == "canonical.is.cost_of_sales"), None)
        gp_item = next((i for i in items if i.canonical_key == "canonical.is.gross_profit"), None)
        other_exp_item = next((i for i in items if i.canonical_key == "canonical.is.other_exp"), None)
        selling_admin_item = next((i for i in items if i.canonical_key == "canonical.is.selling_admin_exp"), None)
        research_item = next((i for i in items if i.canonical_key == "canonical.is.research_development"), None)

        derived_op: Dict[str, float] = {}

        for p in periods:
            if op_item is not None and op_item.values_by_period.get(p) is not None:
                continue

            r_val = rev_item.values_by_period.get(p) if rev_item else None
            gp_val = gp_item.values_by_period.get(p) if gp_item else None
            cos_val = cos_item.values_by_period.get(p) if cos_item else None
            if gp_val is None and r_val is not None and cos_val is not None:
                gp_val = r_val - cos_val

            oe_val = other_exp_item.values_by_period.get(p) if other_exp_item else None
            sa_val = selling_admin_item.values_by_period.get(p) if selling_admin_item else None
            rd_val = research_item.values_by_period.get(p) if research_item else None

            # Selling and administrative expense is the one line a filer cannot
            # report operating profit without: gross profit less research alone
            # leaves out every other operating expense there is, and the result is
            # a near-100% operating margin that anchors the forecast on a company
            # with no costs. Research alone is not enough to recover the profit
            # from, so the period is skipped and the profit left absent, which is
            # the choice the rest of this module already makes.
            #
            # Research and development does belong in the sum once there is
            # something to sum it with. It used to be omitted because no filer's
            # line ever populated it, so leaving it out was inert. Now that it
            # carries real figures, omitting it overstates operating profit by the
            # whole research expense for a filer that does not tag operating income
            # directly, and the statement stays internally consistent throughout,
            # so the coherence checks cannot see it: the error is that the profit
            # is too high, not that it fails to add up.
            if sa_val is None:
                continue

            opex = (oe_val or 0.0) + sa_val + (rd_val or 0.0)

            if gp_val is not None and opex > 0:
                derived_op[p] = round(gp_val - opex, 2)

        if derived_op:
            if op_item is not None:
                for period, value in derived_op.items():
                    op_item.values_by_period.setdefault(period, value)
            else:
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
        elif op_item is not None and not op_item.values_by_period:
            # Nothing to derive. Drop the empty line so callers see an absent
            # figure rather than a present one that is silently zero.
            items = [i for i in items if i.canonical_key != "canonical.is.operating_profit"]

    return IncomeStatement(
        company_id=company_id,
        periods=periods,
        line_items=items,
    )
