"""A title's lone year is not a column anchor; a header's pair is.

Measured on L&T's FY26 integrated report (`lt-annual-2026-05.pdf`, committed), whose
audited consolidated balance sheet spans printed pages 617-618. Before the fix, the
caption "Consolidated Balance Sheet as at March 31, 2026" on printed 617 ends at
x=334 -- four points right of the label boundary (330) -- so its title-year token
anchored while the real header stamps sat 41.6pt below at x=397 and x=493. The note
column at x=333..336 then claimed FY26 from the title's anchor and published note
references as figures ("Property, plant and equipment" carries note 2, so FY26 read
2.0 against a printed 15,663.02), the true figures collided with the header anchor
and dropped (21 rows on p.617, 12 on p.618), and the stray anchor dragged the figure
window's left edge (first anchor - 50) to 284, inside the note column itself.

A bare year therefore anchors only inside a BAND of bare years
(`_BARE_YEAR_BAND = 40`), because that is the shape a column header has: years print
together, a title's year stands alone. The tolerance is measured, not chosen:
Bharti's printed 3 prints its pair 0.3pt apart (extraction jitter on one printed
line), Reliance's printed 16 prints them 36.5pt apart (a two-line header band), and
L&T's title sits 41.6pt above its header -- so the tolerance must reach 36.5 and
stop short of 41.6, and 40 does both. A band qualifies at two or more years, so a
page whose header states one year still raises rather than reading prose into a
column.

The synthetic cases state the rule at the geometry measured on those pages; the
real-document cases parse the committed filings and assert the figures the pages
print.
"""
from __future__ import annotations

import pytest

from backend.data.parsers import pdf_tables
from backend.data.parsers.pdf_tables import parse_predicted_statement_page

LT_FILING = "backend/data/filings/nse/lt-annual-2026-05.pdf"
BHARTI_FILING = "backend/data/filings/nse/bhartiartl-annual-2026-05.pdf"
RELIANCE_FILING = "backend/data/filings/nse/reliance-annual-2026-04.pdf"

from pathlib import Path

needs_lt = pytest.mark.skipif(
    not Path(LT_FILING).exists(), reason="the L&T filing is absent"
)
needs_bh = pytest.mark.skipif(
    not Path(BHARTI_FILING).exists(), reason="the Bharti filing is absent"
)
needs_rel = pytest.mark.skipif(
    not Path(RELIANCE_FILING).exists(), reason="the Reliance filing is absent"
)


class _Page:
    """Words as pdfplumber returns them: x0, top, text."""

    def __init__(self, words):
        self._words = words

    def extract_words(self):
        return self._words


class TestABareYearAnchorsOnlyInsideABand:
    def test_a_titles_lone_year_right_of_the_boundary_is_refused(self):
        """L&T printed 617's exact geometry: the title's year, then the stamp pair.

        The stamps pair through the dotted-date path; the title's bare year is a
        band of one and contributes nothing, so the anchors are the header's.
        """
        page = _Page([
            {"x0": 334.0, "top": 65.2, "text": "2026"},
            {"x0": 397.0, "top": 106.8, "text": "31-3-2026"},
            {"x0": 493.2, "top": 106.8, "text": "31-3-2025"},
        ])
        assert pdf_tables._year_anchors(page) == [
            (397.0, 2026), (493.2, 2025),
        ], "the title's year joined the header's column anchors"

    def test_a_lone_bare_year_still_raises(self):
        """One bare year and nothing else: no band, no dates, no window."""
        page = _Page([
            {"x0": 334.0, "top": 65.2, "text": "2026"},
            {"x0": 400.0, "top": 150.0, "text": "90,806"},
        ])
        with pytest.raises(ValueError, match="no fiscal-year header row"):
            pdf_tables._year_anchors(page)

    def test_a_pair_jittered_off_one_printed_line_still_anchors(self):
        """Bharti printed 3: the two header years extract 0.3pt apart.

        Both label value columns on one printed line; requiring identical tops
        refused the pair and the page read nothing.
        """
        page = _Page([
            {"x0": 412.5, "top": 97.6, "text": "2026"},
            {"x0": 495.1, "top": 97.3, "text": "2025"},
        ])
        assert [y for _, y in pdf_tables._year_anchors(page)] == [2026, 2025], (
            "a 0.3pt jitter between one line's years lost both anchors"
        )

    def test_a_pair_spanning_a_two_line_header_still_anchors(self):
        """Reliance printed 16: the two header years extract 36.5pt apart."""
        page = _Page([
            {"x0": 424.4, "top": 51.2, "text": "2026"},
            {"x0": 527.7, "top": 87.7, "text": "2025"},
        ])
        assert [y for _, y in pdf_tables._year_anchors(page)] == [2026, 2025], (
            "a 36.5pt two-line header lost both anchors"
        )

    def test_a_title_above_a_bare_pair_does_not_join_it(self):
        """The tolerance must stop short of the measured 41.6pt title-header gap.

        Had L&T's header printed bare years instead of stamps, the title's year
        would still stand alone and the pair would anchor.
        """
        page = _Page([
            {"x0": 334.0, "top": 65.2, "text": "2026"},
            {"x0": 397.0, "top": 106.8, "text": "2026"},
            {"x0": 493.2, "top": 106.8, "text": "2025"},
        ])
        assert pdf_tables._year_anchors(page) == [
            (397.0, 2026), (493.2, 2025),
        ], "a title less than the band below a bare pair was glued to it"


