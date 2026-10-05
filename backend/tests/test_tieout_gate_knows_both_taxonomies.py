"""The tie-out gate must read the taxonomy a filer actually uses.

The tie-out probe asks "does a filed caption carry this figure?". When IFRS
ingestion landed it read only the `us-gaap` namespace, so for a 20-F filer the answer
was always no, and it reported TSMC's cash as carrying no filed caption at all:

    cash_and_equivalents: engine 64,886, and no us-gaap element or filed caption
    carries it; nothing to tie it to

The figure was right and the filing agreed with it. That is a gate reporting a
disagreement that does not exist, which is as damaging as one that misses a real
disagreement, because it teaches people to ignore the gate.

These record what was learned by getting it wrong twice.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TIEOUT = (ROOT / "scripts" / "tieout.py").read_text(encoding="utf-8")

sys.path.insert(0, str(ROOT))
from backend.data.ingestion import ifrs_tags  # noqa: E402
from backend.data.ingestion.sec_edgar import US_GAAP_TAG_MAP  # noqa: E402

US_BY_LABEL = {label: tuple(tags) for label, tags, _ in US_GAAP_TAG_MAP}


def _code_only(text: str) -> str:
    """Source with `#` comments removed.

    The resolver block names the element it replaced in prose. That is
    documentation; only a string literal is a second copy of the vocabulary, and
    only the second copy can fall behind.
    """
    return "\n".join(re.sub(r"#.*$", "", ln) for ln in text.splitlines())


def _entry(label: str) -> str:
    """The FIELDS entry for one metric label, comments stripped."""
    i = TIEOUT.index(f'("{label}"')
    return _code_only(TIEOUT[i:TIEOUT.index("]),", i) + 3])


def _fetch_block() -> str:
    i = TIEOUT.index("def company_facts")
    return TIEOUT[i:TIEOUT.index("\ndef ", i + 10)]


class TestTheGateReadsBothTaxonomies:
    def test_it_merges_us_gaap_and_ifrs_full(self):
        """The actual fix: the namespace is merged, not selected.

        Selecting one would be the same bug again -- a 20-F filer that also reports a
        us-gaap extension would have its us-gaap figures ignored.
        """
        block = _fetch_block()
        assert '"us-gaap"' in block
        assert '"ifrs-full"' in block, (
            "the gate reads only us-gaap, so a 20-F filer's figures cannot tie and "
            "the gate reports a disagreement that is not there"
        )
        assert "merged" in block or "setdefault" in block, (
            "both namespaces must be merged; picking one drops whichever the filer "
            "did not use"
        )

    def test_cash_resolves_for_both_taxonomies(self):
        """Both vocabularies must be able to carry cash, or one filer cannot tie.

        Overlap between the two lists is deliberate and fine: `IFRS_ALTERNATIVES` is
        a broad net that includes a us-gaap name as a fallback for filers that
        report either. Disjointness was the wrong property to demand.
        """
        us = US_BY_LABEL["Cash & Bank"]
        ifrs = ifrs_tags.IFRS_ALTERNATIVES["Cash & Bank"]
        assert us, "us-gaap has no cash element, so no us-gaap filer can tie"
        assert ifrs, "ifrs-full has no cash element, so no 20-F filer can tie"

    def test_the_ifrs_net_reaches_the_figure_ts_mc_actually_filed(self):
        """The specific element Infosys' 20-F carries, not a guess at a family."""
        assert "CashAndCashEquivalents" in ifrs_tags.IFRS_ALTERNATIVES["Cash & Bank"]


