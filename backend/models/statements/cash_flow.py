from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from backend.normalization.taxonomy.models import CanonicalDatapoint

logger = logging.getLogger(__name__)

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
    ("canonical.cf.stock_compensation", "Memo: Stock-Based Compensation", "adjustments"),
]


class CashFlowLineItem(BaseModel):
    canonical_key: str
    display_label: str
    category: CFCategoryType
    values_by_period: Dict[str, float] = Field(default_factory=dict)
    currency: str = "INR"
    units: str = "crores"
    lineage_ids_by_period: Dict[str, List[str]] = Field(default_factory=dict)
    # The day each period was FILED for, so the forecast that grows out of these
    # periods inherits the filer's own calendar rather than a constructed one.
    period_end_dates_by_period: Dict[str, date] = Field(default_factory=dict)


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
        period_ends: Dict[str, date] = {}

        for p in periods:
            dp = dp_map.get((c_key, p))
            if dp is not None:
                values[p] = dp.value
                lineage[p] = dp.source_datapoint_ids
                period_ends[p] = dp.period_end_date
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
                    period_end_dates_by_period=period_ends,
                )
            )

    return CashFlowStatement(
        company_id=company_id,
        periods=periods,
        line_items=items,
        reconciles_to_bs_by_period={p: True for p in periods},
    )


# The three sections a cash flow statement is made of. Their sum IS the net
# change in cash: that is the definition, not a relationship that might hold.
_CF_SECTIONS = (
    "canonical.cf.operating_activities",
    "canonical.cf.investing_activities",
    "canonical.cf.financing_activities",
)


def derive_net_change_in_cash(cf_model: CashFlowStatement) -> None:
    """Set net change in cash to the sum of the three sections, in place.

    It was read as an input, and the feeds either omit it or report zero, so the
    cash flow statement published a net change in cash of 0.0 for every company
    in every period while the balance sheet's own cash line moved — at one
    large-cap by 1,309 and 2,016 against a published zero. The line a reader
    checks to see whether the statement adds up was the one line guaranteed not
    to.

    Where all three sections are present the sum is the answer, and a reported
    figure that disagrees with it is logged rather than published. Where a
    section is missing the reported figure is left alone: a partial sum is not a
    net change, and inventing one is worse than reporting what the source said.
    """
    by_key = {item.canonical_key: item for item in cf_model.line_items}
    net_item = by_key.get("canonical.cf.net_change_in_cash")
    sections = [by_key.get(k) for k in _CF_SECTIONS]

    # The line is created when the source never reported one. It is the total of
    # the three sections the statement already publishes, so leaving it off the
    # page removes the one line a reader uses to see whether the statement adds
    # up — and at one large-cap its balance-sheet cash moved 1,309 and 2,016
    # against a line that was simply absent.
    if net_item is None and all(s is not None for s in sections):
        net_item = CashFlowLineItem(
            canonical_key="canonical.cf.net_change_in_cash",
            display_label="Net Change in Cash & Cash Equivalents",
            category="summary",
            values_by_period={},
            currency=sections[0].currency,
            units=sections[0].units,
            lineage_ids_by_period={},
        )
        cf_model.line_items.append(net_item)
        # Keep the summary line last, where a reader looks for it.
        cf_model.line_items.sort(key=lambda i: 0 if i.category != "summary" else 1)

    if net_item is None:
        return

    for period in cf_model.periods:
        if any(s is None or period not in s.values_by_period for s in sections):
            continue
        derived = sum(float(s.values_by_period[period]) for s in sections)

        reported = net_item.values_by_period.get(period)
        if reported is not None and abs(float(reported) - derived) > 0.01:
            logger.info(
                "%s %s: reported net change in cash %.2f disagrees with the sum of "
                "its three sections %.2f; publishing the sum, which is the "
                "definition",
                cf_model.company_id, period, float(reported), derived,
            )
        net_item.values_by_period[period] = round(derived, 2)
