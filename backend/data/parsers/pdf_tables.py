from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime
from pathlib import Path

import pdfplumber

from backend.data.store import RawDatapoint

logger = logging.getLogger(__name__)

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

# How much vertical space two word boxes must share to count as one printed line.
#
# Not a gap threshold. A gap cannot work here: TCS's split rows sit at 0.70-1.50pt while
# Infosys has pairs that must stay apart at 0.60-0.70pt, so the ranges overlap. This is a
# band, not a distance -- two words share a printed line when their boxes share vertical space.
# Measured on five statement pages: 71 of 71 split pairs overlap, and every one of the 4 pairs
# that overlap without being split has caption text on BOTH sides, which is the second condition
# `_merge_split_buckets` requires.
_MIN_LINE_OVERLAP = 0.5

# How much of the shorter band must overlap before two buckets that BOTH carry a
# caption, or BOTH carry only figures, may be called one printed line.
#
# The one-sided-caption rule keeps the measured 0.5pt floor: 71 of 71 split pairs
# clear it and the four signature-block pairs never satisfy the caption condition.
# The two split shapes that rule cannot see need a stricter number, because the
# false positive is a different animal: a share-capital block stacks captioned
# lines 5.9pt apart, so their bands overlap 1.06pt, while one printed line sliced
# across buckets overlaps its whole band (measured on HCLTech printed 4: the
# orphaned "of" overlaps 7.005 of 7.005, the split share-capital figures 6.700 of
# 6.700, the split "73"/"66" figures 6.450 of 6.700). One point of slack keeps
# every measured split and rejects the weld with a 5pt margin on both sides.
_SAME_LINE_SLACK = 1.0

# A bare fiscal year, which is what a statement's date header is made of. Used to refuse to
# bridge that row, since the page title above it satisfies every other merge condition.
_YEAR_HEADER = re.compile(r"^20\d\d$")

# A month name, which is what a date fragment is made of.
#
# The year guard is not enough on its own. A statement prints its period header on TWO lines --
# the fiscal years on one, "Year ended March 31," on the line above with the page title -- and the
# line carrying the title and the date has no year token on it:
#
#   top=62.2  INFOSYS LIMITED ... Statement of Profit and Loss for the
#   top=62.5  31, March        Note No.
#   top=73.3  2026  2025
#
# Bridging the first two satisfies every other condition, and the merged row then publishes the
# date fragment's "31," as a figure of 31.0 -- a page number wearing a caption, which is the
# exact failure the old 3.0pt window produced and the reason this function is careful.
_MONTH = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*$", re.I
)

# A caption that ends in a bare run of three or more digits is an identifier.
#
# Infosys printed 180 prints the auditor's report on the same page as the statement, so
# "Membership No. 060408" reaches the caption column, and the figures beside it include a DIN --
# "00019437" parses as 19437, which would be published as a profit-and-loss line.
#
# Measured across the seven committed statement pages and all 267 captions, this matches exactly
# one, and it is the auditor's. It is safe because a financial caption cannot end in a bare digit
# run: the note reference belongs in its own column, which the per-page boundary guarantees.
_IDENTIFIER_CAPTION = re.compile(r"\d{3,}$")

