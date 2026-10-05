"""The parser reads units from the page instead of asserting them.

`parse_predicted_statement_page` used to stamp every row it emitted with `currency="INR",
units="crores"` regardless of what the document said. That is a claim the parser cannot verify, and
for one committed filing it is false.

`hcltech-ifrs-2026-07.pdf` carries this header on BOTH of its balance-sheet pages:

    HCL Technologies Limited  Condensed Consolidated Interim Balance Sheet
    (All amounts in millions of USD, except share data and as stated otherwise)

Every one of its figures was therefore recorded as INR crores. One USD million is roughly 8.3 INR
crores, so the balance sheet was understated by about eight times while looking entirely ordinary.

It did not merely produce a wrong number. It produced a model that looked CONSISTENT to
`check_units_agree_within_a_model`, because every row carried the same wrong label. That guard
exists, it runs in the validation pipeline, and it has never fired on HCLTech -- not because it is
weak but because it was being lied to uniformly by the parser. A guard cannot catch what the thing
it guards has already agreed on.

So these tests assert the reading, and assert the refusals, because the failure mode that produced
this bug is a rule that answers everything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.data.parsers.pdf_tables import declared_units, parse_predicted_statement_page

INFOSYS = Path("backend/data/filings/infosys-fy26-q4-outcome.pdf")
HCLTECH = Path("backend/data/filings/nse/hcltech-ifrs-2026-07.pdf")
TCS = Path("backend/data/filings/nse/tcs-outcome-2026-04.pdf")

needs_hcl = pytest.mark.skipif(not HCLTECH.exists(), reason="no HCLTech filing committed")
needs_infy = pytest.mark.skipif(not INFOSYS.exists(), reason="no Infosys filing committed")
needs_tcs = pytest.mark.skipif(not TCS.exists(), reason="no TCS filing committed")


class TestWhatThePageDeclares:
    """The real headers, copied from the committed documents."""

    @needs_hcl
    def test_a_usd_filing_is_read_as_usd_millions(self):
        currency, units = declared_units(
            "HCL Technologies Limited Condensed Consolidated Interim Balance Sheet "
            "(All amounts in millions of USD, except share data and as stated otherwise) Note"
        )
        assert (currency, units) == ("USD", "millions"), (
            "the filing says millions of USD and must be read that way. Reading it as INR crores "
            "understated every figure on the page by about eight times."
        )

    @needs_infy
    def test_an_inr_filing_is_read_as_inr_crores(self):
        currency, units = declared_units(
            "Infosys Limited and subsidiaries (In ₹ crore except equity share and per "
            "equity share data) Consolidated Statement of Profit and Loss"
        )
        assert (currency, units) == ("INR", "crores")

    def test_a_missing_currency_glyph_yields_no_currency(self):
        """TCS prints "( crore)" -- the rupee symbol does not survive extraction.

        The scale is declared and readable. The currency is not printed in anything this can see, so
        it must not be supplied. Defaulting it to INR here would be the same unverified pass as the
        hardcode, wearing a regex.
        """
        currency, units = declared_units(
            "TATA CONSULTANCY SERVICES LIMITED Audited Consolidated Balance Sheet ( crore) "
            "As at As at March 31, 2026 March 31, 2025 ASSETS"
        )
        assert units == "crores", "the scale is printed and must be read"
        assert currency == "", (
            f"TCS prints no currency token this can read, so the currency must stay undetermined, "
            f"not be filled in. Got {currency!r}."
        )

    def test_a_declaration_after_a_policy_paragraph_is_still_a_declaration(self):
        """The Infosys cash-flow pages declare their units mid-page, not in the header.

        Refusing those pages would withhold a filing that states everything it needs to state, so
        the search runs over the page rather than its first line.
        """
        currency, units = declared_units(
            "Infosys Limited and subsidiaries Consolidated Statement of Cash Flows Accounting "
            "Policy Cash flows are reported using the indirect method, whereby profit for the "
            "year is adjusted for the effect of transactions of a non-cash nature, any deferrals "
            "or accruals of past or future operating cash receipts and payments, investing and "
            "financing activities of the Group are segregated. The Group considers all highly "
            "liquid investments that are readily convertible to known amounts of cash to be cash "
            "equivalents. (In ₹ crore) Year ended March 31, Particulars Note 2026 2025"
        )
        assert (currency, units) == ("INR", "crores")


class TestWhatItRefuses:
    """The failure mode that produced this bug is a rule that answers everything."""

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "Acme Holdings plc Annual Report 2026",
            "Balance Sheet as at 31 March 2026",
            "Consolidated Statement of Financial Position",
            "The Company has applied the going concern basis of preparation.",
        ],
        ids=["empty", "no-units-word", "bare-heading", "position-heading", "policy-prose"],
    )
    def test_a_page_that_declares_nothing_is_left_undetermined(self, text):
        currency, units = declared_units(text)
        assert (currency, units) == ("", ""), (
            "a page that declares nothing must be recorded as undetermined rather than assumed to "
            "be INR crores. An empty value makes the model disagree with an INR feed, which is the "
            "correct outcome when one of the two might not be in rupees."
        )

    def test_a_bare_units_word_in_prose_is_not_a_declaration(self):
        """Accounting-policy text mentions "lakh" without declaring anything."""
        currency, units = declared_units(
            "The Company has investments aggregating to Rs 12 lakh which are held for trade. "
            "These are measured at fair value through profit or loss."
        )
        assert units == "", (
            f"a units word inside prose is not a declaration of the page's units, and reading it "
            f"as one would relabel the whole statement. Got units={units!r}"
        )

    def test_a_thousands_declaration_without_a_currency_is_not_attributed(self):
        """A scale with no currency is half a fact and must stay half a fact."""
        currency, units = declared_units("All amounts in thousands")
        assert units == "", (
            "thousands of what? The page does not say, so nothing is read from it."
        )


@needs_hcl
class TestTheRowsCarryWhatThePageDeclared:
    """The end-to-end claim, on the filing where the hardcode was false."""

    def _dps(self):
        return parse_predicted_statement_page(
            str(HCLTECH), 4, "BALANCE SHEET", "nse_filing", annual_only=False,
            company_id="hcltech_hcltech",
        )

    def test_no_hcltech_row_is_stamped_inr_crores_any_more(self):
        dps = self._dps()
        assert dps, "the page must still parse, or this test proves nothing"
        wrong = [
            (d.metric_raw, d.currency, d.units) for d in dps
            if d.units == "crores" or d.currency == "INR"
        ]
        assert not wrong, (
            "rows from a filing that declares millions of USD are labelled INR crores: "
            f"{wrong[:4]}"
        )

    def test_the_scale_is_read_from_the_document(self):
        dps = self._dps()
        units = {d.units for d in dps}
        assert units == {"millions"}, f"expected every row in millions, got {units}"

    def test_the_currency_is_read_from_the_document(self):
        dps = self._dps()
        currencies = {d.currency for d in dps}
        assert currencies == {"USD"}, f"expected every row in USD, got {currencies}"

    def test_the_value_is_unchanged_by_this_fix(self):
        """Reading the units must not change a single figure.

        This fix relabels rows. If it moved a number, it would be a different change wearing this
        one's commit message, and the figures in section 23 would no longer describe these pages.
        """
        dps = {
            d.metric_raw: d.value
            for d in parse_predicted_statement_page(
                str(HCLTECH), 4, "BALANCE SHEET", "nse_filing", annual_only=False,
                company_id="hcltech_hcltech",
            )
        }
        # Printed on the page: "Goodwill 2,519 2,519" and "TOTAL ASSETS 11,806 12,261".
        assert dps.get("Goodwill") is not None
        assert max(dps.values()) > 11_000, (
            "TOTAL ASSETS is 11,806 in the filing and must still parse to that magnitude; a much "
            f"smaller number means this fix disturbed the values. Largest seen: {max(dps.values())}"
        )

    def test_the_units_are_recorded_in_the_provenance(self):
        """An undetermined unit must be distinguishable from an unexamined one."""
        dps = self._dps()
        assert dps
        for d in dps[:6]:
            assert "USD/millions" in d.source_location, (
                f"provenance does not say where the units came from: {d.source_location!r}"
            )


@needs_infy
class TestTheIndianFilingsStillReadCorrectly:
    def test_infosys_rows_are_inr_crores(self):
        dps = parse_predicted_statement_page(
            str(INFOSYS), 99, "BALANCE SHEET", "nse_filing", annual_only=False,
            company_id="infy_infy",
        )
        assert dps
        pairs = {(d.currency, d.units) for d in dps}
        assert pairs == {("INR", "crores")}, f"expected INR crores throughout, got {pairs}"