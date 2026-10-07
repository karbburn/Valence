"""A statement that runs past one printed page must read on its continuation.

Infosys' cash flow begins on printed 104 and continues on printed 105, and only the
first page prints the fiscal-year header. Measured on the committed documents before
the fix: the continuation raised `no fiscal-year header row found`, so the financing
half -- lease payments, dividends, buybacks -- was never read, and the FY26 cash flow
that reaches the store was half a statement while every guard in the codebase passed.

The fix borrows the header page's columns for the continuation. Three properties must
hold together, and each is asserted below against the real documents rather than
fixtures:

  * the continuation parses, in the columns its header established, carrying the
    figures the filing prints on that page under the periods those columns name;
  * the same page with no header page named still raises, so the honest failure of
    the un-wired path cannot be traded for output;
  * a note page after the statement is still refused even when a header page IS
    named, because a borrowed window over prose emits confident junk -- measured, the
    four note pages that follow the statements print 0, 0, 0 and 1 figure rows inside
    the carried columns against the continuation's 13, and that one row is half a
    sentence at 2.10.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.data.parsers.pdf_tables import parse_predicted_statement_page

FY26 = Path("backend/data/filings/infosys-fy26-q4-outcome.pdf")
FY25 = Path("backend/data/filings/infosys-fy25-q4-outcome.pdf")

needs_filings = pytest.mark.skipif(
    not (FY26.exists() and FY25.exists()),
    reason="the committed Infosys filings are absent",
)


def _values(dps, caption: str) -> dict[str, float]:
    """period label -> value for one caption, so assertions read like the filing."""
    return {d.period_label: d.value for d in dps if d.metric_raw == caption}


@needs_filings
def test_the_fy26_financing_half_reads_in_the_columns_printed_104_established():
    """The page that used to raise, read against the figures it prints.

    Printed 105 prints "Payment of dividends (18,653) (20,287)" beside no header at
    all: the columns belong to printed 104, whose header reads 2026 and 2025.
    Parentheses are outflows, so the values arrive negative -- the direction a
    dividend payment must have -- and both figures, in both periods, with that sign
    is not something a window shifted onto prose would produce.
    """
    dps = parse_predicted_statement_page(
        str(FY26), 104, "CASH FLOW", "nse_filing", annual_only=False,
        company_id="infy_infy", header_page_index=103,
    )
    dividends = _values(dps, "Payment of dividends")
    assert dividends.get("FY26") == pytest.approx(-18653.0), (
        f"FY26 dividends paid is {dividends.get('FY26')}, and printed 105 says "
        f"(18,653) in the FY26 column"
    )
    assert dividends.get("FY25") == pytest.approx(-20287.0), (
        f"FY25 dividends paid is {dividends.get('FY25')}, and printed 105 says "
        f"(20,287) in the FY25 column"
    )
    leases = _values(dps, "Payment of lease liabilities")
    assert leases.get("FY26") == pytest.approx(-2824.0), (
        f"FY26 lease payments is {leases.get('FY26')}, and printed 105 says (2,824)"
    )
    assert leases.get("FY25") == pytest.approx(-2355.0), (
        f"FY25 lease payments is {leases.get('FY25')}, and printed 105 says (2,355)"
    )
    assert dps, "the continuation produced no datapoints at all"
    assert {(d.currency, d.units) for d in dps} == {("INR", "crores")}, (
        "the continuation's rows did not inherit the units printed 104 declares: %r"
        % sorted({(d.currency, d.units) for d in dps})
    )
    assert all(d.section == "CASH FLOW" for d in dps), (
        "a continuation row lost its statement; two statements print the same words "
        "for opposite things and the mapper needs to know which printed this one"
    )
    assert all("p.105" in d.source_location for d in dps), (
        "the continuation's rows are not attributed to printed 105: %r"
        % sorted({d.source_location.split(" y=")[0] for d in dps})[:3]
    )


@needs_filings
def test_the_fy25_continuation_reads_and_agrees_with_the_comparative_column():
    """The other document continues on printed 111, and the two documents must agree.

    The FY26 document's comparative column and the FY25 document's own FY25 column
    print the same year, so "Payment of dividends" comes out as (20,287) under FY25
    from BOTH parses. One figure read twice, from two pages of two documents, is what
    pins the borrow to the columns rather than merely to some figures.
    """
    dps = parse_predicted_statement_page(
        str(FY25), 110, "CASH FLOW", "nse_filing", annual_only=False,
        company_id="infy_infy", header_page_index=109,
    )
    dividends = _values(dps, "Payment of dividends")
    assert dividends.get("FY25") == pytest.approx(-20287.0), (
        f"FY25 dividends paid is {dividends.get('FY25')} off printed 111, and the "
        f"FY26 document's FY25 column says (20,287)"
    )
    assert dividends.get("FY24") == pytest.approx(-14692.0), (
        f"FY24 dividends paid is {dividends.get('FY24')}, and printed 111 says "
        f"(14,692) in the FY24 column"
    )
    assert {(d.currency, d.units) for d in dps} == {("INR", "crores")}, (
        "printed 111's rows did not inherit the units printed 110 declares: %r"
        % sorted({(d.currency, d.units) for d in dps})
    )
    assert all("p.111" in d.source_location for d in dps), (
        "the continuation's rows are not attributed to printed 111: %r"
        % sorted({d.source_location.split(" y=")[0] for d in dps})[:3]
    )


@needs_filings
def test_the_continuation_without_a_named_header_still_raises():
    """The honest failure of the un-wired path, asserted so the borrow stays explicit.

    The parser cannot go looking for the header itself: which earlier page a
    continuation belongs to is the caller's claim about the document, not something
    the page states about itself. Without a named header page the page raises, which
    is why the un-wired path lost the financing half instead of misreading it.
    """
    with pytest.raises(ValueError, match="no fiscal-year header row"):
        parse_predicted_statement_page(
            str(FY26), 104, "CASH FLOW", "nse_filing", annual_only=False,
            company_id="infy_infy",
        )


@needs_filings
def test_a_note_page_after_the_statement_is_refused_even_with_a_header_page():
    """Printed 106 opens the notes, and prose must not parse into periods.

    With printed 104's columns borrowed, the page prints no figures inside them, so
    the guard raises instead of returning an empty result that reads as "this page
    had nothing in it". The FY25 document's printed 113 is the harder case: exactly
    ONE row falls inside the borrowed window -- half a sentence, "acquisition date
    and are based on expectations", with the note reference 2.10 as its figure --
    and the threshold of two refuses that too. One junk row published as an FY-labelled
    cash-flow figure is the plausible answer this guard exists to prevent.
    """
    with pytest.raises(ValueError, match="does not continue that statement"):
        parse_predicted_statement_page(
            str(FY26), 105, "CASH FLOW", "nse_filing", annual_only=False,
            company_id="infy_infy", header_page_index=103,
        )
    with pytest.raises(ValueError, match="does not continue that statement"):
        parse_predicted_statement_page(
            str(FY25), 112, "CASH FLOW", "nse_filing", annual_only=False,
            company_id="infy_infy", header_page_index=109,
        )