# What a filing says about its own units, read from the page rather than assumed.
#
# This function exists because the units used to be hardcoded:
#
#     currency="INR", units="crores"
#
# on every row of every filing the parser reads. That is a claim the parser cannot verify, and for
# at least one committed filing it is false. `hcltech-ifrs-2026-07.pdf` carries this header on both
# of its balance-sheet pages:
#
#     HCL Technologies Limited  Condensed Consolidated Interim Balance Sheet
#     (All amounts in millions of USD, except share data and as stated otherwise)
#
# so every one of its figures was recorded as INR crores. One USD million is roughly 8.3 INR crores,
# so the whole balance sheet was understated by about eight times while looking entirely ordinary,
# and -- because every row carried the SAME wrong label -- the model looked perfectly consistent to
# `check_units_agree_within_a_model`. The guard was not missing. It was being lied to, uniformly, by
# the parser.
#
# The fix is to stop asserting and start reading. What a page declares is separated into a SCALE and
# a CURRENCY, because they are independent and because the two are not equally determinable:
#
#   * the SCALE is declared in words -- crore, lakh, million, thousand -- and is the one most likely
#     to be wrong by orders of magnitude, so it is read whenever it appears.
#   * the CURRENCY is declared by a symbol or a code -- Rs, INR, USD -- and TCS's rupee glyph does
#     not survive text extraction at all, printing as "( crore)" with nothing before it.
#
# So an absent currency symbol yields an EMPTY currency, never a default. An empty currency is not a
# parse failure; it is a recorded unknown, and it makes the model disagree with the INR feed rows,
# which is exactly what should happen when one of the two sources might not be in rupees.
#
# Measured across the ten committed statement pages: 10 of 10 declare a scale, 6 of 10 declare a
# currency. The four that do not are the two Infosys cash-flow pages, whose "(In Rs crore)" sits
# after an accounting-policy paragraph rather than in the header, and the two TCS balance sheets
# whose rupee glyph is missing. The search therefore runs over the whole page rather than the first
# line, because a declaration that appears mid-page is still a declaration.
_UNIT_DECLARATIONS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"in\s+(?:₹|rs\.?|inr|usd|\$)\s*crores?\b", re.I), "INR", "crores"),
    (re.compile(r"\(\s*(?:₹|rs\.?|inr)?\s*crores?\s*\)", re.I), "", "crores"),
    # HCLTech's audited Ind-AS balance sheet declares "(~ in crores)": the rupee
    # glyph extracts as "~", so the parenthesised form above finds no currency
    # and the pattern below finds none either. The parens are the declaration --
    # a bare "in crores" outside them is prose about units, not a statement of
    # this page's units, and stays refused.
    (re.compile(r"\([^)]{0,30}\bin\s+crores?\b[^)]{0,30}\)", re.I), "", "crores"),
    (re.compile(r"in\s+(?:₹|rs\.?|inr|usd|\$)\s*lakhs?\b", re.I), "INR", "crores"),
    (re.compile(r"in\s+millions?\s+of\s+(usd|inr|rs\.?)\b", re.I), "", "millions"),
    (re.compile(r"in\s+(usd|inr|rs\.?)\s+millions?\b", re.I), "", "millions"),
    (re.compile(r"in\s+thousands?\s+of\s+(usd|inr|rs\.?)\b", re.I), "", "thousands"),
)

_CURRENCY_IN_PHRASE = {
    "usd": "USD",
    "inr": "INR",
    "rs": "INR",
    "rs.": "INR",
    "₹": "INR",
}


def declared_units(page_text: str) -> tuple[str, str]:
    """The currency and scale a statement page declares about itself.

    Returns ``(currency, units)``, either of which may be empty, and both empty when the page
    declares nothing recognisable. Empty means NOT DETERMINED, never "assume rupees and crores" --
    that default is the defect this replaces.

    Deliberately conservative in two ways.

    It matches a whole declaration rather than a bare units word, because a units word also appears
    inside accounting-policy prose, inside a caption, and in the thousands separators of the
    figures themselves. Matching those would read a page as INR crores because it mentioned
    "lakh" in a note.

    And it never supplies a currency it did not see. TCS's balance sheet prints "( crore)" with the
    rupee glyph unextractable, so the scale is read and the currency is left empty.

    Self-tested against the four real headers plus phrases it must refuse; see
    `test_the_parser_reads_units_instead_of_asserting_them.py`, which also asserts that the detector
    refuses rather than guessing, since a rule that answers everything reproduces the bug on any
    filing it has not seen.
    """
    for rx, currency, units in _UNIT_DECLARATIONS:
        m = rx.search(page_text)
        if not m:
            continue
        if currency:
            return currency, units
        # The phrase named a currency of its own, or named only a scale. Either way the currency
        # comes from what was written, never from a default.
        for token, resolved in _CURRENCY_IN_PHRASE.items():
            if re.search(rf"\b{re.escape(token)}\b", m.group(0), re.I) or token in m.group(0):
                return resolved, units
        return "", units
    return "", ""

