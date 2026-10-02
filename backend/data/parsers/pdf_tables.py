from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

import pdfplumber

from backend.data.store import RawDatapoint

LABEL_X_MAX = 330.0  # left of this = label text; right = value columns

_SKIP_LABELS = {
    "three", "two", "year", "as", "the", "particulars",
    "mar", "note", "notes", "total",
}


def _datapoint_id(company_id: str, section: str, metric: str, period: str, source: str, page: int, label: str, value: float) -> str:
    return hashlib.sha1(f"{company_id}|{section}|{metric}|{period}|{source}|{page}|{label}|{value:.4f}".encode()).hexdigest()


def _year_anchors(page) -> list[tuple[float, int]]:
    """All fiscal-year value columns: [(x, year)] sorted by x."""
    words = page.extract_words()
    by_top: dict[float, list[tuple[float, str]]] = {}
    for w in words:
        by_top.setdefault(round(w["top"], 1), []).append((w["x0"], w["text"]))
    anchors: list[tuple[float, int]] = []
    for key in sorted(by_top):
        ws = sorted(by_top[key], key=lambda t: t[0])
        for x, t in ws:
            if x >= LABEL_X_MAX and re.fullmatch(r"20\d\d", t):
                anchors.append((x, int(t)))
    anchors.sort()
    if not anchors:
        raise ValueError("no fiscal-year header row found")
    return anchors


def _clean_label(label: str) -> str:
    label = re.sub(r"\s+\d+\.\d+\s*$", "", label)  # trailing note ref
    label = re.sub(r"^\d+\.\d+\s+", "", label)      # leading note ref
    return label.strip()


def _rows(page) -> list[tuple[str, list[tuple[float, str]]]]:
    words = page.extract_words()
    by_top: dict[float, list[tuple[float, str]]] = {}
    for w in words:
        by_top.setdefault(round(w["top"], 1), []).append((w["x0"], w["text"]))
    out = []
    for key in sorted(by_top):
        ws = sorted(by_top[key], key=lambda t: t[0])
        label = " ".join(t for x, t in ws if x < LABEL_X_MAX).strip()
        vals = [(x, t) for x, t in ws if x >= LABEL_X_MAX]
        if label and any(re.match(r"[-(\d]", t) for _, t in vals):
            out.append((label, vals))
    return out


def _num(token: str) -> float | None:
    s = token.replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(s)
    except ValueError:
        return None


def _period_label(d: date) -> str:
    return f"FY{str(d.year)[2:]}"


def parse_predicted_statement_page(
    pdf_path: str | Path,
    page_index: int,
    section: str,
    source: str,
    annual_only: bool = True,
    company_id: str = "infy_infy",
    period_end_month: int = 3,
    period_end_day: int = 31,
) -> list[RawDatapoint]:
    """Parse one filing statement page into RawDatapoints for the given company.

    P&L pages carry quarterly + annual pairs; when annual_only we keep only the
    rightmost (year-ended) columns and drop quarterly ones. Values map to the
    nearest year anchor. ``period_end_month``/``period_end_day`` follow the
    company's fiscal calendar.
    """
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        anchors = _year_anchors(page)
        annual_x = {a[0] for a in (anchors[len(anchors) // 2:] if annual_only else anchors)}
        lo_x = anchors[0][0] - 50.0
        hi_x = anchors[-1][0] + 50.0

        dps: list[RawDatapoint] = []
        seen: set[tuple[str, str, float]] = set()
        for raw_label, vals in _rows(page):
            label = _clean_label(raw_label)
            low = label.lower()
            if not label or low in _SKIP_LABELS or re.fullmatch(r"\d+\.\d+", label):
                continue
            for x, tok in vals:
                if not (lo_x <= x <= hi_x):
                    continue  # note-reference column, not a figure
                v = _num(tok)
                if v is None:
                    continue
                nearest_x = min(anchors, key=lambda a: abs(a[0] - x))[0]
                if nearest_x not in annual_x:
                    continue
                year = next(a[1] for a in anchors if a[0] == nearest_x)
                period_end = date(year, period_end_month, period_end_day)
                period_label = _period_label(period_end)
                if (label, period_label, v) in seen:
                    continue  # identical line printed twice on the page
                seen.add((label, period_label, v))
                dps.append(
                    RawDatapoint(
                        id=_datapoint_id(company_id, section, label, period_label, source, page_index, label, v),
                        company_id=company_id,
                        metric_raw=label,
                        period_label=period_label,
                        period_end_date=period_end,
                        value=v,
                        currency="INR",
                        units="crores",
                        source=source,  # type: ignore[arg-type]
                        source_location=f"{Path(pdf_path).name} p.{page_index + 1} {label}",
                        section=section,
                        status="reported",
                        update_date=datetime.now(),
                    )
                )
        return dps
