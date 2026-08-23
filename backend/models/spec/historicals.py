from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel

HistoricalStatus = Literal["reported", "reported_adjusted", "derived", "analyst_adjusted"]


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