# A caption that names a COUNT of shares rather than an amount.
#
# The consolidated profit-and-loss page prints its earnings-per-share block in the same rupee
# columns as the rest of the statement:
#
#     Basic (in shares)     2.13   4,046,019,309   4,142,429,577
#     Basic (₹)             2.13        21.01          16.98
#
# Both rows sit in the value columns, so the share count is read as rupees and
# 4,046,019,309 reaches a line item. It is separated on what the CAPTION says, never on the
# magnitude of the number -- a share count is four thousand times a rupee figure here, and a
# small-cap earnings-per-share figure is the other way round, so scale decides nothing.
#
# Measured across all nine committed statement pages and 336 captions: 12 mention "share", and
# this drops 5 while keeping 7. Every kept one is an amount -- "Share premium", "Share capital",
# "Equity share capital", "Equity attributable to shareholders of the Company", "Class B
# compulsorily convertible preference shares", and the "(₹)" earnings-per-share rows, which never
# match because they do not say "share". Every dropped one is a count.
_SHARE_COUNT_CAPTION = re.compile(r"in shares|number of|outstanding|weighted", re.I)
_MENTIONS_SHARE = re.compile(r"share", re.I)

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
# MEASURED on backend/data/filings/infosys-fy26-q4-outcome.pdf p.100.


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


def _has_column_pairs(anchors: list[tuple[float, int]]) -> bool:
    """Do these year headers form quarterly/annual PAIRS, so only half are annual columns?

    `annual_only` used to keep `anchors[len//2:]` unconditionally, on the assumption that a
    profit-and-loss page always prints a quarter beside each year. Infosys printed 180 does not:
    it prints two headers, "2026 2025", and both are annual. `anchors[1:]` therefore kept one
    column and **discarded FY26 entirely**, so the statement the grouping fix had just recovered
    arrived with half its years missing.

    A pair needs at least two of them, so fewer than four headers cannot be pairs. That is the
    whole rule, and it is stated as a floor rather than a shape because the alternative --
    deciding from the spacing between columns -- has no measured justification behind it and the
    header tokens are identical either way.
    """
    return len(anchors) >= 4


