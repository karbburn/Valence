"""One printed figure must read as one figure, however the extractor tokenises it.

The FY26 cash flow prints its acquisition payment with every glyph separately
positioned, so pdfplumber returns five words for one amount:

    y=495.2  Payment for acquisition of business, net of cash acquired   ( 6 3 7 )   (3,155)
                                              x0 457.4 460.1 464.2 468.3 472.4   532.5

Each digit in the figure column parsed on its own and all of them sat in the FY26
column, so one printed amount became three FY26 datapoints -- 6, 3 and 7 -- sharing one
line and one period, and the store then kept whichever was written last: a single-digit
purchase against a filing that prints 637. The comparative `(3,155)` on the same line
prints as one string and read whole, which is how the split survived review -- the
figure that was checked was the figure that read correctly.

The FY25 document splits its own column the same way: `( 3 , 1 5 5 )` read as 1, 3 and5,
while the same figure on the FY26 document's comparative column read -3,155. Two
documents printing the same year disagreed by three orders of magnitude, and neither
side of the disagreement was what the filings print.

These run against both committed documents at the figures they print, and at the
identity the store writes: after the join no two datapoints on either cash flow page
share a `source_location` and a period, so no re-ingest can leave a rival digit beside
the figure. The note reference `2 . 1 0` beside the caption is reassembled too (it sits
in the values band but outside the figure window, x0 385.6 against a window that opens
at 408.9), and these tests pin that it stays a non-figure.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.data.parsers.pdf_tables import parse_predicted_statement_page

FY26 = Path("backend/data/filings/infosys-fy26-q4-outcome.pdf")
FY25 = Path("backend/data/filings/infosys-fy25-q4-outcome.pdf")

needs_both = pytest.mark.skipif(
    not (FY26.exists() and FY25.exists()),
    reason="the Infosys filings are absent",
)

ACQUISITION = "Payment for acquisition of business, net of cash acquired"


def _parse(pdf: Path, index: int):
    return parse_predicted_statement_page(
        str(pdf), index, "CASH FLOW", "nse_filing", annual_only=False,
        company_id="infy_infy",
    )


def _acquisition_rows(dps):
    return [d for d in dps if d.metric_raw == ACQUISITION]


@needs_both
def test_the_amount_the_filing_prints_is_the_amount_the_reader_returns():
    """The defect, asserted at the figure: printed (637) reads as -637.

    Before the join the same assertion saw three FY26 rivals, 6, 3 and 7, because the
    extractor handed the digits over as separate words. The exact list is the point:
    one figure, one period, no digit left standing beside it.
    """
    rows = _acquisition_rows(_parse(FY26, 103))
    got = {(d.period_label, d.value) for d in rows}
    assert got == {("FY26", -637.0), ("FY25", -3155.0)}, (
        "the FY26 cash flow prints '(637)' for FY26 and '(3,155)' for the comparative year, "
        f"and the reader returned {sorted(got)}. A figure whose glyphs arrive as separate "
        "words was read digit by digit, so the store kept one digit of the purchase."
    )
    for d in rows:
        assert d.units == "crores" and d.currency == "INR", (
            f"{d.period_label} acquisition row lost the page's declared units: "
            f"{d.currency}/{d.units}"
        )


@needs_both
def test_the_same_figure_on_its_own_document_reads_the_same_number():
    """The FY25 document's own column split the other way and must agree with it.

    Read digit by digit this line returned 1, 3 and 5 for FY25. Its sibling on the FY26
    document read -3,155 for the same year, so two pages of the same company printed one
    figure and the store held two irreconcilable accounts of it. The bare dash in the
    FY24 column is not a figure and must not become one.
    """
    rows = _acquisition_rows(_parse(FY25, 109))
    got = {(d.period_label, d.value) for d in rows}
    assert got == {("FY25", -3155.0)}, (
        "the FY25 cash flow prints '(3,155)' in its FY25 column and a bare dash in FY24, "
        f"and the reader returned {sorted(got)}"
    )


@needs_both
def test_no_line_writes_two_rows_under_one_identity():
    """What the store would have been left with: one identity, several rival rows.

    Identity is (company, source, source_location, period), and a split figure writes
    every digit under the same four. The re-ingest that replaced rows under that
    identity therefore kept a random digit, whichever one was written last.
    """
    from collections import Counter

    for pdf, index in ((FY26, 103), (FY25, 109)):
        dps = _parse(pdf, index)
        rivals = Counter(
            (d.source_location, d.period_label) for d in dps
        )
        collisions = {k: n for k, n in rivals.items() if n > 1}
        assert not collisions, (
            f"printed {index + 1}: {len(collisions)} line/period identities carry more than "
            f"one row, so a re-ingest would keep one of them and delete the rest: "
            f"{[(k[1], k[0], n) for k, n in collisions.items()]}"
        )


@needs_both
def test_the_note_reference_beside_the_caption_is_not_a_figure():
    """The digits printed between the caption and the figures stay out of the store.

    `2 . 1 0` sits in the values band of both cash flow pages but outside the figure
    window, so it must remain a non-figure however it is tokenised. Assembled it reads
    2.10; split it reads 2, then 1, then 0 -- and either way it must produce no
    datapoint for this caption.
    """
    for pdf, index in ((FY26, 103), (FY25, 109)):
        rows = _acquisition_rows(_parse(pdf, index))
        assert all(d.value not in (2.10, 2.0, 1.0, 0.0) for d in rows), (
            f"printed {index + 1}: the note reference beside this caption became a figure: "
            f"{[(d.period_label, d.value) for d in rows]}"
        )
        assert not any("2.10" in d.metric_raw for d in rows), (
            "the note reference was glued into the caption, moving the row's identity"
        )
