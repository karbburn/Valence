from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel

# `estimated` is a figure no filer published: a hand-entered projection in a
# repository spreadsheet. It is a valid value but it is NOT a historical fact,
# and any model built on it must say so rather than present it as a filing.
HistoricalStatus = Literal[
    "reported", "reported_adjusted", "derived", "analyst_adjusted", "estimated"
]

# Statuses that trace back to an actual filing or an audited statement.
REPORTED_STATUSES = frozenset({"reported", "reported_adjusted"})


class HistoricalLineItem(BaseModel):
    """Single canonical datapoint as it appears in the Model Specification.

    Carries full provenance traceable back to RawDatapoints via
    source_datapoint_ids. The `derivation_rule` field is non-null only for
    status="derived" entries (e.g. EBITDA formula), enabling the Excel
    renderer to surface derivation logic in the Methodology tab.
    """
    canonical_key: str
    period_label: str                       # e.g. "FY26"
    period_end_date: date                   # e.g. date(2026, 3, 31)
    value: float
    currency: str = "INR"
    units: str = "crores"
    status: HistoricalStatus
    source_datapoint_ids: List[str]         # raw datapoint IDs — full lineage
    derivation_rule: Optional[str] = None   # formula string if status=="derived"


class Historicals(BaseModel):
    """Collection of all historical canonical line items across all periods.

    Populated directly from the HistoricalModel output.
    """
    periods: List[str]                      # sorted, e.g. ["FY17"..."FY26"]
    line_items: List[HistoricalLineItem]

    def get(self, canonical_key: str, period: str) -> Optional[HistoricalLineItem]:
        for item in self.line_items:
            if item.canonical_key == canonical_key and item.period_label == period:
                return item
        return None

    def get_value(self, canonical_key: str, period: str) -> Optional[float]:
        item = self.get(canonical_key, period)
        return item.value if item else None

    def filed_period_end(self, period: str) -> Optional[date]:
        """The day this period was filed for, from the balance of the reported lines.

        A fiscal calendar gives the month and day a filer's year closes on, not
        the date it closed: NVIDIA's FY2026 ended 25 January 2026, the last Sunday
        of the month, and the 31st is what the calendar produces. Taking the LATEST
        date is no better, because the handful of lines that never carried a filed
        date fall back to the calendar and would then win. The date most of the
        reported lines agree on is the filing's.
        """
        counts: dict = {}
        for item in self.line_items:
            if item.period_label != period or not item.period_end_date:
                continue
            counts[item.period_end_date] = counts.get(item.period_end_date, 0) + 1
        if not counts:
            return None
        return max(counts, key=counts.get)