def _merge_split_buckets(buckets: list[tuple[float, list[dict]]], boundary: float):
    """Join a caption and its figures when pdfplumber split one printed line in two.

    The defect this fixes, on Infosys printed 180:

        top=83.5   Revenue from operations   2.18        <- caption bucket
        top=83.6                148,819 136,592         <- figure bucket

    Two buckets, so the revenue figure never reaches its caption, the caption is emitted with no
    value, and the P&L yields no revenue at all. The same shape loses about a third of every
    statement: printed 100 produced 60 captions where the filing prints 86.

    **A threshold on the top gap cannot do this, and the measurement says so rather than
    implying it.** Across the five statement pages:

        infy printed 180 (P&L)   0.10pt x23, 0.20 x6, 0.30 x1, 0.40 x3, 0.50 x1
        infy printed 100 (BS)    0.10pt x14, 0.20 x1, 0.30 x1, 0.50 x1, 0.60 x1, 0.70 x1
        infy printed 104 (CF)    0.10pt x8,  0.20 x3, 0.30 x1, 0.40 x1, 0.50 x1, 0.60 x1
        tcs  printed 11  (BS)    0.70pt x2,  1.40 x1, 1.50 x1
        hcltech printed 5 (BS)   0.10pt x9,  0.20 x3

    TCS's split rows sit at 0.70-1.50pt while Infosys has pairs that must stay separate at
    0.60-0.70pt. The ranges overlap, so no threshold separates them on these documents. That is
    why the old 3.0pt window merged a page title into its date header and read the header's
    "31," as a figure of 31.0.

    **Vertical overlap does separate them, and only with a second condition.** Measured on the
    same five pages: 71 of 71 split pairs have vertically overlapping word boxes, and 4 pairs
    overlap that must NOT merge. All four are the audit report's signature block:

        [April 23, 2026] [Chief Financial Officer]
        [for and on behalf of the Board of] [for Deloitte Haskins & Sells LLP]
        [Jayesh Sanghrajka A.G.S. Manikanth] [Bengaluru]
        [DIN: 00041245] [Membership No. 060408 and Managing]

    Every one of them carries caption text on BOTH sides. Every true split row carries a caption
    on exactly ONE side and figures on the other. So both conditions are required: overlap alone
    would weld the auditors' signatures into one line, and gap alone cannot work at all. With
    both, the measurement is 71 true positives and zero false positives.

    Overlap rather than a gap because a printed line is a physical band. Two words are on the
    same line when their boxes share vertical space, whatever distance pdfplumber happens to
    report between their `top` values.

    **A second split shape exists, measured on HCLTech's audited Ind-AS balance sheet
    (printed page 4), and it is invisible to the one-sided-caption rule.** Three buckets
    carry one printed line there:

        top=471.6   543                 <- figure bucket (FY25 column)
        top=471.9   543                 <- figure bucket (FY26 column)
        top=472.3   (a ) Equity share capital    <- caption bucket

    The rule above rejoins caption to figures, so the last two buckets become one row --
    but the first sits two buckets back, its only neighbour is another figure-only
    bucket, and `prev_has_caption != this_has_caption` is false for both, so the FY25
    share capital never reaches its caption. The same shape loses "73" off
    "(e ) Other non-current liabilities", and a caption word that lands in its own
    bucket ("of" in "Equity attributable to owners of the Company", baseline
    490.604 against the line's 490.839) leaves both sides captioned, which the
    one-sided rule also refuses.

    So there are now two rules where there was one. Exactly one side owning the caption
    keeps the measured 0.5pt floor; the two new shapes -- both sides captioned with
    differing figure sets, and neither side captioned at all -- require the overlap to
    cover the whole shorter band (`_SAME_LINE_SLACK`), because the false positive for
    them is a share-capital block stacking captioned lines 5.9pt apart whose bands
    overlap only 1.06pt, while every measured same-line slice overlaps 6.2pt or more.
    Two caption-only buckets still never merge: that is the audit report's signature
    block, whose four overlapping pairs were measured as false positives before any
    figure condition existed.
    """
    merged: list[tuple[float, list[dict]]] = []
    for key, ws in buckets:
        if merged:
            prev_key, prev_ws = merged[-1]
            prev_top = min(w["top"] for w in prev_ws)
            prev_bottom = max(w["bottom"] for w in prev_ws)
            this_top = min(w["top"] for w in ws)
            this_bottom = max(w["bottom"] for w in ws)
            overlap = min(prev_bottom, this_bottom) - max(prev_top, this_top)
            prev_has_caption = any(w["x0"] < boundary for w in prev_ws)
            this_has_caption = any(w["x0"] < boundary for w in ws)
            prev_has_figures = any(w["x0"] >= boundary for w in prev_ws)
            this_has_figures = any(w["x0"] >= boundary for w in ws)
            prev_height = prev_bottom - prev_top
            this_height = this_bottom - this_top
            near_total = overlap > min(prev_height, this_height) - _SAME_LINE_SLACK
            # Never bridge a year header. The page title sits directly above the date header and
            # carries caption text while the header does not, so the two conditions above are
            # satisfied and it merges -- which is the failure this whole function exists to
            # avoid, arriving from the other direction:
            #
            #   Consolidated Balance Sheet as at | 2025 2026 31, 31, March March
            #
            # The header is the one row a statement reliably prints, and `_year_anchors` already
            # identifies it by exactly this token, so the guard reuses that rather than
            # introducing a second way to recognise the same row. A statement figure of 2,025
            # prints as "2,025" and is not a bare year, so no real value is excluded by this.
            touches_year = any(
                _YEAR_HEADER.search(w["text"]) or _MONTH.match(w["text"].strip(",."))
                for w in prev_ws
            ) or any(
                _YEAR_HEADER.search(w["text"]) or _MONTH.match(w["text"].strip(",."))
                for w in ws
            )
            if overlap > _MIN_LINE_OVERLAP and not touches_year and (
                prev_has_caption != this_has_caption
                or (
                    prev_has_caption == this_has_caption
                    and prev_has_figures != this_has_figures
                    and near_total
                )
                or (not (prev_has_caption or this_has_caption) and near_total)
            ):
                merged[-1] = (prev_key, prev_ws + ws)
                continue
        merged.append((key, ws))
    return merged


