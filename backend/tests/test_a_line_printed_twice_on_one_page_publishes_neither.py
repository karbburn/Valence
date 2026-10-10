"""One line printed twice on one page under one half publishes neither printing.

HCLTech's audited Ind-AS balance sheet prints the caption "Billed" twice on the
same page in the same (current) half: 23,585 under trade receivables and 3,726
under trade payables. Both rows carry the registry's caption and the half tag,
so both reach `trade_receivables`, and before this gate the reader was shown
whichever the row order happened to put last -- a payables figure arriving as
receivables, or the filing's real receivables discarded for the payables one,
with nothing on the page saying which happened. The migration refused eight
such rows across the two captions ("Billed" and "Unbilled") and both years.

The gate is scoped narrowly so the honest duplicates keep publishing:

  * different halves are different lines (HCLTech's "(i) Investments" is 130
    non-current and 6,960 current on ONE page, each on its own key);
  * different pages are different readings, which the selector already ranks;
  * a feed row has no page coordinate at all, so a screener estimate beside a
    filing figure is a second source rather than a second printing;
  * agreeing printings are not a conflict, because two rows that say the same
    thing cannot publish a contradiction.

Every refused caption lands in the review queue as pending, so the refusal is a
recorded unknown rather than a silently missing figure.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from backend.data.store import RawDatapoint
from backend.normalization.financials import mapper


def _raw(
    label: str,
    value: float,
    location: str,
    half: str | None = None,
    period: str = "FY26",
    source: str = "nse_filing",
) -> RawDatapoint:
    return RawDatapoint(
        id=f"gate-{label[:8].replace(' ', '')}-{value}-{period}",
        company_id="fixture_co",
        metric_raw=label,
        period_label=period,
        period_end_date=datetime(2026, 3, 31).date(),
        value=value,
        currency="INR",
        units="crores",
        source=source,
        source_location=location,
        section="BALANCE SHEET",
        bs_half=half,
        status="reported",
        update_date=datetime.now(),
    )


def _pending(db, caption: str) -> list[tuple]:
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(
            "SELECT suggested_key, status FROM taxonomy_review_queue "
            "WHERE company_id='fixture_co' AND metric_raw=?",
            (caption,),
        ).fetchall()
    finally:
        conn.close()


class TestOneLineTwiceOnOnePage:
    def test_neither_printing_publishes(self, tmp_path):
        dps = [
            _raw("Billed", 23585.0, "indas p.4 y=423.8 Billed", half="current"),
            _raw("Billed", 3726.0, "indas p.4 y=558.0 Billed", half="current"),
        ]
        canonical, _mappings, unmapped = mapper.map_raw_datapoints(
            dps, db_path=tmp_path / "queue.db"
        )
        keys = [c.canonical_key for c in canonical]
        assert "canonical.bs.trade_receivables" not in keys, (
            "two differing printings of one line under one half both staged, so the reader "
            f"gets whichever wrote last: {keys}"
        )
        assert unmapped == [], (
            f"a refused caption must be a recorded refusal, not an unmapped gap: {unmapped}"
        )

    def test_the_refusal_is_queued_as_pending(self, tmp_path):
        db = tmp_path / "queue.db"
        dps = [
            _raw("Billed", 23585.0, "indas p.4 y=423.8 Billed", half="current"),
            _raw("Billed", 3726.0, "indas p.4 y=558.0 Billed", half="current"),
        ]
        mapper.map_raw_datapoints(dps, db_path=db)
        rows = _pending(db, "Billed")
        assert rows, (
            "the conflicted caption was dropped without reaching the review queue, so the "
            "refusal exists nowhere a reader can find it"
        )
        assert all(status == "pending" for _key, status in rows), rows

    def test_two_halves_of_one_caption_are_two_lines(self, tmp_path):
        """The investments pair: the gate must not eat what the half tag separates."""
        dps = [
            _raw("(i) Investments", 130.0, "indas p.4 y=181.0 Investments", half="noncurrent"),
            _raw("(i) Investments", 6960.0, "indas p.4 y=390.0 Investments", half="current"),
        ]
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            dps, db_path=tmp_path / "queue.db"
        )
        by_key = {c.canonical_key: c.value for c in canonical}
        assert by_key == {
            "canonical.bs.non_current_investments": 130.0,
            "canonical.bs.current_investments": 6960.0,
        }, (
            "one caption printed in both halves must publish once per half on each half's "
            f"own key: {by_key}"
        )

    def test_two_pages_are_two_readings_and_both_survive(self, tmp_path):
        dps = [
            _raw("Billed", 23585.0, "docA p.4 y=423.8 Billed", half="current"),
            _raw("Billed", 24001.0, "docB p.11 y=423.8 Billed", half="current"),
        ]
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            dps, db_path=tmp_path / "queue.db"
        )
        rows = [
            c for c in canonical if c.canonical_key == "canonical.bs.trade_receivables"
        ]
        assert len(rows) == 2, (
            "a same-key pair from different pages is a second reading for the selector to "
            f"rank, not a conflict to refuse: {[(r.value, r.status) for r in rows]}"
        )
        # Staging order is the order the reader saw them, and the survivors keep it.
        assert [r.value for r in rows] == [23585.0, 24001.0]

    def test_a_feed_row_beside_a_filing_row_is_not_a_second_printing(self, tmp_path):
        """A screener estimate has no page coordinate, so it can conflict with nothing.

        Refusing the pair would withhold the filing's own reading on behalf of a
        third-party estimate, which is the opposite of what the gate is for.
        """
        dps = [
            _raw(
                "Billed",
                23585.0,
                "indas p.4 y=423.8 Billed",
                half="current",
            ),
            _raw(
                "Billed",
                22500.0,
                "screener!Sheet1!F42",
                half="current",
                source="screener",
            ),
        ]
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            dps, db_path=tmp_path / "queue.db"
        )
        rows = [
            c for c in canonical if c.canonical_key == "canonical.bs.trade_receivables"
        ]
        assert len(rows) == 2, (
            f"a feed row and a filing row are two sources, not two printings: {rows}"
        )

    def test_printings_that_agree_are_not_a_conflict(self, tmp_path):
        """Two rows saying the same thing cannot publish a contradiction."""
        dps = [
            _raw("Billed", 23585.0, "indas p.4 y=423.8 Billed", half="current"),
            _raw("Billed", 23585.0, "indas p.4 y=558.0 Billed", half="current"),
        ]
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            dps, db_path=tmp_path / "queue.db"
        )
        rows = [
            c for c in canonical if c.canonical_key == "canonical.bs.trade_receivables"
        ]
        assert len(rows) == 2, (
            f"agreeing printings were refused as a conflict: {rows}"
        )


class TestTheHalfRouteTheGateDependsOn:
    """The investments route is what keeps the gate from eating that pair."""

    def test_the_current_half_moves_to_the_current_key(self):
        assert (
            mapper._key_for_half("canonical.bs.non_current_investments", "current")
            == "canonical.bs.current_investments"
        )

    def test_the_noncurrent_half_keeps_the_registry_key(self):
        assert (
            mapper._key_for_half("canonical.bs.non_current_investments", "noncurrent")
            == "canonical.bs.non_current_investments"
        )

    def test_a_key_without_a_pair_is_untouched(self):
        assert mapper._key_for_half("canonical.bs.ppe", "current") == "canonical.bs.ppe"
