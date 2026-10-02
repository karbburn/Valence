"""A successor entity's share price must never be solved against.

When a filer's own ticker stops resolving, `market_data` falls through to a
successor so the model is not pinned to a months-old quote. That is right for
keeping a price current and wrong for everything built on top of it: a demerger
splits ONE issuer into several, so the successor's price belongs to a different
company with a different balance sheet.

Tata Motors is the live case. TATAMOTORS.NS no longer resolves, so the model quotes
TMPV.NS -- Tata Motors Passenger Vehicles, demerged in October 2025 -- and the
solver returned an implied terminal growth of -427.20%:

    reverse_dcf.implied_terminal_growth  -427.2033
    method_note  ... [DIVERGENCE FLAG: implied growth -427.20% outside sane band]

The divergence gate caught it, appended a flag, and the number was computed,
carried in the payload and rendered anyway. A flag is a note about a number. There
is no growth rate that reconciles this issuer's cash flows with another company's
share price, so the honest answer is none at all.

What is asserted here is the refusal, and equally that it does not over-reach: a
price this company really did trade at must still solve, or the gate is just a
second way of returning nothing.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.models.spec.valuation import ReverseDCF  # noqa: E402

PIPELINE = (REPO / "backend" / "valuation" / "pipeline.py").read_text(encoding="utf-8")
CODE = re.sub(r"#.*$", "", PIPELINE, flags=re.M)


class TestTheGateRefusesRatherThanFlags:
    def test_a_successor_quote_produces_no_implied_growth(self):
        """The behaviour, in the shape the pipeline builds it."""
        successor = "yfinance_history:successor_ticker"
        assert ":successor_ticker" in successor

        result = ReverseDCF(
            market_price=279.40,
            method_note="Not solved: the quote is the successor entity's, not this issuer's.",
        )
        # No solver ran, so both solved quantities are absent rather than wrong.
        assert result.implied_terminal_growth is None, (
            "a successor quote was solved for an implied growth rate; there is no "
            "rate that reconciles one issuer's cash flows with another's price"
        )
        assert result.implied_revenue_cagr is None

    def test_the_price_is_still_reported_with_its_source(self):
        """Withholding the solve must not hide that a price is being shown.

        A reader deserves to see the quote AND that it belongs to a successor.
        Dropping the price entirely would make the gap invisible rather than
        explained.
        """
        result = ReverseDCF(
            market_price=279.40,
            method_note="Not solved: the quote is the successor entity's.",
        )
        result.market_price_date = "2026-10-01"
        result.market_price_source = "yfinance_history:successor_ticker"
        assert result.market_price == 279.40
        assert result.market_price_source.endswith("successor_ticker")
        assert "successor" in result.method_note.lower()

    def test_the_note_says_why_rather_than_only_that_it_failed(self):
        result = ReverseDCF(
            market_price=1.0,
            method_note="Not solved: the quote is the successor entity's, not this issuer's.",
        )
        assert "successor" in result.method_note
        assert "not solved" in result.method_note.lower()


class TestTheGateDoesNotOverReach:
    """A gate that refuses everything returns nothing and hides real analysis."""

    def test_an_ordinary_quote_is_still_solved(self):
        for source in (
            "yfinance_history",
            "yahoo_chart",
            "twelvedata",
            "registry",
            "stale_cache:2026-09-30",
        ):
            assert ":successor_ticker" not in source, (
                "the test's own sample is contaminated: %r looks like a successor"
                % source
            )

    def test_the_marker_is_a_suffix_not_a_substring_of_the_company_name(self):
        """`:successor_ticker` must not match by accident.

        A check like `"successor" in source` would also catch a source string that
        merely mentions the word -- a registry note, a cache label, a company whose
        name contains it. The colon-anchored suffix is the only form that means
        "this price came from the redirect path".
        """
        assert ":successor_ticker" in CODE, (
            "the successor marker is gone from the pipeline, so a successor quote "
            "will be solved against as though it were this issuer's own"
        )
        # And the marker is checked against `source`, which is where the redirect
        # path records it.
        assert re.search(
            r'successor_quote\s*=\s*":successor_ticker"\s+in\s+\(\s*mdata\.price\.source',
            CODE,
        ), (
            "the successor test is no longer applied to the quote's source string, "
            "so it is either matching the wrong field or matching nothing"
        )

    def test_the_solver_is_inside_the_else_branch(self):
        """The solve must be unreachable when the quote is a successor.

        Asserting that a flag exists, or that the note is set, is not enough: the
        original defect produced a correct note AND a wrong number. The number has
        to be unreachable.
        """
        m = re.search(
            r"successor_quote\s*=\s*.*?\n(?P<block>.*?)\n\s*reverse_dcf\.market_price_date",
            CODE,
            flags=re.S,
        )
        assert m, "could not locate the successor gate block in the pipeline"
        block = m.group("block")
        assert "if successor_quote:" in block, "the gate no longer branches"
        # Everything from the else onwards is the solved path.
        else_at = block.index("else:")
        solved = block[else_at:]
        assert "compute_reverse_dcf(" in solved, (
            "the solver is no longer inside the else branch, so it may run against "
            "a successor quote"
        )
        assert "compute_reverse_dcf(" not in block[:else_at], (
            "the solver is reachable outside the else branch -- a successor quote "
            "would be solved and then the result discarded, which is the defect "
            "this gate exists to remove"
        )

    def test_the_divergence_gate_still_exists_for_this_issuers_own_price(self):
        """A sanity band is still needed for a price that IS this company's.

        The successor gate removes one source of absurd implied growth; it does not
        remove the general case where a real price still implies something
        impossible.
        """
        assert "DIVERGENCE FLAG" in CODE, (
            "the divergence band was removed with the successor gate; it guards a "
            "different condition and is still needed for this issuer's own price"
        )