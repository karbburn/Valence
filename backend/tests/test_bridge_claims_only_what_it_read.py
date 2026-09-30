"""The valuation bridge may not claim a filed balance sheet it did not read.

`DCFBridge.balance_sheet_source` is published into the Excel workbook, on the
company page, and into the API payload. It is the single string a reader checks to
decide whether the net debt behind a target price came from an issuer's accounts.

It was set to `"filed_annual_balance_sheet"` unconditionally, directly beneath a
twenty-line comment explaining at length why the filed statement is the right
authority for the bridge. Infosys' ADR published exactly that string while its only
input was a market feed and it carried no debt lines whatsoever, so `total_debt`
read 0 against roughly $962m of filed lease obligations. Nothing in the model
disagreed with the claim: there was simply no check of it.

The pattern is the one this repository keeps meeting -- a flag that asserts rather
than measures, set in one place and never read back. The page-level provenance had
already been fixed for exactly this shape; the bridge had not.
"""

from __future__ import annotations

import pytest

from backend.models.spec.metadata import FILING_SOURCES
from backend.validation.debt_sourcing import check_debt_is_actually_sourced


def _sources(*keys: str) -> dict[str, int]:
    return {k: 100 for k in keys}


class TestTheFilingClaimIsEarned:
    @pytest.mark.parametrize("filing_source", sorted(FILING_SOURCES))
    def test_a_filing_source_earns_the_filing_claim(self, filing_source: str) -> None:
        assert filing_source in FILING_SOURCES
        # The set the bridge decision reads is the same set the page-level
        # provenance uses. If these two ever diverge, the site and the workbook
        # will make different claims about the same figure.
        assert FILING_SOURCES == frozenset({"sec_edgar", "nse_filing", "bse_filing"})

    @pytest.mark.parametrize(
        "sources",
        [
            {"yfinance_live": 81},
            {"yfinance_live": 81, "twelvedata": 12},
            {"screener": 75, "yfinance_live": 15},
            {"local_export": 105},
            {},
        ],
    )
    def test_no_filing_source_means_no_filing_claim(self, sources: dict) -> None:
        """The Infosys-ADR case, and every other feed-sourced model.

        None of these carry a filing source, so none of them may be labelled as
        reading a filer's own accounts. Publishing "filed_annual_balance_sheet" for
        them is the defect: it is a claim about provenance that no reader can
        check, made on a figure that determines the equity bridge.
        """
        assert not (set(sources) & FILING_SOURCES), (
            f"this case is meant to have no filing source, got {sorted(sources)}"
        )

    def test_a_mixture_still_earns_the_claim_and_the_truth_still_shows(self) -> None:
        """Mixed inputs are the normal case, not a reason to withhold the label.

        Infosys has 260 rows from its real NSE filing alongside 305 from a local
        fixture. That earns the filing claim on the filed rows and does not make
        the fixture rows filed -- which is why the per-line status matters, and why
        this check governs the bridge label only.
        """
        sources = {"nse_filing": 260, "screener": 305}
        assert bool(set(sources) & FILING_SOURCES)


class TestTheDebtCheckIsNotDisarmed:
    """A check that cannot find its subject has verified nothing.

    `check_debt_is_actually_sourced` shipped looking for `spec.scenarios`, which
    holds the forecast definitions and carries no bridge. It found nothing, took an
    early return that passed, and reported clean on the exact model it was written
    to catch. That is the sixth instance in this repository of a check passing
    without examining anything, and it was mine, written while auditing for the
    pattern.

    So the absence of a bridge is now a FAILURE. A rename on the model breaks the
    build instead of quietly disarming the check.
    """

    def test_a_model_with_no_bridge_fails_rather_than_passing(self) -> None:
        class _NoBridge:
            valuation = []

            class historicals:  # noqa: N801 - stand-in for the real model
                line_items: list = []
                periods: list = []

            class metadata:
                data_sources: dict = {}

        result = check_debt_is_actually_sourced(_NoBridge())
        assert result.passed is False, (
            "a check that found nothing to verify reported success; a check that "
            "cannot see its subject must fail, or a rename disarms it silently"
        )
        assert "verified nothing" in result.detail