def _join_split_figures(vals: list[tuple[float, float, str]]) -> list[tuple[float, str]]:
    """Re-join a figure whose glyphs pdfplumber returned as separate words.

    The FY26 cash flow prints its acquisition payment as `(637)` with every glyph
    separately positioned (x0 457.4, 460.1, 464.2, 468.3, 472.4), so the extractor hands
    back five words: `(` `6` `3` `7` `)`. Each digit parses on its own and all five sit
    in the FY26 column, so one printed amount became three FY26 datapoints -- 6, 3 and 7 --
    and the store then kept whichever was written last, publishing a single-digit purchase
    against a filing that prints 637. The comparative `(3,155)` on the same line prints as
    one string and reads whole, which is how the split survived review: the figure that
    was checked was the one that read correctly.

    Tokens are rejoined while their EDGES are within 4pt. Measured on the two committed
    documents: split glyphs sit 0.9-1.8pt apart, and the nearest real neighbour of a
    figure is the next column's value 55pt away, so 4pt rejoins a number and cannot reach
    a second one -- a printed row carries one figure per column, which is the property
    that makes the distance safe. The join runs on the figure side only: a caption keeps
    its words and its note reference (`2 . 1 0` beside this very line, in the caption
    column), so a row's recorded identity does not move.
    """
    out: list[tuple[float, float, str]] = []
    for x, x1, t in vals:
        if out and x - out[-1][1] < 4.0:
            prev_x0, _prev_x1, prev_t = out[-1]
            out[-1] = (prev_x0, x1, prev_t + t)
        else:
            out.append((x, x1, t))
    return [(x, t) for x, _x1, t in out]


def _rows(page, boundary: float = LABEL_X_MAX) -> list[tuple[str, list[tuple[float, str]], float, float]]:
    """Group words into caption-and-figures rows, with each row's own `top` and indent.

    The coordinate is returned because it is the only thing that distinguishes two
    printed lines carrying the same caption. Infosys prints "- Mutual fund units"
    twice on printed page 104, once inside a note with the figures in parentheses
    and once inside another with them plain, and both readings are correct:

        y=573.75  - Mutual fund units (72,878) (73,048)
        y=640.02  - Mutual fund units 72,682 73,987

    A row identified as "p.104 - Mutual fund units" names both of them, so a re-ingest
    cannot collapse one into the other and cannot tell a duplicate from a second
    real line. The coordinate is what makes a row's identity recoverable.

    Grouping starts from pdfplumber's `top` rounded to 0.1pt, then rejoins the rows that are one
    printed line split across two of those buckets. `_merge_split_buckets` carries the
    measurement that a gap threshold cannot work here and that vertical overlap plus the
    one-sided-caption signature can.
    """
    words = page.extract_words()
    by_top: dict[float, list[dict]] = {}
    for w in words:
        by_top.setdefault(round(w["top"], 1), []).append(w)
    buckets = _merge_split_buckets(sorted(by_top.items()), boundary)

    out = []
    for key, bucket in buckets:
        ws = sorted(((w["x0"], w["x1"], w["text"]) for w in bucket), key=lambda t: t[0])
        label = " ".join(t for x, x1, t in ws if x < boundary).strip()
        vals = _join_split_figures([(x, x1, t) for x, x1, t in ws if x >= boundary])
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
        indent = min((x for x, _x1, _t in ws if x < boundary), default=0.0)
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


