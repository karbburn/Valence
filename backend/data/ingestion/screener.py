from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

import openpyxl

from backend.data.store import RawDatapoint, Source, Status


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


def parse_screener_export(path: str | Path, company_id: str = "infy_infy") -> list[RawDatapoint]:
    """Parse a Screener.in structured XLSX export into RawDatapoint records.

    The export format is a "Data Sheet" workbook tab with section headers
    ("PROFIT & LOSS", "BALANCE SHEET", "CASH FLOW:") followed by a
    "Report Date" row giving fiscal period end dates, then row-per-metric
    data in INR Crores.

    Args:
        path: Absolute or relative path to the Screener XLSX export file.
        company_id: Dynamic company identifier supplied by the caller at
            ingestion time (e.g. "infy_infy", "tcs_tcs"). Not a static
            constant — must be provided explicitly for each company ingested.

    Returns:
        List of RawDatapoint records tagged with source="screener",
        currency="INR", units="crores".
    """
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
                    # Every row this reader produces is marked ESTIMATED, not
                    # reported, and that is the honest label rather than a
                    # conservative one.
                    #
                    # The files read here are not Screener.in exports. They are
                    # written by backend/data/sources/generate_sources.py, which
                    # is tracked in this repository and hand-enters the figures.
                    # Some of what it wrote was transcribed from audited results and
                    # some was estimated by the author -- the generator says so in
                    # its own comment, "FY26 values are estimates (unverified at
                    # fixture date)" -- but nothing in the workbook records WHICH
                    # is which, so this reader cannot tell a transcribed filing
                    # figure from a typed-in guess and must not claim to.
                    #
                    # Marking the newest year alone would be the more flattering
                    # choice and would still be a false claim about the earlier
                    # ones. The reader is also why `reported` was defensible for the
                    # genuine Screener.in exports it was written for, and why it is
                    # not here: it was reused for a file of a different kind.
                    status: Status = "estimated"
                    offset = k + 2  # column B (index 1) is first period
                    col = openpyxl.utils.get_column_letter(offset + 1)
                    datapoints.append(
                        RawDatapoint(
                            id=_datapoint_id(company_id, label, _period_label(period), "screener", section, j + 1),
                            company_id=company_id,
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