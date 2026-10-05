"""A caption and its figures are one printed line, and the reader has to be able to tell.

`_rows` buckets words by `round(top, 1)`, which splits a caption from its own figures whenever
pdfplumber reports their `top` values a tenth of a point apart. On Infosys printed 180:

    top=83.5   Revenue from operations   2.18        <- caption bucket
    top=83.6                148,819 136,592         <- figure bucket

So the revenue figure never reached its caption, the caption was emitted with no value, and the
profit and loss statement yielded no revenue at all. The same shape was losing about a third of
every statement: printed 100 produced 60 captions where the filing prints 86.

**A threshold on the top gap cannot fix this, and these tests hold the measurement that says so**
rather than restating the conclusion. Across the five committed statement pages:

    infy printed 180 (P&L)   0.10pt x23, 0.20 x6, 0.30 x1, 0.40 x3, 0.50 x1
    infy printed 100 (BS)    0.10pt x14, 0.20 x1, 0.30 x1, 0.50 x1, 0.60 x1, 0.70 x1
    tcs  printed 11  (BS)    0.70pt x2,  1.40 x1, 1.50 x1

TCS's split rows sit at 0.70-1.50pt while Infosys has pairs that must stay apart at 0.60-0.70pt.
The ranges overlap, so no threshold separates them on these documents.

Vertical overlap does, and only with a second condition: 71 of 71 split pairs have vertically
overlapping word boxes, and 4 pairs overlap that must not merge -- all four the audit report's
signature block, and all four carrying caption text on BOTH sides. So overlap alone would weld
"Deloitte" onto "for and on behalf of the Board of".

These run against the committed PDFs and skip without them, because what they assert is what a
real filing prints.
"""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber
import pytest

from backend.data.parsers.pdf_tables import (
    _caption_boundary,
    _merge_split_buckets,
    _rows,
    parse_predicted_statement_page,
)

INFOSYS = Path("backend/data/filings/infosys-fy26-q4-outcome.pdf")
TCS = Path("backend/data/filings/nse/tcs-outcome-2026-04.pdf")

needs_infosys = pytest.mark.skipif(not INFOSYS.exists(), reason="the Infosys filing is absent")
needs_tcs = pytest.mark.skipif(not TCS.exists(), reason="the TCS filing is absent")

# The caption that started this: the forecast grows revenue, so its absence is not cosmetic.
REVENUE = "Revenue from operations"


def _captions(pdf: Path, index: int) -> list[str]:
    with pdfplumber.open(str(pdf)) as doc:
        page = doc.pages[index]
        boundary = _caption_boundary(page.extract_words(), page.height)
        return [r[0].strip() for r in _rows(page, boundary)]


def _valued(pdf: Path, index: int) -> dict[str, list[str]]:
    with pdfplumber.open(str(pdf)) as doc:
        page = doc.pages[index]
        boundary = _caption_boundary(page.extract_words(), page.height)
        return {r[0].strip(): [t for _x, t in r[1]] for r in _rows(page, boundary)}


@needs_infosys
def test_the_profit_and_loss_statement_yields_its_revenue_line():
    """The defect, stated as the thing a reader would notice.

    Before the fix this page produced 19 captions and no revenue at all. A profit and loss
    statement with no revenue cannot seed a forecast, which is why the India models contribute so
    little filing-sourced history.
    """
    vals = _valued(INFOSYS, 179)
    assert REVENUE in vals, (
        f"printed 180 has no {REVENUE!r} caption. Captions found: {sorted(vals)[:20]}"
    )
    assert any(vals[REVENUE]), f"{REVENUE!r} carries no figure: {vals[REVENUE]!r}"
    figures = [t for t in vals[REVENUE] if t.replace(",", "").isdigit()]
    assert figures, f"{REVENUE!r} has no numeric figure among {vals[REVENUE]!r}"


