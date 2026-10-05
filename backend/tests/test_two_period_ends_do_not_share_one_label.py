"""Two printed columns with different period-ends must not share one period label.

The defect, confirmed against the documents in section 26 and diagnosed in section 27.

HCLTech's balance sheet compares two DIFFERENT dates:

    printed page 5    30 June 2026   and   31 March 2026
    printed page 6    30 June 2026   and   31 March 2026

and both arrive in the store as FY26. TCS and Infosys, which compare March 2026 with March 2025, are
correctly labelled FY26 and FY25 -- so this is HCLTech-only and a fix for one would break the other.

The cause is a stacked pair:

    `_year_anchors` matches only `re.fullmatch(r"20\\d\\d", t)`, so "30 June 2026" and
    "31 March 2026" both yield the anchor year 2026 and the month that distinguishes them is
    discarded at the point of reading. Its return type, `list[tuple[float, int]]`, has no room for
    one.

    `_period_label` is `f"FY{str(d.year)[2:]}"`, which cannot express a difference between March and
    June even when the month is captured. Under the project's convention FY26 is the year ending
    March 2026, so June 2026 is FY27 -- a period the engine does not model.

So the defect is not that the label is wrong. It is that the parser **silently** relabels a column
it cannot represent. Both of HCLTech's dates are real, both rows look valid, and every guard in the
codebase passes.

These tests assert the property, not a fix. The fix depends on a decision this project has not
taken: refuse the comparative and say so, or extend the period model to quarters. Nothing here
encodes that choice, and nothing here should be "fixed" by making these pass.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pdfplumber

import pytest

sys.path.insert(0, ".")

from backend.data.parsers.pdf_tables import (  # noqa: E402
    _year_anchors,
    parse_predicted_statement_page,
)

HCLTECH = Path("backend/data/filings/nse/hcltech-ifrs-2026-07.pdf")
TCS = Path("backend/data/filings/nse/tcs-outcome-2026-04.pdf")
INFOSYS = Path("backend/data/filings/infosys-fy26-q4-outcome.pdf")

needs_hcl = pytest.mark.skipif(not HCLTECH.exists(), reason="no HCLTech filing committed")
needs_tcs = pytest.mark.skipif(not TCS.exists(), reason="no TCS filing committed")

MONTH = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

DATE_HEAD = re.compile(
    r"(\d{1,2})\s+([A-Za-z]{3,9}),?\s+(20\d\d)|([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(20\d\d)"
)


def _column_dates(page) -> list[tuple[int, int]]:
    """The distinct (month, year) dates printed in the page's header region."""
    text = re.sub(r"\s+", " ", " ".join(w["text"] for w in page.extract_words()))[:700]
    found: list[tuple[int, int]] = []
    for m in DATE_HEAD.finditer(text):
        if m.group(1):
            _day, mon, year = m.group(1), m.group(2), m.group(3)
        else:
            mon, _day, year = m.group(4), m.group(5), m.group(6)
        month = MONTH.get(mon.lower())
        if month:
            pair = (month, int(year))
            if pair not in found:
                found.append(pair)
    return found


def _labels_for(pdf: Path, index: int, company_id: str) -> set[str]:
    dps = parse_predicted_statement_page(
        str(pdf), index, "BALANCE SHEET", "nse_filing", annual_only=False,
        company_id=company_id,
    )
    return {d.period_label for d in dps}


