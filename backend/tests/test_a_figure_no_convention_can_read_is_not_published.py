"""A figure whose comma grouping no convention can read is not published.

HCLTech's audited Ind-AS balance sheet (printed page 4) prints its FY25
current-liabilities subtotal as "28,1139". The filing's own arithmetic names
the intent: the components sum to 28,039, and 7,832 + 28,039 = 35,871 is the
total the same face prints for total liabilities. Read as western grouping
(281,139) it publishes a reported figure eleven times its own arithmetic, and
read as Indian grouping (2,81,139) it still lands nine times too high. Both
conventions parse; neither is what the line says.

So the choice is refuse or lie. The parser refuses: the figure is a recorded
unknown, the row keeps its other period column, and the shortfall is visible
where a missing subtotal belongs -- on the face of the model, where the
reconciler can see that total current liabilities does not sum to its printed
components for that year. A wrong number would be invisible: it foots nothing
and contradicts nothing, because it replaces the sum that would have caught it.

Both real conventions keep working, because refusing them would withhold
figures the filing states plainly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.data.parsers.pdf_tables import _num, parse_predicted_statement_page

HCLTECH_INDAS = Path("backend/data/filings/nse/hcltech-indas-2026-04.pdf")

needs_indas = pytest.mark.skipif(
    not HCLTECH_INDAS.exists(), reason="no audited Ind-AS filing committed"
)


class TestAGroupingNoConventionCanRead:
    """The refusal at the level it happens, on the token itself."""

    def test_hcltechs_misprint_is_refused(self):
        assert _num("28,1139") is None, (
            "the filing prints 28,1139 where its own components sum to 28,039; a non-None "
            "value means the parser chose a convention the line does not state"
        )

    def test_the_misprint_is_refused_inside_parentheses_too(self):
        """Negatives print parenthesised, and the grouping check must see them."""
        assert _num("(28,1139)") is None

    def test_western_grouping_still_reads(self):
        assert _num("281,139") == 281139.0, (
            "three digits behind every comma is a western-grouped figure and must publish"
        )

    def test_indian_grouping_still_reads(self):
        assert _num("2,81,139") == 281139.0, (
            "three behind the first comma and two behind the rest is the Indian convention "
            "and must publish"
        )

    def test_an_ordinary_grouped_figure_still_reads(self):
        assert _num("11,032") == 11032.0

    def test_a_trailing_comma_is_untouched_by_the_refusal(self):
        """The surgical scope: only tokens matching a grouped figure can refuse.

        "31," is a date fragment pdfplumber splits from its line; it has never
        parsed as a grouped figure and this change must not make it start, or
        stop, doing anything. It reads as 31.0 exactly as before -- the year and
        month guards on the bucket merge are what keep it out of a row, and
        they are tested in `test_a_caption_and_its_figures_are_one_line.py`.
        """
        assert _num("31,") == 31.0


@needs_indas
class TestTheMisprintNeverReachesTheModel:
    """The end-to-end claim, on the document that prints it."""

    def _dps(self):
        return parse_predicted_statement_page(
            str(HCLTECH_INDAS), 3, "BALANCE SHEET", "nse_filing", annual_only=False,
            company_id="hcltech_hcltech",
        )

    def test_the_misparsed_value_is_absent_from_the_page(self):
        values = {d.value for d in self._dps()}
        assert 281139.0 not in values, (
            "the misprint's western reading reached the page's rows"
        )

    def test_the_subtotal_keeps_the_column_that_is_readable(self):
        """A refusal must not take the honest column with it."""
        by_period = {
            d.period_label: d.value
            for d in self._dps()
            if d.metric_raw == "Total current liabilities"
        }
        assert by_period.get("FY26") == 31826.0, (
            f"the FY26 current-liabilities total prints 31,826: {by_period}"
        )
        assert "FY25" not in by_period, (
            "FY25's cell is the misprint; a value there means the refusal did not hold "
            f"{by_period}"
        )
