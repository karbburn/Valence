from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

import pdfplumber

from backend.data.store import RawDatapoint

LABEL_X_MAX = 330.0  # left of this = label text; right = value columns

# A note reference: dotted, optionally with a letter. `3.5`, `3.4(a)`, `2.12`.
#
# The figures in these statements are comma-grouped (`2,487`), parenthesised (`(215)`) or bare
# integers standing in a dense aligned column (`59`, `971`), so the dotted shape separates a
# reference from a figure and the column position confirms it.
_NOTE_SHAPE = re.compile(r"^\d+(?:\.\d+)+(?:\([a-z]\))?$", re.I)

# A value column needs this many numeric tokens at one x to be a column rather than a coincidence.
_MIN_COLUMN_ROWS = 6
# How far left of a note reference the boundary goes, so the reference itself lands on the value
# side rather than exactly on the edge.
_NOTE_MARGIN = 4.0
# How close a numeric column must sit to a year header to count as a period column. This is what
# tells the NOTE column apart from a VALUE column, and density alone cannot: HCLTech printed 5
# carries eleven references in a column as dense as either of its two value columns.
_ANCHOR_PROXIMITY = 40.0

_SKIP_LABELS = {
    "three", "two", "year", "as", "the", "particulars",
    "mar", "note", "notes", "total",
}


def _datapoint_id(company_id: str, section: str, metric: str, period: str, source: str, page: int, label: str, value: float) -> str:
    return hashlib.sha1(f"{company_id}|{section}|{metric}|{period}|{source}|{page}|{label}|{value:.4f}".encode()).hexdigest()


def _numeric(token: str) -> float | None:
    s = token.replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(s)
    except ValueError:
        return None