@needs_hcl
@pytest.mark.xfail(
    strict=True,
    reason=(
        "CONFIRMED DEFECT, sections 26 and 27. HCLTech compares 30 June 2026 with 31 March 2026; "
        "both arrive as FY26. The comparative is lost and the balance sheet double-counts, with no "
        "guard in the codebase objecting. Marked xfail(strict) rather than deleted because the "
        "fix depends on a decision this project has not taken -- refuse the comparative and record "
        "that, or extend the period model to quarters. Strict so that landing either fix without "
        "updating this marker fails the suite, and so the defect cannot be quietly forgotten."
    ),
)
@pytest.mark.parametrize("index", [4, 5], ids=["printed-5", "printed-6"])
def test_two_different_period_ends_do_not_both_become_fy26(index):
    """The property, asserted on the two pages that violate it.

    Reads the dates the page prints and the labels the store receives, and compares. Nothing here is
    hardcoded to HCLTech's particular dates: if the filing changes its comparatives the test follows,
    and if the parser starts distinguishing them the test goes green on its own.
    """
    with pdfplumber.open(str(HCLTECH)) as doc:
        page = doc.pages[index]
        dates = _column_dates(page)
        anchors = _year_anchors(page)

    assert dates, "the page prints no parseable date, so this test cannot say anything"
    distinct_years = {y for _m, y in dates}

    labels = _labels_for(HCLTECH, index, "hcltech_hcltech")

    if len(distinct_years) == 1:
        # Same year in both headers, so the year token cannot distinguish them and the month must.
        months = {m for m, _y in dates}
        assert not (len(months) > 1 and len(labels) == 1), (
            f"printed page {index + 1} compares {sorted(dates)} -- different months, same year -- "
            f"and both arrived as {labels}. The parser relabelled a column it cannot represent. "
            "The fix is either to refuse the comparative and record that, or to represent quarters; "
            "it is not to widen the year regex."
        )
        assert len(anchors) >= 2, (
            "both printed columns should produce an anchor, however indistinct the years are"
        )
    else:
        assert len(labels) == len(distinct_years), (
            f"printed page {index + 1} compares {sorted(dates)}, spanning years "
            f"{sorted(distinct_years)}, but only produced the labels {labels}"
        )


@needs_tcs
def test_two_different_years_still_produce_two_labels():
    """The control that stops this becoming a gate that fails everything.

    TCS compares March 2026 with March 2025. Distinct YEAR tokens, so the existing behaviour is
    already correct and must stay correct. A fix written for HCLTech that broke this would be worse
    than the defect.
    """
    with pdfplumber.open(str(TCS)) as doc:
        dates = _column_dates(doc.pages[10])

    years = {y for _m, y in dates}
    assert len(years) >= 2, f"TCS should compare two different years, found {dates}"

    labels = _labels_for(TCS, 10, "tcs_tcs")
    assert len(labels) >= 2, (
        f"TCS printed page 11 compares {sorted(dates)} and must produce two period labels, got "
        f"{labels}. This is the case that works today and a fix must not regress it."
    )


@needs_hcl
def test_the_anchor_type_cannot_carry_a_month():
    """Names the structural limit, so a future fix knows what has to change.

    This is not a request to change the type now: doing so would alter no observable behaviour,
    because `_period_label` cannot express a March/June difference either. It is recorded so that
    whoever implements quarterly period-ends knows the anchor is the first thing that has to give.
    """
    with pdfplumber.open(str(HCLTECH)) as doc:
        page = doc.pages[4]
        anchors = _year_anchors(page)

    assert anchors, "the page has no anchors, so this cannot say anything"
    years = {year for _x, year in anchors}
    assert len(years) == 1, (
        "HCLTech's two headers are both dated 2026, so the anchors carry one distinct year and "
        "cannot distinguish a quarter from a year-end. That is the defect's mechanism, and it is "
        f"why the labels collapse: {anchors}"
    )


@needs_hcl
def test_the_loss_is_silent_rather_than_recorded():
    """A dropped comparative must be visible. Today it is not.

    The engine does not model quarterly balance sheets, so it cannot represent HCLTech's June 2026
    column. The project's rule is that a recorded unknown beats a silent collision -- so the current
    behaviour, which gives the unrepresentable column a real label and loses the comparative without
    saying so, is the thing to change. This asserts what is true today so the change is visible when
    it happens.
    """
    with pdfplumber.open(str(HCLTECH)) as doc:
        dates = _column_dates(doc.pages[4])

    dps = parse_predicted_statement_page(
        str(HCLTECH), 4, "BALANCE SHEET", "nse_filing", annual_only=False,
        company_id="hcltech_hcltech",
    )
    labels = {d.period_label for d in dps}
    months = {m for m, _y in dates}

    assert len(months) > 1 and len(labels) == 1, (
        f"expected the silent-collision state: two months compared, one label ({labels}). If this "
        "now fails, the parser has started distinguishing them or refusing the column -- in which "
        "case THIS TEST is the obsolete one and should be replaced, not deleted."
    )