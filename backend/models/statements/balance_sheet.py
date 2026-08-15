from __future__ import annotations

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from backend.data.store import RawDatapoint
from backend.models.statements.selector import select_primary_datapoints
from backend.normalization.taxonomy.models import CanonicalDatapoint

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
    ("canonical.bs.total_equity", "Total Equity", "equity"),

    # Non-Current Liabilities
    ("canonical.bs.borrowings", "Borrowings (Non-Current)", "non_current_liabilities"),
    ("canonical.bs.lease_liabilities", "Lease Liabilities", "non_current_liabilities"),
    ("canonical.bs.other_non_current_liabilities", "Other Non-Current Liabilities", "non_current_liabilities"),
    ("canonical.bs.total_non_current_liabilities", "Total Non-Current Liabilities", "non_current_liabilities"),

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
                BalanceSheetLineItem(
                    canonical_key=c_key,
                    display_label=label,
                    category=cat,
                    values_by_period=values,
                    currency=curr,
                    units=un,
                    lineage_ids_by_period=lineage,
                )
            )

    # Perform balance sheet equality checks
    is_balanced: Dict[str, bool] = {}
    imbalance: Dict[str, float] = {}

    # Reconcile Total Assets from sum of Non-Current Assets and Current Assets
    nca_item = next((i for i in items if i.canonical_key == "canonical.bs.total_non_current_assets"), None)
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

    liab_eq_item = next((i for i in items if i.canonical_key == "canonical.bs.total_liabilities_and_equity"), None)

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
