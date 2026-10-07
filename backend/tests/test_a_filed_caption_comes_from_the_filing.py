"""A filed caption must be read from the filing.

Every shipped US model was taking at least one line from a market feed -- for NVIDIA,
nine figures including trade payables and dividends paid. The numbers were right: the
tie-out confirmed the feed's trade payables equalled the filing's
`AccountsPayableCurrent` and its dividends equalled `PaymentsOfDividends`. The
provenance was not, and nothing on the page could tell a reader that.

The temptation when adding a tag to `US_GAAP_TAG_MAP` is to add it and move on. So
these tests check the whole path and the two traps that make a mapping inert:

  - a label the taxonomy has never heard of maps to nothing, silently
  - "Cash Dividends Paid" is suggested at MEDIUM confidence to `canonical.bs
    .cash_and_bank`, which is CASH ON THE BALANCE SHEET. Mapping that label would
    file a cash-flow movement as a balance, and the cross-statement guard would then
    refuse it -- correct behaviour, and a completely inert entry.
"""

from __future__ import annotations

import pathlib
import sys
from datetime import date, datetime

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.ingestion.ifrs_tags import IFRS_ALTERNATIVES, build_ifrs_map  # noqa: E402
from backend.data.ingestion.sec_edgar import US_GAAP_TAG_MAP  # noqa: E402
from backend.data.store import RawDatapoint  # noqa: E402
from backend.normalization.financials.mapper import map_raw_datapoints  # noqa: E402
from backend.normalization.taxonomy.registry import get_canonical_mapping  # noqa: E402

# What the market feed was supplying for nvda_us, verified by the tie-out against the
# filing. The filing-sourced figure must reproduce these EXACTLY: if it differs, one of
# the two is wrong and the tie-out is what settles it.
FEED_SUPPLIED = {
    "Trade payables": ("canonical.bs.trade_payables", "BALANCE SHEET",
                       [2699.0, 6310.0, 9812.0]),
    "Dividend Amount": ("canonical.cf.dividends_paid", "CASH FLOW",
                        [-395.0, -834.0, -974.0]),
}


def _map(label: str, section: str, value: float):
    dp = RawDatapoint(
        id="probe-%s" % label[:4].replace(" ", ""),
        company_id="nvda_us",
        metric_raw=label,
        period_label="FY26",
        period_end_date=date(2026, 1, 25),
        value=value,
        currency="USD",
        units="millions",
        source="sec_edgar",
        source_location="p",
        section=section,
        status="reported",
        update_date=datetime.now(),
    )
    return map_raw_datapoints([dp])


class TestTheEntryProducesAFigure:
    def test_the_label_is_in_the_readers_map(self):
        labels = {label for label, _tags, _stmt in US_GAAP_TAG_MAP}
        for label in FEED_SUPPLIED:
            assert label in labels, (
                "%r is not emitted by the SEC reader, so adding tags for it changes "
                "nothing" % label
            )

    def test_it_reaches_the_canonical_key_the_model_uses(self):
        for label, (expected_key, section, values) in FEED_SUPPLIED.items():
            canonical, _m, _u = _map(label, section, values[-1])
            assert canonical, (
                "%r produced NO canonical datapoint, so the entry is inert. The "
                "taxonomy may not know the label -- check `get_canonical_mapping` "
                "before assuming it does." % label
            )
            assert canonical[0].canonical_key == expected_key, (
                "%r landed on %s, not %s"
                % (label, canonical[0].canonical_key, expected_key)
            )

    def test_the_filing_agrees_with_the_feed_it_replaces(self):
        """Exact agreement, not approximate.

        The feed's figures were verified against the filing for NVIDIA, so a filing-
        sourced figure that differs means one of the two is wrong. This is the check
        that would catch a tag which means something adjacent rather than the same.
        """
        for label, (_key, section, values) in FEED_SUPPLIED.items():
            for v in values:
                canonical, _m, _u = _map(label, section, v)
                assert canonical, "%r produced nothing for %.1f" % (label, v)
                assert abs(canonical[0].value - v) < 0.005, (
                    "%r: filed %.1f became %.1f, which does not match the feed figure "
                    "the tie-out verified" % (label, v, canonical[0].value)
                )


class TestTheTrapsThatMakeAMappingInert:
    def test_a_label_the_taxonomy_has_never_heard_of_is_not_used(self):
        """The mistake this file exists to prevent.

        The obvious label for the dividends line is the one a filer prints --
        "Dividends", "Dividends paid", "Common Stock Dividend Paid" -- and every one
        of them is unmapped. Writing any of them into the reader's map yields an
        entry that produces nothing, and it looks like a working mapping in review.
        """
        from backend.normalization.taxonomy.mapping_engine import (
            suggest_canonical_mapping,
        )

        for label in ("Dividends", "Dividends paid", "Common Stock Dividend Paid"):
            assert get_canonical_mapping(label) is None, (
                "%r is now mapped, so this test's premise changed -- re-check which "
                "label the SEC entry should emit" % label
            )
            assert suggest_canonical_mapping(label).level == "low", (
                "%r is no longer a low-confidence suggestion; if it became medium or "
                "high it may now reach a key, and the SEC entry may be wrong"
                % label
            )

    def test_the_cash_dividends_trap_still_points_at_cash(self):
        """"Cash Dividends Paid" suggests a BALANCE SHEET key at medium confidence.

        That is the trap. Mapping it would file a cash-flow movement as cash in the
        bank, and the cross-statement guard would then refuse it -- so the entry would
        be inert while reading as correct. Asserted so that if the suggestion engine
        ever improves, this file says so rather than leaving a stale assumption.
        """
        from backend.normalization.taxonomy.mapping_engine import (
            suggest_canonical_mapping,
        )

        s = suggest_canonical_mapping("Cash Dividends Paid")
        assert s.canonical_key == "canonical.bs.cash_and_bank", (
            "the suggestion for 'Cash Dividends Paid' changed to %r; if it now points "
            "at canonical.cf.dividends_paid the SEC entry could use that label "
            "directly" % s.canonical_key
        )
        # And demonstrate the consequence rather than describing it.
        canonical, _m, _u = _map("Cash Dividends Paid", "CASH FLOW", -974.0)
        assert not canonical, (
            "'Cash Dividends Paid' from a cash-flow page now produces %s; if it "
            "produced cash_and_bank the dividends would be filed as cash in the bank"
            % [c.canonical_key for c in canonical]
        )

    def test_the_emitted_label_states_the_right_statement(self):
        """The map's statement code must agree with the statement it is filed under.

        A mislabelled entry is refused by the cross-statement guard, which is right in
        principle and useless in practice -- the figure simply never arrives.
        """
        by_label = {label: stmt for label, _tags, stmt in US_GAAP_TAG_MAP}
        expected = {"Trade payables": "BALANCE SHEET", "Dividend Amount": "CASH FLOW:"}
        for label, section in expected.items():
            assert by_label.get(label) == section, (
                "%r is filed under %r in the map but %r is where it comes from"
                % (label, by_label.get(label), section)
            )


