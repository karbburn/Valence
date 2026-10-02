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


# How far apart a caption's words and its figures may sit and still be one row.
#
# A printed table puts them on one baseline, but pdfplumber reports their `top`
# coordinates with sub-point drift. See `_rows`.
_ROW_TOLERANCE_PT = 3.0


# Headers a balance sheet prints to open its current and non-current halves.
#
# These are the disambiguator for captions that appear on BOTH sides under the same
# name. Infosys prints:
#
#     Current assets
#         Unbilled revenue      15,483        <- current
#         Income tax assets      1,835        <- current
#     Non-current assets
#         Unbilled revenue       1,738        <- non-current
#         Income tax assets        666        <- non-current
#
# Both members of each pair map to ONE canonical key, so without the boundary the
# later row overwrites the earlier and a reader is shown the non-current figure as
# if it were the current one. The header is printed by the filer, so this is the
# statement answering the question rather than the parser guessing from position.
_CURRENT_HEADER = re.compile(r"^\s*current assets\s*$", re.I)
_NONCURRENT_HEADER = re.compile(r"^\s*non[\s-]*current assets\s*$", re.I)


def _balance_sheet_half(label: str) -> str | None:
    """Which half of a balance sheet a caption sits in, from the printed headers.

    Returns "current", "noncurrent", or None when the caption precedes both headers
    or is not a balance sheet at all. None means no claim, and absence of a claim
    is not evidence against a mapping.
    """
    if _CURRENT_HEADER.match(label):
        return "current"
    if _NONCURRENT_HEADER.match(label):
        return "noncurrent"
    return None


def _clean_label(label: str) -> str:
    label = re.sub(r"\s+\d+\.\d+\s*$", "", label)  # trailing note ref
    label = re.sub(r"^\d+\.\d+\s+", "", label)      # leading note ref
    return label.strip()


def _rows(page) -> list[tuple[str, list[tuple[float, str]]]]:
    """Group words into caption-and-figures rows.

    Grouping is by `top`, rounded to 0.1pt, because a table row's words share a
    baseline closely enough for that to separate one line from the next.

    It was also EXACTLY that, and that split Infosys' current assets in half. pdfplumber
    reports a caption and its figures at marginally different `top` values:

        top=108.9  [(70.3, 'Prepayments'), (107.6, 'and'), ..., (156.5, 'assets')]
        top=109.0  [(349.1, '2.4'), (443.8, '15,703'), (506.3, '12,986')]

    Rounding to a tenth did not merge them, so the label formed one row with no
    values and was dropped, and the figures formed another with no label and were
    dropped. "Prepayments and other current assets 15,703" never became a datapoint
    at all -- which is why the line was EMPTY, and why the cash-flow statement's
    "Prepayments and other assets (2,312)" was the only thing left to fill it.

    Captions on a real financial statement are within a couple of points of their
    own figures. 3pt is comfortably inside that and far below the ~12pt line
    spacing, so genuine neighbours still separate.
    """
    words = page.extract_words()
    rows: list[list[tuple[float, str]]] = []
    anchors: list[float] = []  # the `top` each open row was started at
    for w in sorted(words, key=lambda t: t["top"]):
        if rows and abs(anchors[-1] - w["top"]) <= _ROW_TOLERANCE_PT:
            rows[-1].append((w["x0"], w["text"]))
        else:
            rows.append([(w["x0"], w["text"])])
            anchors.append(w["top"])

    out = []
    for ws in rows:
        ws.sort(key=lambda t: t[0])
        label = " ".join(t for x, t in ws if x < LABEL_X_MAX).strip()
        vals = [(x, t) for x, t in ws if x >= LABEL_X_MAX]
        if not label:
            continue
        if not any(re.match(r"[-(\d]", t) for _, t in vals):
            # A row of words with no figure is usually a section header -- and the
            # balance sheet's "Current assets" / "Non-current assets" headers are
            # exactly that. They are dropped by the figure test, which is why
            # every caption came back with no half: the disambiguator was being
            # thrown away by the filter that keeps actual data rows.
            if _balance_sheet_half(label) is not None:
                out.append((label, []))
            continue
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
        # Tracked across the rows rather than per-row, because the boundary is a
        # header that appears once and governs everything printed after it.
        half: str | None = None
        for raw_label, vals in _rows(page):
            label = _clean_label(raw_label)
            low = label.lower()
            if not label or low in _SKIP_LABELS or re.fullmatch(r"\d+\.\d+", label):
                continue

            header_half = _balance_sheet_half(label)
            if header_half is not None:
                half = header_half
                continue  # the header carries no figure of its own
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
                        source_location=f"{Path(pdf_path).name} p.{page_index + 1} {label}"
                                     + (f" [{half}]" if half else ""),
                        section=section,
                        # Which half of the balance sheet this caption was printed
                        # in, from the filer's own "Current assets" / "Non-current
                        # assets" headers. Disambiguates a caption printed on both
                        # sides under one name.
                        bs_half=half,
                        status="reported",
                        update_date=datetime.now(),
                    )
                )
        return dps
