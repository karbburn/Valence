from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

import openpyxl

from backend.data.store import RawDatapoint, Source, Status

COMPANY_ID = "infy_infy"


def _datapoint_id(company_id: str, metric: str, period: str, source: str, section: str, row: int) -> str:
    return hashlib.sha1(f"{company_id}|{section}|{metric}|{period}|{source}|{row}".encode()).hexdigest()


def _clean(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, float):
        return v
    s = str(v).replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _period_label(d: date) -> str:
    # Screener fiscal periods: FY24 = Apr 2023 – Mar 2024 (period end 2024-03-31)
    return f"FY{str(d.year)[2:]}"


def parse_screener_export(path: str | Path) -> list[RawDatapoint]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Data Sheet"]
    rows = list(ws.iter_rows(values_only=True))

    datapoints: list[RawDatapoint] = []
    # Section starts by header keyword, then "Report Date" row gives periods.
    header_idx = None
    for i, row in enumerate(rows):
        if row[0] in ("PROFIT & LOSS", "BALANCE SHEET", "CASH FLOW:"):
            header_idx = i
        if row[0] == "Report Date" and header_idx is not None:
            periods: list[date] = [r.date() for r in row[1:] if hasattr(r, "date")]
            section = rows[header_idx][0]
            for j in range(i + 1, len(rows)):
                label = (rows[j][0] or "").strip()
                if not label or (isinstance(rows[j][0], str) and rows[j][0] in ("PROFIT & LOSS", "BALANCE SHEET", "CASH FLOW:", "Quarters", "PRICE:", "DERIVED:")):
                    break
                values = [_clean(v) for v in rows[j][1:]]
                for k, (period, val) in enumerate(zip(periods, values)):
                    if val is None:
                        continue
                    source: Source = "screener"
                    status: Status = "reported"
                    offset = k + 2  # column B (index 1) is first period
                    col = openpyxl.utils.get_column_letter(offset + 1)
                    datapoints.append(
                        RawDatapoint(
                            id=_datapoint_id(COMPANY_ID, label, _period_label(period), "screener", section, j + 1),
                            company_id=COMPANY_ID,
                            metric_raw=label,
                            period_label=_period_label(period),
                            period_end_date=period,
                            value=val,
                            currency="INR",
                            units="crores",
                            source=source,
                            source_location=f"DataSheet!{col}{j + 1}",
                            status=status,
                            update_date=datetime.now(),
                        )
                    )
            header_idx = None
    wb.close()
    return datapoints