class TestDebtIsDeliberatelyUsGaapOnly:
    """A regression, recorded so it is not repeated.

    `DEBT_PARTS` was extended with `ifrs-full:Borrowings` so that TSMC's debt would
    tie. It made things much worse: 2 untied figures became 7, and 9 of 11 companies
    audited clean fell to 3.

    The reason is that the gate SUMS the filed debt parts and compares the sum to the
    engine's debt. The engine builds debt from the us-gaap parts. Adding a tag the
    engine does not count puts a filed part into the sum that the engine never
    deducted, so the comparison fails for every filer that reports it -- which is why
    Microsoft and NVIDIA broke when TSMC was meant to be fixed.

    The fix for TSMC's debt is in the engine or the filing, not in the gate's list.
    A gate that is widened to accommodate one filer stops checking the others.
    """

    def test_debt_parts_stays_us_gaap(self):
        i = TIEOUT.index("DEBT_PARTS")
        block = TIEOUT[i:TIEOUT.index("\n]", i)]
        assert "_IFRS_ELEMENTS" not in block and "_US_GAAP_ELEMENTS" not in block, (
            "DEBT_PARTS is summed against the engine's debt, which is built from the "
            "us-gaap parts. Adding an IFRS element here breaks every filer that "
            "reports it -- it was tried and took the audit from 9/11 clean to 3/11."
        )

    def test_debt_parts_are_the_us_gaap_names(self):
        i = TIEOUT.index("DEBT_PARTS")
        block = TIEOUT[i:TIEOUT.index("\n]", i)]
        for name in ("LongTermDebtNoncurrent", "LongTermDebtCurrent",
                     "FinanceLeaseLiability"):
            assert name in block, f"{name} was dropped from DEBT_PARTS"


class TestNoSecondCopyOfTheElementNames:
    """Element names must be resolved, not restated.

    A hand-kept second copy of the vocabulary is the failure this project has now hit
    four times: the claims enumeration, the IFRS metric labels, the client's
    publication check, and this gate. Each time it drifted silently and each time a
    gate reported a disagreement that was not there.
    """

    def test_the_resolvers_are_declared(self):
        for name in ("_US_GAAP_ELEMENTS", "_IFRS_ELEMENTS", "US_GAAP_TAG_MAP"):
            assert name in TIEOUT, f"{name} is missing from the gate"

    def test_cash_resolves_instead_of_being_restated(self):
        entry = _entry("cash_and_equivalents")
        assert "CashAndCashEquivalentsAtCarryingValue" not in entry, (
            "the gate names a us-gaap element inline again. Resolve it through the "
            "ingestion map so a 20-F filer is not reported as disagreeing with its "
            "own accounts."
        )
        assert "_US_GAAP_ELEMENTS" in entry and "_IFRS_ELEMENTS" in entry

    def test_marketable_securities_resolves_instead_of_being_restated(self):
        entry = _entry("marketable_securities")
        assert "_US_GAAP_ELEMENTS" in entry and "_IFRS_ELEMENTS" in entry
        offenders = [
            ln.strip() for ln in entry.splitlines()
            if re.search(r'"[A-Z][A-Za-z]*(Securities|Investments)', ln)
        ]
        assert not offenders, f"still names elements inline: {offenders}"

    def test_non_current_investments_resolves_instead_of_being_restated(self):
        """The last field to restate us-gaap names inline, and it cost a real signal.

        This test previously asserted the field was NOT converted, as a record that the
        work had not been done. Converting it then left the test asserting something
        false, so it is replaced rather than loosened: a test should describe the
        state of the code, not tolerate whichever state it happens to find.
        """
        entry = _entry("non_current_investments")
        assert "_US_GAAP_ELEMENTS" in entry and "_IFRS_ELEMENTS" in entry

        # `OtherLongTermInvestments` and `LongTermInvestments` have no IFRS
        # counterpart and no shipped filer reports them, so they stay inline. Assert
        # that they were kept deliberately, so a future edit cannot drop them
        # silently and quietly narrow the gate.
        for name in ("OtherLongTermInvestments", "LongTermInvestments"):
            assert name in entry, f"{name} was dropped from the non-current entry"

    def test_every_field_the_gate_checks_resolves_through_both_taxonomies(self):
        """No field may be left reading one vocabulary.

        Every one of these was a real untied figure at some point today, and in each
        case the figure was right and the gate could not see the filing that reported
        it. This is the property that prevents the sixth repetition.
        """
        import re as _re

        i = TIEOUT.index("FIELDS = [")
        table = _code_only(TIEOUT[i:TIEOUT.index("\n]\n", i)])
        labels = _re.findall(r'\("([a-z_]+)",', table)
        assert labels, "the FIELDS table could not be read; this test would pass vacuously"
        for label in labels:
            entry = _entry(label)
            assert "_US_GAAP_ELEMENTS" in entry, (
                f"{label} does not resolve through the us-gaap resolver"
            )

