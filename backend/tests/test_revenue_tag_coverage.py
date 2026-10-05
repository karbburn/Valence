"""A filer that tags revenue in an accepted form must not silently vanish.

The engine reads revenue through a hand-kept list of XBRL tags in
``US_GAAP_TAG_MAP``. Anything not on that list is not an error and not a warning
-- the company simply never appears, which is how ``RevenueFromContractWith-
CustomerIncludingAssessedTax`` cost us several hundred filers with no signal at
all.

This is the third instance of the same defect in this repository, after
``CIK_REGISTRY`` returning another company's financials and a metadata registry
that hardcoded provenance. The pattern is a table that short-circuits an
authority, where an omission is invisible rather than loud.

So the table is checked against the filers it is meant to serve. The check is
deliberately structural -- it asserts against the tag list and against real
filer facts -- rather than a snapshot of a coverage number, which would drift
the moment the index or the SEC changes and would quietly stop testing anything.
"""

from __future__ import annotations

from typing import List

import pytest

from backend.data.ingestion.sec_edgar import _revenue_tags as engine_revenue_tags
from backend.tests.conftest import fetch_company_facts

# The User-Agent and gzip handling used to live here and are now in
# `fetch_company_facts`, so that a network failure is handled in one place for
# both live-EDGAR tests rather than being re-implemented per file.


# Read the engine's own accessor rather than re-walking US_GAAP_TAG_MAP here.
# This helper was the last surviving copy of the tag list, and a copy in a test is
# how a fix lands in the engine and not in the assertion that claims to cover it.
def _revenue_tags() -> List[str]:
    return list(engine_revenue_tags())


class TestRevenueTagCoverage:
    def test_including_assessed_tax_is_accepted(self) -> None:
        """The tag whose absence hid real filers must be present.

        Filers tag revenue including or excluding sales taxes collected on the
        issuer's behalf. Both are defensible; assuming one loses the filer that
        chose the other. Liberty Latin America, Annaly, Northwest Bancshares and
        AEGON were in that group.
        """
        assert "RevenueFromContractWithCustomerIncludingAssessedTax" in _revenue_tags()

    def test_the_common_revenue_tags_are_all_accepted(self) -> None:
        """Every tag in ordinary circulation, so the list is not merely longer.

        Asserting one tag is present permits a later edit that swaps it for a
        different omission. This pins the set.
        """
        expected = {
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet",
            "OperatingRevenue",
            "TotalRevenueNet",
            "TotalRevenuesAndOtherIncome",
        }
        assert expected <= set(_revenue_tags()), (
            "revenue tag coverage regressed; missing "
            f"{sorted(expected - set(_revenue_tags()))}"
        )

    def test_no_duplicate_revenue_tags(self) -> None:
        """A duplicate suggests a merge that copied rather than reconciled.

        Harmless today, and the kind of thing that hides a disagreement between
        two entries about the same concept.
        """
        tags = _revenue_tags()
        assert len(tags) == len(set(tags)), "duplicate entries in the revenue tag list"

    def test_revenue_is_its_own_priority_group_and_not_reused(self) -> None:
        """Revenue must not be satisfied by a tag that means something else.

        A bank files ``GainLossOnSalesOfLoansNet`` and a REIT files
        ``AccruedFeesAndOtherRevenueReceivable``. Neither is revenue, and a
        substring match over the tag namespace would treat both as one -- which
        is how six banks and two REITs were briefly reported as an ingestion bug
        instead of as filers no revenue DCF should model.
        """
        tags = set(_revenue_tags())
        for impostor in (
            "GainLossOnSalesOfLoansNet",
            "AccruedFeesAndOtherRevenueReceivable",
            "GainsLossesOnSalesOfOtherRealEstate",
        ):
            assert impostor not in tags, (
                f"{impostor} is not a revenue figure and must not be read as one"
            )


class TestAgainstRealFilers:
    """The list is checked against what filers actually publish, not against taste.

    A structural test can only assert what someone thought to write down. This
    asserts the thing that matters: that a filer whose facts contain nothing but
    one accepted tag is one the ingestion can build from.
    """

    @staticmethod
    def _facts(cik: int):
        return fetch_company_facts(cik)

    @pytest.mark.network
    def test_a_company_tagging_only_the_including_variant_is_readable(self) -> None:
        """Liberty Latin America tags revenue only as ...IncludingAssessedTax.

        Before the tag was added the engine found no revenue for it, produced no
        model, and raised nothing. This asserts the specific gap is closed against
        the filer that exposed it.
        """
        facts = self._facts(1712184)  # Liberty Latin America Ltd, per the ticker index
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        assert "RevenueFromContractWithCustomerIncludingAssessedTax" in us_gaap, (
            "expected this filer to tag revenue only in the IncludingAssessedTax form"
        )
        assert not any(
            tag in us_gaap
            for tag in set(_revenue_tags()) - {"RevenueFromContractWithCustomerIncludingAssessedTax"}
        ), (
            "this test was chosen because it isolates one tag; if the filer now "
            "uses several, pick another or update the assertion deliberately"
        )
        tags = _revenue_tags()
        assert "RevenueFromContractWithCustomerIncludingAssessedTax" in tags
