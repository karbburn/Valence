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
HCLTECH_INDAS = Path("backend/data/filings/nse/hcltech-indas-2026-04.pdf")
TCS = Path("backend/data/filings/nse/tcs-outcome-2026-04.pdf")

needs_hcl = pytest.mark.skipif(not HCLTECH.exists(), reason="no HCLTech filing committed")
needs_infy = pytest.mark.skipif(not INFOSYS.exists(), reason="no Infosys filing committed")
needs_tcs = pytest.mark.skipif(not TCS.exists(), reason="no TCS filing committed")
needs_indas = pytest.mark.skipif(
    not HCLTECH_INDAS.exists(), reason="no audited Ind-AS filing committed"
)


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


@needs_tcs
class TestTheTcsCroreBannerResolvesToInr:
    """TCS prints "( crore)" with the rupee glyph unextractable.

    `declared_units` rightly leaves that undetermined -- it cannot see a
    currency token. But the caller knows the source is an NSE filing, and an
    NSE filing denominated in crores is rupees by construction, so the rows
    arrive as INR crores instead of dying in the currency validator. Any
    other source keeps the empty string; HCLTech's USD rows are untouched
    because their currency is present, not empty.
    """

    def _dps(self):
        return parse_predicted_statement_page(
            str(TCS), 10, "BALANCE SHEET", "nse_filing", annual_only=False,
            company_id="tcs_tcs",
        )

    def test_tcs_rows_carry_inr_crores(self):
        dps = self._dps()
        assert dps, "the page must still parse, or this test proves nothing"
        pairs = {(d.currency, d.units) for d in dps}
        assert pairs == {("INR", "crores")}, f"expected INR crores throughout, got {pairs}"

    def test_the_figures_are_untouched_by_the_fill(self):
        """The fill relabels rows. A number that moved would be a different
        change wearing this one's message."""
        dps = [
            (d.period_label, d.value) for d in self._dps()
            if d.metric_raw == "Property, plant and equipment"
        ]
        assert ("FY26", 11032.0) in dps, (
            "consolidated PP&E prints 11,032 for FY26; a different figure means "
            f"the fill disturbed the values. Got {dps}"
        )

    def test_the_provenance_names_the_resolved_units(self):
        dps = self._dps()
        assert dps
        for d in dps[:6]:
            assert "INR/crores" in d.source_location, (
                f"provenance does not say where the units came from: {d.source_location!r}"
            )

    def test_the_fill_is_gated_on_the_nse_source(self):
        """The never-assume rule stands everywhere else: only an NSE filing's
        crore scale resolves to INR, so assert the gate rather than trusting
        the two tests above to cover it."""
        import inspect
        import re

        from backend.data.parsers import pdf_tables

        src = inspect.getsource(pdf_tables.parse_predicted_statement_page)
        m = re.search(r'page_currency = "INR"\n', src)
        assert m, "the INR fill is gone; TCS rows go back to dying in validation"
        guard = src[max(0, m.start() - 400):m.start()]
        assert 'source == "nse_filing"' in guard, (
            "the INR fill is no longer gated on the NSE source, so it answers "
            "for every source and the never-assume rule is dead"
        )