@needs_infosys
def test_the_recovered_figures_are_the_ones_the_filing_prints():
    """The grouping must attach the filing's own numbers, not merely attach some.

    Printed 180 prints "Revenue from operations ... 148,819 136,592". Asserting the values pins
    the merge to the right figures; asserting only that a number appeared would pass if the row
    merged with the wrong neighbour's column.
    """
    dps = parse_predicted_statement_page(
        str(INFOSYS), 179, "PROFIT & LOSS", "nse_filing", annual_only=True,
        company_id="infy_infy",
    )
    revenue = {d.period_label: d.value for d in dps if d.metric_raw == REVENUE}
    assert revenue, f"no revenue datapoints: {sorted({d.metric_raw for d in dps})[:20]}"
    assert revenue.get("FY26") == pytest.approx(148819.0), (
        f"FY26 revenue is {revenue.get('FY26')}, and the filing prints 148,819"
    )
    assert revenue.get("FY25") == pytest.approx(136592.0), (
        f"FY25 revenue is {revenue.get('FY25')}, and the filing prints 136,592"
    )


@needs_infosys
def test_a_page_title_is_never_merged_into_its_date_header():
    """The failure this fix could have introduced, and did on the first attempt.

    A page title carries caption text and the date header beside it does not, so both merge
    conditions are satisfied and the two bridge -- which publishes the header's "31," as a figure
    of 31.0. That is the same defect the old 3.0pt window produced.

    A statement prints its period header on two lines, so refusing to bridge a bare year is not
    enough on its own: the line holding the title and "Year ended March 31," carries no year
    token. Both a year and a month name are therefore refused.
    """
    for index in (99, 103, 179):
        for caption in _captions(INFOSYS, index):
            assert "March" not in caption, (
                f"printed {index + 1}: {caption!r} absorbed a date fragment"
            )
            assert not caption.endswith("Consolidated Balance Sheet as at"), (
                f"printed {index + 1}: the page title was merged with the row beneath it"
            )


@needs_infosys
def test_the_auditors_signature_block_never_becomes_a_datapoint():
    """Printed 180 carries the audit report as well as the statement.

    "Membership No. 060408" reaches the caption column, and the figures beside it include a DIN
    that parses as a number, so without a filter it becomes a profit-and-loss line.

    Asserted on the PARSED OUTPUT rather than on `_rows`, because that is the layer the filter
    sits at. The first version of this test looked at `_rows` and failed while the datapoints
    were in fact clean, which is the wrong way round: a reader cares what becomes a figure, not
    what is a candidate for one.
    """
    for index, section in ((99, "BALANCE SHEET"), (103, "CASH FLOW"), (179, "PROFIT & LOSS")):
        dps = parse_predicted_statement_page(
            str(INFOSYS), index, section, "nse_filing", annual_only=False,
            company_id="infy_infy",
        )
        for d in dps:
            for banned in ("Membership", "Chief Financial Officer", "Deloitte",
                           "Haskins", "Sells", "DIN"):
                assert banned not in d.metric_raw, (
                    f"printed {index + 1}: audit-report text became a datapoint: "
                    f"{d.metric_raw!r} = {d.value}"
                )


@needs_infosys
def test_both_printings_of_a_repeated_caption_survive_the_merge():
    """The product rule: never remove a correct figure.

    Printed 104 prints "- Mutual fund units" twice, once inside a note with the figures in
    parentheses and once inside another with them plain. Both readings are correct, and the line
    coordinate is what tells them apart. A merge that collapsed them would delete a filed figure,
    which is worse than publishing a wrong one.
    """
    dps = parse_predicted_statement_page(
        str(INFOSYS), 103, "CASH FLOW", "nse_filing", annual_only=False,
        company_id="infy_infy",
    )
    mutual = [d for d in dps if d.metric_raw == "- Mutual fund units"]
    fy26 = [d for d in mutual if d.period_label == "FY26"]
    assert len(fy26) == 2, (
        f"expected both printed readings of '- Mutual fund units' for FY26, got "
        f"{[(d.value, d.source_location) for d in fy26]}"
    )
    assert {round(d.value) for d in fy26} == {-72878, 72682}, (
        f"the parenthesised note (-72,878) and the plain one (72,682) are both correct readings; "
        f"got {sorted(d.value for d in fy26)}"
    )
    assert len({d.source_location for d in fy26}) == 2, (
        "the two readings share a source_location, so a re-ingest cannot tell them apart"
    )


