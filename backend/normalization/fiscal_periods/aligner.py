from __future__ import annotations

from datetime import date
from backend.normalization.taxonomy.models import CanonicalDatapoint


def align_fiscal_periods(datapoints: list[CanonicalDatapoint]) -> dict:
    """Verifies that all period_end_dates correctly align with April-March fiscal calendar.

    For Indian entities like Infosys, FY26 ends on March 31, 2026 (2026-03-31).
    Returns alignment summary and flags any misaligned records.
    """
    misaligned: list[dict] = []

    for dp in datapoints:
        label = dp.period_label.upper()
        if label.startswith("FY") and len(label) in (4, 6):
            try:
                yr_str = label[2:]
                year = 2000 + int(yr_str) if len(yr_str) == 2 else int(yr_str)
                is_us = dp.company_id.endswith("_us")
                if is_us:
                    # US companies have varying fiscal year ends (NVDA=Jan, MSFT=Jun, AAPL=Sep, AMZN=Dec)
                    # Verify period_end_date is within 1 calendar year of the FY label year
                    if abs(dp.period_end_date.year - year) > 1:
                        misaligned.append({
                            "id": dp.id,
                            "canonical_key": dp.canonical_key,
                            "period_label": dp.period_label,
                            "period_end_date": dp.period_end_date.isoformat(),
                            "expected_year": year,
                        })
                else:
                    # Indian entities standard March 31 calendar
                    expected_end = date(year, 3, 31)
                    if dp.period_end_date != expected_end:
                        misaligned.append({
                            "id": dp.id,
                            "canonical_key": dp.canonical_key,
                            "period_label": dp.period_label,
                            "period_end_date": dp.period_end_date.isoformat(),
                            "expected_end_date": expected_end.isoformat(),
                        })
            except ValueError:
                pass

    return {
        "total_checked": len(datapoints),
        "misaligned_count": len(misaligned),
        "misaligned_datapoints": misaligned,
        "is_aligned": len(misaligned) == 0,
    }