_GROUPED_FIGURE = re.compile(r"\d{1,3}(?:,\d+)+$")


def _grouping_is_readable(bare: str) -> bool:
    """True when a comma-grouped figure parses in either convention a filing uses.

    Western grouping puts three digits behind every comma (281,139); Indian
    grouping puts three behind the first comma and two behind the rest
    (2,81,139). A token matching neither groups no number a reader could
    verify: HCLTech's audited balance sheet prints its FY25 current-liabilities
    subtotal as "28,1139", whose components sum to 28,039 and whose own
    printed total (7,832 + 28,039 = 35,871) confirms the intent. Read as
    281,139 it would publish a reported figure eleven times its own arithmetic.
    """
    parts = bare.split(",")
    if not all(parts):
        return False
    if len(parts[0]) > 3:
        return False
    if all(len(p) == 3 for p in parts[1:]):
        return True
    return (
        len(parts) >= 3
        and len(parts[1]) == 2
        and all(len(p) == 3 for p in parts[2:])
    )


def _num(token: str) -> float | None:
    bare = token.strip().strip("()")
    if "," in bare and _GROUPED_FIGURE.match(bare) and not _grouping_is_readable(bare):
        # A figure whose grouping no convention can read is a recorded unknown,
        # not a number to guess at. The row keeps its other column, so the
        # shortfall lands where a missing subtotal belongs: visible.
        return None
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
    header_page_index: int | None = None,
) -> list[RawDatapoint]:
    """Parse one filing statement page into RawDatapoints for the given company.

    P&L pages carry quarterly + annual pairs; when annual_only we keep only the
    rightmost (year-ended) columns and drop quarterly ones. Values map to the
    nearest year anchor. ``period_end_month``/``period_end_day`` follow the
    company's fiscal calendar.

    ``header_page_index`` names the page whose fiscal-year header this page
    continues. A statement that runs past one printed page does not repeat its
    header on the continuation, so a continuation with no anchors of its own
    raises and its figures are never read -- which is how the financing half of
    Infosys' FY26 cash flow (lease payments, dividends, buybacks) was missing
    from the store while the operating half read cleanly. Naming the header page
    borrows that page's anchors instead. The borrow is tested against this page
    rather than trusted: it is accepted only when the page prints its own figures
    in the borrowed columns, so the note pages that follow a statement still
    raise instead of having prose parsed into periods.
    """
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        # One boundary for the page, decided once and used by both the anchor search and the
        # caption split, so the two cannot disagree about which tokens are figures.
        boundary = _caption_boundary(page.extract_words(), page.height)
        carried = False
        try:
            anchors = _year_anchors(page, boundary)
        except ValueError:
            if header_page_index is None:
                raise
            # The continuation of a statement whose header printed on an earlier page. The
            # header page is read the same way this page would have been, so the borrowed
            # columns are established by the filer's own header row and not by this page's
            # layout. A header page with no header of its own raises here, honestly.
            header = pdf.pages[header_page_index]
            anchors = _year_anchors(
                header, _caption_boundary(header.extract_words(), header.height)
            )
            carried = True
        annual_x = {
            a[0] for a in (
                anchors[len(anchors) // 2:] if annual_only and _has_column_pairs(anchors)
                else anchors
            )
        }
        lo_x = anchors[0][0] - 50.0
        hi_x = anchors[-1][0] + 50.0
        if carried:
            # The borrow, tested against this page rather than trusted. Without this any
            # page the caller names would parse in the borrowed window, and the page after
            # a statement is a note: measured on the committed Infosys documents, the real
            # continuations print 13 figure rows and 24 figures inside the carried
            # columns, while the note pages that follow print 0, 0, 0 and 1 -- the one being
            # half a sentence of prose at 2.10, which is exactly the confident junk this
            # refuses. A continuation with fewer than two figure rows does not exist in
            # either committed document; refusing it keeps an honest failure over a
            # plausible answer.
            figure_rows = sum(
                1
                for _lab, vals, _t, _ind in _rows(page, boundary)
                if any(lo_x <= x <= hi_x and _num(t) is not None for x, t in vals)
            )
            if figure_rows < 2:
                raise ValueError(
                    f"no fiscal-year header row on this page, and the columns carried "
                    f"from printed page {header_page_index + 1} hold {figure_rows} "
                    f"figure row(s): this page does not continue that statement"
                ) from None

        # What the page says about its own units, read rather than assumed. See
        # `declared_units`. Either component may be empty, and empty means undetermined.
        page_currency, page_units = declared_units(
            re.sub(r"\s+", " ", " ".join(w["text"] for w in page.extract_words()))
        )
        if not (page_currency or page_units) and header_page_index is not None:
            # The units banner prints once, on the statement's first page, and the
            # continuation belongs to that statement -- so its figures are in the units
            # that page declared. Measured on the committed Infosys documents: printed
            # 104 reads INR/crores and printed 105 prints no banner at all, and rows
            # arriving with no units are refused downstream by the company's own
            # currency/units check -- a correct guard aimed at the wrong layer, which
            # would turn a read continuation into a failed normalization for the whole
            # company. The page's own banner, when it prints one, still wins.
            header_text = re.sub(
                r"\s+", " ",
                " ".join(w["text"] for w in pdf.pages[header_page_index].extract_words()),
            )
            page_currency, page_units = declared_units(header_text)

        # A scale of crores with no readable currency, on an NSE filing, is
        # INR. The crore exists only in the Indian numbering system, and NSE
        # filings report in rupees by construction: TCS prints "( crore)"
        # with the rupee glyph unextractable, so the scale is read and the
        # currency is genuinely absent from anything this can see. Resolving
        # the denomination's home currency is reading, not assuming -- but
        # only with the source in hand, which is why this lives here where
        # `source` is known and not in `declared_units`, whose TCS test pins
        # that an undetermined currency stays empty. Any other source keeps
        # the empty string and stays refused downstream.
        if not page_currency and page_units == "crores" and source == "nse_filing":
            page_currency = "INR"

        dps: list[RawDatapoint] = []
        seen: set[tuple[str, str, float]] = set()
        # Which (caption, period) has already been claimed, and by WHICH printed column.
        #
        # The column is the whole point, and getting it wrong is what an earlier attempt at this
        # did. A page can print one caption twice for two entirely different reasons:
        #
        #   * two COLUMNS -- two dates. HCLTech printed 5 compares "30 June 2026" with
        #     "31 March 2026"; `_year_anchors` matches only the year, so both label FY26. One of
        #     them is a period the engine cannot represent, and emitting both puts 11,806 and
        #     12,261 in the store as two FY26 total-assets rows.
        #
        #   * two ROWS in the SAME column -- a caption appearing in both the current and the
        #     non-current half of one page. `bs_half` exists to disambiguate those, both are real,
        #     and dropping either loses a figure.
        #
        # The earlier version treated both as the same thing and silently discarded eleven
        # legitimate TCS captions. So the drop is keyed on the column, and only across columns.
        _claimed: dict[tuple[str, str], float] = {}
        _collisions: list[tuple[str, str, float, float]] = []
        # Tracked across the rows rather than per-row, because the boundary is a
        # header that appears once and governs everything printed after it.
        half: str | None = None
        for raw_label, vals, _row_top, _indent in _rows(page, boundary):
            label = _clean_label(raw_label)
            low = label.lower()
            if not label or low in _SKIP_LABELS or re.fullmatch(r"\d+\.\d+", label):
                continue
            if _IDENTIFIER_CAPTION.search(label):
                # An identifier, not a line item. Printed 180 carries the auditor's report as
                # well as the statement, and "Membership No. 060408" reaches the caption column
                # because its figures include a DIN -- a digit run that parses as 19437 and would
                # otherwise be published as a profit-and-loss line.
                #
                # A caption ending in a bare digit run is safe to reject because a financial
                # caption cannot end in one: its note reference lives in a separate column, which
                # the per-page boundary now guarantees. Measured across the seven statement pages
                # and 267 captions, this matches exactly one caption and it is the auditor's.
                continue
            if _MENTIONS_SHARE.search(label) and _SHARE_COUNT_CAPTION.search(label):
                # A count of shares, not an amount. Printed in the same value columns as the
                # rupee figures on the earnings-per-share block and beside the share-capital
                # line, so without this a share count reaches a line item as rupees.
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
                key = (label, period_label)
                claimed_by = _claimed.get(key)
                if claimed_by is not None and abs(claimed_by - nearest_x) > 0.5:
                    # A DIFFERENT printed column has already claimed this period for this caption.
                    # The first column wins -- leftmost, which is the reporting date on both the
                    # Indian interim layout and the comparative layout -- and the drop is counted so
                    # it is reported rather than happening silently.
                    _collisions.append((label, period_label, v, nearest_x))
                    continue
                _claimed.setdefault(key, nearest_x)
                seen.add((label, period_label, v))
                dps.append(
                    RawDatapoint(
                        id=_datapoint_id(company_id, section, label, period_label, source, page_index, label, v),
                        company_id=company_id,
                        metric_raw=label,
                        period_label=period_label,
                        period_end_date=period_end,
                        value=v,
                        currency=page_currency,
                        units=page_units,
                        source=source,  # type: ignore[arg-type]
                        # The LINE, not the page and the caption. Two printed lines
                        # can carry one caption, so the page and the caption do not
                        # identify a row; see `_rows`. Never remove a correct figure
                        # is easier to honour once a row can be told from its twin.
                        source_location=(
                            f"{Path(pdf_path).name} p.{page_index + 1} y={_row_top:.1f} "
                            f"{label}" + (f" [{half}]" if half else "")
                            # The units are a claim about the row, so where they came from belongs
                            # with the row. Without this, an empty currency is indistinguishable
                            # from a currency nobody looked for.
                            + (f" [{(page_currency + '/' + page_units).strip('/')}]"
                               if (page_currency or page_units) else " [units undetermined]")
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
        if _collisions:
            # Loud, because silence here is what the defect looked like.
            #
            # A dropped comparative is a real loss -- a period the filing prints and the model does
            # not have -- and it must not read as "the filing only showed one period". So it is
            # reported with the caption count, the page, and an example of what was discarded.
            #
            # The engine-wide consequence is unchanged and is the larger one: the period model has
            # no quarter, so a page comparing June 2026 with a March 2026 year-end cannot be
            # represented at all. Recording the drop is what preferring a recorded unknown to a
            # silent collision looks like; extending the period model to quarters is the other
            # answer and is not built.
            logger.warning(
                "%s printed page %s: %d figure(s) came from a second printed column that this "
                "engine cannot represent, and were dropped rather than relabelled onto the first. "
                "Example: %r at x=%.1f. The filing compares two period-ends and the period model "
                "holds one, so one date is genuinely absent from the model.",
                company_id, page_index + 1, len(_collisions),
                _collisions[0][0], _collisions[0][3],
            )
        return dps