@needs_infosys
def test_the_merge_never_loses_a_caption():
    """It moves tokens between a caption and its figures; it must not delete a line."""
    real = _merge_split_buckets

    def before(buckets, boundary):
        return buckets

    from backend.data.parsers import pdf_tables as pt

    pt._merge_split_buckets = before
    try:
        for index in (99, 103, 179):
            with pdfplumber.open(str(INFOSYS)) as doc:
                page = doc.pages[index]
                b = pt._caption_boundary(page.extract_words(), page.height)
                was = [r[0].strip() for r in pt._rows(page, b)]
    finally:
        pt._merge_split_buckets = real

    now = _captions(INFOSYS, index)
    lost = sorted(set(was) - set(now))
    assert not lost, f"printed {index + 1}: captions the merge removed: {lost}"
    assert len(now) >= len(was), (
        f"printed {index + 1}: {len(was)} captions before, {len(now)} after. The point of the "
        f"merge is recovery, so a decrease is a regression."
    )


def _words(words: list[tuple[float, str]], top: float) -> list[dict]:
    """Synthetic pdfplumber-shaped word dicts, so the guards can be tested without a filing."""
    return [
        {
            "x0": x,
            "x1": x + 18.0,
            "top": top,
            "bottom": top + 9.0,
            "text": text,
        }
        for x, text in words
    ]


def test_two_caption_buckets_are_never_merged_into_one_line():
    """The weld guard, fed the case it exists to refuse.

    Four earlier versions of this test tried to INFER a weld from the parsed output, and the
    filings contradicted every premise: duplicate captions are normal where a balance sheet prints
    both halves, equal indents are normal for children repeated in both halves, a comma-grouped
    amount inside a caption is normal (Infosys prints "authorized, issued and outstanding
    4,046,940,812 (4,143,607,528) equity shares" as one line), and the caption set legitimately
    GROWS because a row previously dropped for carrying no figure now carries one.

    Testing the guard directly is the version with a premise that holds: given two vertically
    overlapping buckets that BOTH carry caption text -- the audit report's signature block, the
    shape that produced all four false positives in the measurement -- the merge must decline.
    """
    boundary = 330.0
    signature = [
        (200.0, _words([(100.0, "April"), (140.0, "23,"), (160.0, "2026")], 200.0)),
        (200.4, _words([(100.0, "Chief"), (150.0, "Financial"), (210.0, "Officer")], 200.4)),
    ]
    merged = _merge_split_buckets(signature, boundary)
    assert len(merged) == 2, (
        "two buckets that both carry caption text were merged, which is how a caption becomes a "
        f"concatenation of two printed lines: {merged}"
    )
    texts = [w["text"] for _key, ws in merged for w in ws]
    assert texts == ["April", "23,", "2026", "Chief", "Financial", "Officer"]


def test_a_caption_bucket_is_merged_with_the_figures_beneath_it():
    """The positive case, so the guard above is not passing because nothing ever merges."""
    boundary = 330.0
    split = [
        (200.0, _words([(54.0, "Revenue"), (120.0, "from"), (170.0, "operations")], 200.0)),
        (200.1, _words([(462.0, "148,819"), (534.0, "136,592")], 200.1)),
    ]
    merged = _merge_split_buckets(split, boundary)
    assert len(merged) == 1, (
        "a caption and the figures pdfplumber split onto the next bucket were not rejoined, so "
        f"the caption is emitted with no value: {merged}"
    )
    joined = [w["text"] for w in merged[0][1]]
    assert "Revenue" in joined and "148,819" in joined, (
        f"the merged bucket lost a side: {joined}"
    )