@needs_lt
class TestTheLTSixBalanceSheetReadsItsFiguresAndNotItsNotes:
    def _page(self, printed: int):
        return parse_predicted_statement_page(
            Path(LT_FILING), printed - 1, "BALANCE SHEET", "nse_filing",
            annual_only=False, company_id="lt_lt",
            declared_units_override=("INR", "crores"),
        )

    def test_the_note_column_does_not_claim_the_year(self):
        rows = self._page(617)
        ppe = sorted(
            (d.period_label, d.value) for d in rows
            if d.metric_raw == "Property, plant and equipment"
        )
        assert ppe == [("FY25", 14128.56), ("FY26", 15663.02)], (
            "the note column claimed FY26 from the title's anchor: %s" % ppe
        )
        goodwill = sorted(
            (d.period_label, d.value) for d in rows
            if d.metric_raw == "Goodwill"
        )
        assert goodwill == [("FY25", 8348.48), ("FY26", 8481.54)], (
            "note 4 was published as the FY26 figure: %s" % goodwill
        )

    def test_the_titles_own_caption_produced_no_rows(self):
        rows = self._page(617) + self._page(618)
        titled = [
            d.metric_raw for d in rows
            if d.metric_raw.startswith("Consolidated Balance Sheet")
        ]
        assert titled == [], (
            "the title's year anchored a caption into the row set: %s" % titled
        )

    def test_the_subtotals_read_as_printed_on_both_pages(self):
        rows = self._page(617) + self._page(618)
        got = {
            (d.metric_raw, d.period_label): d.value for d in rows
            if d.metric_raw in {
                "Sub-total - Non-current assets", "Sub-total - Current assets",
                "TOTAL ASSETS", "Equity share capital",
                "Sub-total - Current liabilities",
            }
        }
        assert got == {
            ("Sub-total - Non-current assets", "FY25"): 134182.39,
            ("Sub-total - Non-current assets", "FY26"): 134238.56,
            ("Sub-total - Current assets", "FY25"): 245184.27,
            ("Sub-total - Current assets", "FY26"): 292841.13,
            ("TOTAL ASSETS", "FY25"): 379524.1,
            ("TOTAL ASSETS", "FY26"): 452549.88,
            ("Equity share capital", "FY25"): 275.04,
            ("Equity share capital", "FY26"): 275.13,
            ("Sub-total - Current liabilities", "FY25"): 201970.9,
            ("Sub-total - Current liabilities", "FY26"): 233531.47,
        }, "the printed subtotals did not read as printed: %s" % got

    def test_both_pages_read_their_rows_in_full(self):
        rows = self._page(617) + self._page(618)
        assert len(rows) == 107, (
            "the two pages read %d rows against the 107 measured" % len(rows)
        )
        assert {d.period_label for d in rows} == {"FY25", "FY26"}


@needs_bh
class TestTheOtherInstalledStatementsThatPrintPairsStillRead:
    def test_bhartis_header_pair_still_anchors(self):
        """The 0.3pt jitter case, on the committed filing itself."""
        rows = parse_predicted_statement_page(
            Path(BHARTI_FILING), 2, "BALANCE SHEET", "nse_filing",
            annual_only=False, company_id="bhartiartl_bhartiartl",
            declared_units_override=("INR", "millions"),
        )
        assert len(rows) == 85, "printed 3 reads %d rows" % len(rows)
        total = sorted(
            (d.period_label, d.value) for d in rows
            if d.metric_raw == "Total assets"
        )
        assert total == [("FY25", 5143604.0), ("FY26", 5521516.0)], (
            "the pair no longer labels both columns: %s" % total
        )

    @needs_rel
    def test_reliances_two_line_header_still_pairs(self):
        """The 36.5pt band case, on the committed filing itself.

        The direct parse reads both periods (48 rows); the store path refuses
        the FY26 column through the witnessed `readable_periods` record and
        keeps the 42 FY25 rows.
        """
        rows = parse_predicted_statement_page(
            Path(RELIANCE_FILING), 15, "BALANCE SHEET", "nse_filing",
            annual_only=False, company_id="reliance_reliance",
        )
        assert len(rows) == 48, "printed 16 reads %d rows" % len(rows)
        assert {d.period_label for d in rows} == {"FY25", "FY26"}, (
            "one of the two header years no longer anchors a column"
        )