def _value_columns(words, page_height: float) -> list[float]:
    """x positions of numeric columns that have a year header above them.

    The year header is the discriminator, not density. HCLTech printed 5 has eleven note
    references in a column at x=330, as dense as either of its value columns at 448 and 546, so
    a density scan alone cannot tell a note column from a period column -- and treating the note
    column as a value column is what put those references on the wrong side of the boundary in
    the first place.
    """
    hist: dict[float, int] = {}
    for w in words:
        if _numeric(w["text"]) is not None:
            key = float(int(w["x0"] // 2.0) * 2.0)
            hist[key] = hist.get(key, 0) + 1
    years = [
        float(w["x0"]) for w in words
        if re.fullmatch(r"20\d\d", w["text"]) and w["top"] < page_height * 0.5
    ]
    return [
        x for x, n in sorted(hist.items())
        if n >= _MIN_COLUMN_ROWS
        and any(abs(x - y) <= _ANCHOR_PROXIMITY for y in years)
    ]


def _caption_boundary(words, page_height: float) -> float:
    """`LABEL_X_MAX`, lowered only where a note reference is caught on the caption side.

    The boundary separates caption words from everything else. `parse_predicted_statement_page`
    already discards anything outside the year-anchor window, so a note reference on the VALUE
    side costs nothing, while one on the CAPTION side corrupts the caption -- "Investments
    3.4(b)" instead of "Investments" -- which is why HCLTech's captions fail to map.

    Measured across all four committed filings: Infosys prints its references at x=347.5 and
    357.7, safely right of 330, and TCS prints none at all, so both keep 330 exactly. HCLTech
    prints them at 327.2-335.8, which straddles it -- `3.4(b)` at 329.7 lands in the caption and
    `3.4(a)` at 330.0 does not. So the constant is wrong for exactly one of three layouts, and the
    fix lowers it for that one.

    **Only ever downward.** Raising it would move words from the discarded side into captions, and
    two placements that would have raised it were measured and rejected first:

      * the widest gap between x-clusters lands at 334->390 on HCLTech printed 5, to the RIGHT of
        the note column, so every reference would go into the caption. The caption's own internal
        spacing makes wider gaps than the gap that separates text from notes.
      * the right edge of the non-numeric words is 525-575 on every page, because ordinary words
        sit out in the value area too. It would have swallowed the figures.

    A page with no detected value column returns the constant untouched. That is what keeps the
    two Infosys NOTES pages safe: their `1.1`, `1.2` tokens are numbered list items in prose at
    x=40, and treating them as references would have moved the boundary to 36 and pulled 255
    words into captions.
    """
    if not _value_columns(words, page_height):
        return LABEL_X_MAX
    columns = _value_columns(words, page_height)
    leftmost = None
    for w in words:
        if not _NOTE_SHAPE.match(w["text"]):
            continue
        if any(abs(w["x0"] - c) <= 2.0 for c in columns):
            continue
        if leftmost is None or w["x0"] < leftmost:
            leftmost = w["x0"]
    if leftmost is None or leftmost >= LABEL_X_MAX:
        return LABEL_X_MAX
    return leftmost - _NOTE_MARGIN


def _year_anchors(page, boundary: float = LABEL_X_MAX) -> list[tuple[float, int]]:
    """All fiscal-year value columns: [(x, year)] sorted by x."""
    words = page.extract_words()
    by_top: dict[float, list[tuple[float, str]]] = {}
    for w in words:
        by_top.setdefault(round(w["top"], 1), []).append((w["x0"], w["text"]))
    anchors: list[tuple[float, int]] = []
    for key in sorted(by_top):
        ws = sorted(by_top[key], key=lambda t: t[0])
        for x, t in ws:
            if x >= boundary and re.fullmatch(r"20\d\d", t):
                anchors.append((x, int(t)))
    anchors.sort()
    if not anchors:
        raise ValueError("no fiscal-year header row found")
    return anchors


# How far apart a caption's words and its figures may sit and still be one row.
#
# This number is measured, not chosen. On Infosys' FY26 balance sheet (p.100):
#
#     spread WITHIN one printed line          0.00 pt
#     caption -> its own figures              0.12 pt   <- the defect
#     page title -> the date-header below it  0.72 pt   <- must not be bridged
#     one printed line -> the next            ~8.8 pt
#
# The 0.12pt gap is the defect: `round(top, 1)` puts a caption at 108.9 and its
# figures at 109.0, in different buckets, and each half is then dropped for having no
# counterpart. p.100 yields 60 captions where it yields 86.
#
# A fixed window cannot fix it, because the 0.72pt gap must NOT be bridged and no
# threshold separates 0.12 from 0.72 in a way that holds across layouts. See `_rows`,
# which now takes the printed line exactly and records the consequence.
#
# MEASURED on backend/data/filings/infosys-fy26-q4-outcome.pdf p.100, by
# assets/gsd/spread.py.


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


def _rows(page, boundary: float = LABEL_X_MAX) -> list[tuple[str, list[tuple[float, str]], float, float]]:
    """Group words into caption-and-figures rows, with each row's own `top`.

    The coordinate is returned because it is the only thing that distinguishes two
    printed lines carrying the same caption. Infosys prints "- Mutual fund units"
    twice on printed page 104, once inside a note with the figures in parentheses
    and once inside another with them plain, and both readings are correct:

        y=573.75  - Mutual fund units (72,878) (73,048)
        y=640.02  - Mutual fund units 72,682 73,987

    A row identified as "p.104 - Mutual fund units" names both of them, so a re-ingest
    cannot collapse one into the other and cannot tell a duplicate from a second
    real line. The coordinate is what makes a row's identity recoverable.

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

    MEASURED, AND THE MEASUREMENT SAYS A FIXED WINDOW CANNOT DO IT. The gaps that
    have to be told apart are the same size:

        spread WITHIN one printed line          0.00 pt
        caption -> its own figures              0.12 pt   <- must be bridged
        page title -> the date-header below it  0.72 pt   <- must NOT be bridged

    At 3.0pt the second is bridged too, and the merged row then reads the date
    header's "31," as a figure of 31.0 -- a year fragment published as a
    balance-sheet line. On the FY25 PDF the title sits closer still, so no fixed
    window is safe across layouts, and on the profit-and-loss page the columns sit
    differently again, enough that a share count (4,120,108,168) is read as rupees.

    So this takes the printed line exactly as pdfplumber reports it, loses the
    captions that straddle a rounding boundary, and lets `current_assets_reconcile`
    report the shortfall. Under-counting a statement is visible and checkable; a
    caption quietly merged with a neighbour's numbers is published as fact.

    Fixing it properly means grouping on the printed baseline rather than on `top`:
    ruling detection, or the row rectangles the PDF draws. Recorded in
    assets/gsd/OPEN_DEFECTS.md with the measurements and the cost of leaving it.
    """
    words = page.extract_words()
    by_top: dict[float, list[tuple[float, str]]] = {}
    for w in words:
        by_top.setdefault(round(w["top"], 1), []).append((w["x0"], w["text"]))
    out = []
    for key in sorted(by_top):
        ws = sorted(by_top[key], key=lambda t: t[0])
        label = " ".join(t for x, t in ws if x < boundary).strip()
        vals = [(x, t) for x, t in ws if x >= boundary]
        if not label:
            continue
        # The caption's own left edge, which is the ONLY nesting signal in the document.
        #
        # TCS prints three levels deep and HCLTech two:
        #
        #     x0 79.7   Financial assets
        #     x0 87.0     Trade receivables
        #     x0 94.2       Billed        3.5   2,487   2,284
        #     x0 94.2       Unbilled      3.5     839     739
        #
        # A flat (caption, values) pair cannot tell "Trade receivables heads these two" from
        # "Trade receivables is a line in its own right", so the parser emitted the parent
        # with no value and the children as though they were top-level captions. Measured on
        # the four committed pages that nest: 22 nested parents, none of which prints a
        # figure of its own, so every one of those parents was silently losing its amount.
        #
        # Recorded rather than used yet. The roll-up that consumes this is a separate change,
        # and keeping them apart means this one is provably output-neutral: Infosys is flat at
        # one indent throughout, so a field nothing reads cannot change a single row.
        indent = min((x for x, _ in ws if x < boundary), default=0.0)
        if not any(re.match(r"[-(\d]", t) for _, t in vals):
            # A row of words with no figure is usually a section header -- and the
            # balance sheet's "Current assets" / "Non-current assets" headers are
            # exactly that. They are dropped by the figure test, which is why
            # every caption came back with no half: the disambiguator was being
            # thrown away by the filter that keeps actual data rows.
            if _balance_sheet_half(label) is not None:
                out.append((label, [], key, indent))
            continue
        out.append((label, vals, key, indent))
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
        # One boundary for the page, decided once and used by both the anchor search and the
        # caption split, so the two cannot disagree about which tokens are figures.
        boundary = _caption_boundary(page.extract_words(), page.height)
        anchors = _year_anchors(page, boundary)
        annual_x = {a[0] for a in (anchors[len(anchors) // 2:] if annual_only else anchors)}
        lo_x = anchors[0][0] - 50.0
        hi_x = anchors[-1][0] + 50.0

        dps: list[RawDatapoint] = []
        seen: set[tuple[str, str, float]] = set()
        # Tracked across the rows rather than per-row, because the boundary is a
        # header that appears once and governs everything printed after it.
        half: str | None = None
        for raw_label, vals, _row_top, _indent in _rows(page, boundary):
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
                        # The LINE, not the page and the caption. Two printed lines
                        # can carry one caption, so the page and the caption do not
                        # identify a row; see `_rows`. Never remove a correct figure
                        # is easier to honour once a row can be told from its twin.
                        source_location=(
                            f"{Path(pdf_path).name} p.{page_index + 1} y={_row_top:.1f} "
                            f"{label}" + (f" [{half}]" if half else "")
                        ),
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