def test_a_date_header_is_never_bridged_even_when_only_one_side_has_caption_text():
    """The title failure, fed directly.

    A page title carries caption text and the date fragment beside it does not, so both merge
    conditions hold. Without the year and month guards the merged row publishes "31," as a figure
    of 31.0 -- the same defect the old 3.0pt window produced.
    """
    boundary = 330.0
    title_and_date = [
        (62.2, _words([(54.0, "Statement"), (150.0, "of"), (200.0, "Profit")], 62.2)),
        (62.5, _words([(340.0, "31,"), (370.0, "March")], 62.5)),
    ]
    assert len(_merge_split_buckets(title_and_date, boundary)) == 2, (
        "a page title was bridged into its date header"
    )

    year_header = [
        (62.2, _words([(54.0, "Particulars")], 62.2)),
        (62.5, _words([(462.0, "2026"), (534.0, "2025")], 62.5)),
    ]
    assert len(_merge_split_buckets(year_header, boundary)) == 2, (
        "a caption was bridged into the year header row"
    )


def test_two_columns_cannot_be_mistaken_for_quarterly_and_annual_pairs():
    """`annual_only` used to keep the rightmost half of the year headers unconditionally.

    Infosys printed 180 prints two headers, "2026 2025", and BOTH are annual, so `anchors[1:]`
    kept one column and discarded FY26 -- the statement the grouping fix recovered arrived with
    half its years missing.
    """
    from backend.data.parsers.pdf_tables import _has_column_pairs

    assert not _has_column_pairs([(462.0, 2026), (534.0, 2025)]), (
        "two year headers cannot be quarterly/annual pairs, so both must be kept"
    )
    assert _has_column_pairs([(300.0, 2025), (360.0, 2025), (460.0, 2026), (530.0, 2026)]), (
        "four headers can be two pairs, so the rightmost half is the annual columns"
    )


@needs_infosys
def test_a_share_count_never_becomes_a_rupee_line_item():
    """The earnings-per-share block prints share counts in the rupee columns.

        Basic (in shares)     2.13   4,046,019,309   4,142,429,577
        Basic (Rs.)           2.13        21.01          16.98

    Both sit in the value columns, so the count was read as rupees and 4,046,019,309 reached a
    profit-and-loss line. Separated on what the CAPTION says, never on the magnitude of the
    number: the count is four thousand times the rupee figure here, and a small-cap
    earnings-per-share figure is the other way round, so scale decides nothing.
    """
    dps = parse_predicted_statement_page(
        str(INFOSYS), 100, "PROFIT & LOSS", "nse_filing", annual_only=True,
        company_id="infy_infy",
    )
    counts = [d for d in dps if "in shares" in d.metric_raw.lower()]
    assert not counts, (
        "a count of shares became a rupee line item: "
        f"{[(d.metric_raw, d.period_label, d.value) for d in counts]}"
    )
    # And the per-share RUPE figure beside it must survive, because it is a real statement line.
    per_share = [d for d in dps if "per share" in d.metric_raw.lower() or "(₹)" in d.metric_raw]
    assert per_share, (
        "the per-share rupee figure was dropped along with the share counts. They sit in the "
        "same block and only the caption distinguishes them."
    )


@needs_infosys
def test_share_capital_and_premium_are_not_mistaken_for_share_counts():
    """The other direction: real rupee lines whose captions happen to say "share"."""
    dps = parse_predicted_statement_page(
        str(INFOSYS), 99, "BALANCE SHEET", "nse_filing", annual_only=False,
        company_id="infy_infy",
    )
    premium = {d.period_label: d.value for d in dps if d.metric_raw == "Share premium"}
    assert premium, (
        "'Share premium' is a rupee balance-sheet line and was dropped. The rule separates a "
        "count of shares from an amount, and this is an amount."
    )
    # Measured against the filing: printed 101 shows 1,839 and 2,180.
    assert premium.get("FY26") == pytest.approx(1839.0), (
        f"Share premium FY26 is {premium.get('FY26')}, and the filing prints 1,839"
    )
    assert premium.get("FY25") == pytest.approx(2180.0), (
        f"Share premium FY25 is {premium.get('FY25')}, and the filing prints 2,180"
    )