class TestTheMapStaysHonestAboutWhatFilersFile:
    def test_no_candidate_tag_is_listed_twice(self):
        """A duplicate makes the map look broader than it is.

        The first version of the trade-payables entry listed `AccountsPayableCurrent`
        twice, which would have made the coverage claim in its comment read as two
        elements when it is one.
        """
        for label, tags, _stmt in US_GAAP_TAG_MAP:
            dupes = {t for t in tags if tags.count(t) > 1}
            assert not dupes, "%r lists %s more than once" % (label, sorted(dupes))


class TestTheElementOrderDecidesWhichMoneyIsRead:
    """Selection keeps the first candidate with an annual fact for a target year.

    So list order is behaviour, not documentation: the wrong element first reports a
    different figure under the same caption. Measured per filer against SEC
    companyfacts and the face of the balance sheet, 2026-10-06:

    AWI files no `AccountsPayableCurrent`. It files the trade slice as
    `AccountsPayableTradeCurrent` -- 91.0 / 105.8 / 123.6 at FY23-FY25, equal to the
    feed -- and prints ONE combined line, "Accounts payable and accrued expenses"
    (237.1 / 215.3), carried by `AccountsPayableAndAccruedLiabilitiesCurrent`. That
    element first would report trade payables plus accruals under a trade-payables
    key: bigger money, right caption family, nothing on the page to tell them apart.

    Meta files `AccountsPayableCurrent` only through 10-Q comparatives for these
    years, and 10-Q facts do not qualify as annual; its 10-Ks tag
    `AccountsPayableTradeCurrent` -- 4,849 / 7,687 / 8,894 at FY23-FY25, equal to the
    feed. Without the trade element in the list, no candidate holds an annual fact
    for any target year and the line stays on the feed rather than converting.
    """

    def test_the_trade_slice_precedes_the_combined_total(self):
        tags = next(t for label, t, _s in US_GAAP_TAG_MAP if label == "Trade payables")
        assert "AccountsPayableTradeCurrent" in tags, (
            "the trade slice is no longer a candidate, so AWI would read its combined"
            " trade-and-accruals element and Meta would keep nothing to convert"
        )
        assert tags.index("AccountsPayableTradeCurrent") < tags.index(
            "AccountsPayableAndAccruedLiabilitiesCurrent"
        ), (
            "the combined element now comes first, so AWI reads 237.1 of trade and"
            " accruals where its filed trade slice is 123.6 -- same caption, more"
            " money, undetectable on the page"
        )

    def test_both_lines_reach_the_ifrs_vocabulary(self):
        """The ADR filers file under ifrs-full, and both labels must resolve there.

        Infosys' 20-F supplies both lines exactly: `TradeAndOtherCurrentPayables`
        470 / 474 / 487 (USD) at FY23-FY25 and `DividendsPaid` 1,777 / 2,416 at
        FY24/FY25 as positive magnitudes -- equal to the feed in value, and in
        magnitude once the outflow rule signs it. TSM files neither element in USD:
        no plain trade-payables element exists in its facts (only parts of one, to
        trade suppliers and to related parties), and its `DividendsPaid` arrives in
        TWD while the reader takes USD. Both lines therefore stay on the feed for TSM
        -- absence, not a wrong figure.
        """
        assert IFRS_ALTERNATIVES.get("Trade payables") == (
            "TradeAndOtherCurrentPayables",
        ), (
            "the IFRS trade-payables entry changed to %r; it must stay the single"
            " element Infosys files, not a partial component"
            % (IFRS_ALTERNATIVES.get("Trade payables"),)
        )
        assert IFRS_ALTERNATIVES.get("Dividend Amount") == ("DividendsPaid",), (
            "the IFRS dividends entry changed to %r; without `DividendsPaid` the ADR"
            " filer's dividends never leave the feed"
            % (IFRS_ALTERNATIVES.get("Dividend Amount"),)
        )
        # `build_ifrs_map` re-checks that every IFRS label exists in the us-gaap map,
        # so carrying both entries out the other side proves the whole path: label
        # known, alternatives attached, section preserved.
        built = {label: (tags, stmt) for label, tags, stmt in build_ifrs_map(US_GAAP_TAG_MAP)}
        assert built.get("Trade payables") == (("TradeAndOtherCurrentPayables",), "BALANCE SHEET")
        assert built.get("Dividend Amount") == (("DividendsPaid",), "CASH FLOW:")