class TestTheParenthesisedScaleDeclaration:
    """HCLTech's audited Ind-AS face prints "(~ in crores)" in its header.

    The rupee glyph extracts as "~", so neither the symbol pattern nor the bare
    "( crore)" pattern finds anything. The parenthesised form is the
    declaration the page makes about its own scale, so a paren containing "in
    crores" reads the scale -- and only the scale, unless a currency token is
    printed inside the same paren.
    """

    def test_a_parenthesised_scale_with_no_readable_currency_stays_half_read(self):
        currency, units = declared_units(
            "HCL Technologies Limited Consolidated Balance Sheet (~ in crores) "
            "As at March 31, 2026 ASSETS"
        )
        assert (currency, units) == ("", "crores"), (
            "the page declares its scale inside parentheses and no readable currency; "
            f"got {(currency, units)!r}"
        )

    def test_a_currency_printed_inside_the_parentheses_is_read_from_it(self):
        currency, units = declared_units("Particulars (Rs in crores) Note 2026 2025")
        assert (currency, units) == ("INR", "crores"), (
            "a currency token inside the same paren is printed evidence, not a default"
        )

    def test_a_bare_scale_outside_parentheses_is_not_a_declaration(self):
        """The paren IS the declaration; a sentence about units is prose.

        Accounting-policy paragraphs say "presented in crores" about notes while
        the statement beside them may be in a different scale, so a bare phrase
        keeps answering nothing.
        """
        currency, units = declared_units(
            "The figures in the schedule below are presented in crores and are unaudited."
        )
        assert (currency, units) == ("", ""), (
            f"bare prose named a scale and it was taken as a declaration: {(currency, units)!r}"
        )


class TestTheClosingParenIsTheDeclarationsResidue:
    """Reliance's audited consolidated face declares "(Rs. in crore)" with the "(Rs."
    run missing from extraction, leaving a bare "in crore)" in the banner slot under
    the title.

    The closing paren is what separates this from the prose the refusals above
    protect: no sentence about units carries one. The document corroborates the
    reading itself -- its segment page prints the same banner with the open paren
    surviving as "(~ in crorel" -- and the figures match crore reality, so the
    scale is read and the currency stays empty for the NSE fill, exactly as the
    half-read HCLTech declaration above it.
    """

    def test_a_scale_before_a_closing_paren_with_no_open_paren_reads(self):
        currency, units = declared_units(
            "AUDITED CONSOLIDATED BALANCE SHEET AS AT 31st MARCH, 2026 in crore) "
            "Particulars As at 31st March, 2025 ASSETS"
        )
        assert (currency, units) == ("", "crores"), (
            "the banner's residue states the scale and no readable currency; "
            f"got {(currency, units)!r}"
        )

    def test_the_singular_scale_reads_as_the_canonical_scale_name(self):
        """The validator admits only "crores", so a singular reading that kept
        "crore" would refuse every company it touched."""
        _currency, units = declared_units("Particulars As at 2025 in crore)")
        assert units == "crores", f"singular scale must read as the canonical name: {units!r}"

    def test_an_open_paren_without_its_close_is_not_a_declaration(self):
        """The segment page's "(~ in crorel" has the open paren and noise where the
        close belongs. The close paren is the signal, so its absence refuses --
        and that page is notes, never a parsed statement, so nothing is lost."""
        assert declared_units("Notes (~ in crorel Particulars") == ("", "")


@needs_indas
class TestTheAuditedIndasFaceReadsAsTheRupeesItDeclares:
    """The end-to-end claim on the document that replaced the IFRS attachment.

    The whole reason the header reader exists is that this company's cache once
    held a document whose figures were NOT rupees. The audited Ind-AS face
    prints "(~ in crores)", its rows reach normalization as INR crores, and the
    units validator accepts the company. A single row carrying another scale
    would refuse the whole normalize, so the whole page must agree.
    """

    def _dps(self):
        return parse_predicted_statement_page(
            str(HCLTECH_INDAS), 3, "BALANCE SHEET", "nse_filing", annual_only=False,
            company_id="hcltech_hcltech",
        )

    def test_every_row_carries_the_declared_scale(self):
        dps = self._dps()
        assert len(dps) == 98, (
            f"the audited face yields 98 rows; a different count means the parse changed "
            f"underneath the migration. Got {len(dps)}."
        )
        pairs = {(d.currency, d.units) for d in dps}
        assert pairs == {("INR", "crores")}, (
            f"expected INR crores throughout, got {pairs}"
        )

    def test_the_resolved_units_reach_the_provenance(self):
        dps = self._dps()
        for d in dps[:6]:
            assert "INR/crores" in d.source_location, (
                f"provenance does not say where the units came from: {d.source_location!r}"
            )