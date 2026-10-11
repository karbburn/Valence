"""A dotted date is a fiscal-year anchor, and operator-recorded units fill a silent banner.

Two mechanisms Tata Steel's audited consolidated face needs, each asserted against the
printed page rather than a simulation:

1. Dotted-date anchors. The face prints its column headers as single tokens
   "31.03.2026" and "31.03.2025". `_year_anchors` recognised only a bare `20\\d\\d`
   there, so the page raised "no fiscal-year header row found" and read nothing. A
   dotted date is the stronger signal, not the weaker -- a bare "2026" can be prose,
   "31.03.2026" cannot -- so it is read under the same x >= boundary condition as a
   bare year. The page's only bare year sits in its TITLE left of the caption
   boundary, which is why the boundary rule stays as written.

2. `declared_units_override`. The same page prints a bare "Crore" in the banner slot:
   no parens, no currency token, no preposition, so there is no declaration residue
   for `declared_units` to match and every row would arrive with empty currency and
   units. The fact is recorded in the filing metadata beside `balance_sheet_pages`,
   the same class of operator-witnessed record as `readable_periods`, and consulted
   ONLY when the page itself declared nothing. The second assertion is the guard: a
   page that speaks for itself (ONGC's "(Rs in Crore)") is never overridden even if
   metadata were to claim something else.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.data.parsers.pdf_tables import parse_predicted_statement_page
from backend.data.pipeline import _declared_units_for

TATA = Path("backend/data/filings/nse/tatasteel-annual-2026-05.pdf")
ONGC = Path("backend/data/filings/nse/ongc-annual-2026-05.pdf")

needs_tata = pytest.mark.skipif(not TATA.exists(), reason="the Tata Steel filing is absent")
needs_ongc = pytest.mark.skipif(not ONGC.exists(), reason="the ONGC filing is absent")

# Printed page 20 is the consolidated face; the document is 1-based there, 0-based here.
FACE = 19
# The banner slot's bare scale word, recorded from the printed page at install time.
CRORE = ("", "crores")


@needs_tata
def test_a_dotted_date_header_reads_both_year_columns() -> None:
    dps = parse_predicted_statement_page(
        TATA, FACE, "BALANCE SHEET", "nse_filing", annual_only=False,
        company_id="tatasteel_tatasteel", declared_units_override=CRORE,
    )
    assert dps, "the page read nothing: the dotted-date anchors did not fire"
    periods = {d.period_label for d in dps}
    # Both printed columns are dated 31.03.2026 / 31.03.2025, so both years must
    # arrive. One year alone would mean one anchor was read and one lost.
    assert {"FY26", "FY25"} <= periods, f"periods read: {sorted(periods)}"


@needs_tata
def test_the_recorded_units_reach_every_row_of_the_silent_page() -> None:
    dps = parse_predicted_statement_page(
        TATA, FACE, "BALANCE SHEET", "nse_filing", annual_only=False,
        company_id="tatasteel_tatasteel", declared_units_override=CRORE,
    )
    bad = [(d.metric_raw, d.currency, d.units) for d in dps
           if d.currency != "INR" or d.units != "crores"]
    assert not bad, f"rows without the recorded INR/crores basis: {bad[:5]}"


@needs_tata
def test_no_override_means_the_silent_page_refuses_rather_than_assumes() -> None:
    # The override is the only thing standing between this page and empty units;
    # without it the rows must arrive undetermined, which the company's own
    # currency check then refuses. That refusal is the design -- an unbased figure
    # must never reach the store -- so this pins the override as load-bearing.
    dps = parse_predicted_statement_page(
        TATA, FACE, "BALANCE SHEET", "nse_filing", annual_only=False,
        company_id="tatasteel_tatasteel",
    )
    assert dps, "the page still read rows"
    undetermined = [d for d in dps if not (d.currency and d.units)]
    assert undetermined, "rows carried a basis the page never declared"


@needs_ongc
def test_a_page_that_declares_its_own_units_is_not_overridden() -> None:
    # ONGC's banner is a complete "(Rs in Crore)" declaration. A bogus metadata
    # record must not override it: the page's own banner always wins, so every row
    # keeps INR/crores whether the override is absent or claims something else.
    bogus = ("USD", "millions")
    dps = parse_predicted_statement_page(
        ONGC, 34, "BALANCE SHEET", "nse_filing", annual_only=False,
        company_id="ongc_ongc", declared_units_override=bogus,
    )
    assert dps
    bad = [(d.metric_raw, d.currency, d.units) for d in dps
           if d.currency != "INR" or d.units != "crores"]
    assert not bad, f"the page's own declaration lost to metadata: {bad[:5]}"


def test_the_recorded_units_are_read_only_for_the_page_they_were_recorded_on() -> None:
    meta = {"declared_units": {"20": ["", "crores"]}}
    assert _declared_units_for(meta, 20) == ("", "crores")
    assert _declared_units_for(meta, 35) is None, "another page must not inherit it"
    assert _declared_units_for({}, 20) is None, "no record means no claim"


def test_an_empty_record_is_no_claim_at_all() -> None:
    # A record of ("", "") is what a caller writes when it has nothing to say;
    # passing it through would reach the same empty tuple the absent case avoids.
    meta = {"declared_units": {"20": ["", ""]}}
    assert _declared_units_for(meta, 20) is None
