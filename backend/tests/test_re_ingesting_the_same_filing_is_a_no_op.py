"""Re-ingesting the same filing must not change the store, and must not delete a figure.

`save_datapoints` keys rows on a uuid4, so two runs of the same ingestion never collide and
`INSERT OR REPLACE` never replaces anything. On the two paths that pass
`clear_existing=False` -- the India pipeline's screener+filing merge and the supplement pass
-- every re-run ADDED rows. `filing_derived` is a ratio of row COUNTS, so a model's
publication verdict depended on how many times the build tool had been run.

Measured on the live store before this change: `infy_infy` held 567 raw rows across 488
distinct natural keys, 72 duplicated, and 14 of those disagreeing on VALUE.

The dangerous half of that last number is not obvious from the counts, and reading the
filing is what settled it. Four rows share the caption "- Mutual fund units", the period
FY25/FY26 and the source `nse_filing`, with values -73,048 and +73,987 on printed page 104
-- OPPOSITE signs from one page at one timestamp, which reads exactly like a parser reading
a line twice.

The page says otherwise:

    y=573.75  - Mutual fund units (72,878) (73,048)     parenthesised
    y=640.02  - Mutual fund units 72,682 73,987        plain

Two notes print the same caption and both figures are correct. So deduplicating on caption,
period and source would have DELETED a correct figure out of an audited filing -- the one
error this project treats as worse than publishing a wrong one. The reader therefore records
the line's coordinate, and that is what makes a row's identity recoverable.

These tests pin all three properties: re-ingestion is a no-op, a changed reading replaces
rather than joins, and two printed lines carrying one caption both survive.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from backend.data.store import RawDatapoint, query_datapoints, save_datapoints

INFY_PDF = Path("backend/data/filings/infosys-fy26-q4-outcome.pdf")
needs_pdf = pytest.mark.skipif(
    not INFY_PDF.exists(), reason="the Infosys filing is not in this checkout"
)


def _dp(**kw) -> RawDatapoint:
    base = dict(
        company_id="probe_us",
        metric_raw="Total assets",
        period_label="FY26",
        period_end_date=date(2026, 3, 31),
        value=1000.0,
        currency="INR",
        units="crores",
        source="nse_filing",
        source_location="probe.pdf p.10 y=100.0 Total assets",
        status="reported",
        update_date=datetime(2026, 10, 4, 9, 0, 0),
    )
    base.update(kw)
    return RawDatapoint(**base)  # type: ignore[arg-type]


def _count(db: Path) -> int:
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute("SELECT COUNT(*) FROM raw_datapoints").fetchone()[0]
    finally:
        conn.close()


def test_re_ingesting_the_same_rows_changes_nothing(tmp_path):
    db = tmp_path / "probe.db"
    rows = [_dp(metric_raw=f"line {i}", value=float(i)) for i in range(5)]

    save_datapoints(db, rows, clear_existing=False)
    first = _count(db)
    # Fresh objects with fresh uuid4s, exactly as a second run produces.
    save_datapoints(db, [_dp(metric_raw=f"line {i}", value=float(i)) for i in range(5)],
                    clear_existing=False)

    assert _count(db) == first, (
        f"re-ingesting identical rows grew the store from {first} to {_count(db)}. "
        f"filing_derived is a ratio of row counts, so this is a model's publication verdict "
        f"changing because a script ran twice."
    )


def test_a_changed_reading_replaces_its_row_rather_than_joining_it(tmp_path):
    """A parser fix that changes a figure must update the row, not leave a rival beside it."""
    db = tmp_path / "probe.db"
    save_datapoints(db, [_dp(value=1000.0)], clear_existing=False)
    save_datapoints(db, [_dp(value=1234.0)], clear_existing=False)

    rows = query_datapoints(db, "probe_us")
    assert len(rows) == 1, (
        f"a re-read produced a second row for the same line rather than replacing it: "
        f"{[(r.metric_raw, r.value) for r in rows]}"
    )
    assert rows[0].value == pytest.approx(1234.0), (
        "the store kept the superseded reading rather than the current one"
    )


def test_rows_from_different_periods_and_lines_are_all_kept(tmp_path):
    """The identity is the LINE, so the same caption twice on a page is two rows."""
    db = tmp_path / "probe.db"
    save_datapoints(
        db,
        [
            _dp(source_location="probe.pdf p.104 y=573.8 - Mutual fund units", value=-73048.0),
            _dp(source_location="probe.pdf p.104 y=640.0 - Mutual fund units", value=73987.0),
            _dp(source_location="probe.pdf p.104 y=573.8 - Mutual fund units",
                period_label="FY25", value=-72878.0),
            _dp(source_location="probe.pdf p.104 y=640.0 - Mutual fund units",
                period_label="FY25", value=72682.0),
        ],
        clear_existing=False,
    )
    rows = query_datapoints(db, "probe_us")
    assert len(rows) == 4, (
        "four correct readings of two printed lines collapsed into fewer. Each is a figure "
        "an audited filing prints, and losing one is worse than publishing a wrong one."
    )
    assert sorted(r.value for r in rows) == pytest.approx(
        sorted([-73048.0, -72878.0, 72682.0, 73987.0])
    )


def test_clear_existing_still_replaces_the_whole_company(tmp_path):
    """The other mode is unchanged: a forced re-ingest clears the company first."""
    db = tmp_path / "probe.db"
    save_datapoints(db, [_dp(metric_raw="old line")], clear_existing=True)
    save_datapoints(db, [_dp(metric_raw="new line")], clear_existing=True)

    rows = query_datapoints(db, "probe_us")
    assert [r.metric_raw for r in rows] == ["new line"]


def test_nothing_outside_the_written_rows_is_touched(tmp_path):
    """Scoped replacement, not a company-wide delete hidden behind a filter."""
    db = tmp_path / "probe.db"
    save_datapoints(db, [_dp(company_id="other_us", metric_raw="their line")],
                    clear_existing=False)
    save_datapoints(db, [_dp(company_id="probe_us", metric_raw="our line")],
                    clear_existing=False)
    save_datapoints(db, [_dp(company_id="probe_us", metric_raw="our line", value=2.0)],
                    clear_existing=False)

    assert [r.metric_raw for r in query_datapoints(db, "other_us")] == ["their line"]


@needs_pdf
def test_the_reader_records_the_line_so_two_printings_are_distinguishable():
    """The property the identity depends on, measured on the real filing."""
    from backend.data.parsers.pdf_tables import parse_predicted_statement_page

    dps = parse_predicted_statement_page(
        str(INFY_PDF), 103, "CASH FLOW", "nse_filing", annual_only=False,
        company_id="infy_infy",
    )
    mutual = [d for d in dps if "Mutual fund" in d.metric_raw]
    assert len(mutual) == 4, (
        f"expected the two printed '- Mutual fund units' lines across two periods, got "
        f"{len(mutual)}: {[(d.value, d.source_location) for d in mutual]}"
    )

    locations = {d.source_location for d in mutual}
    assert len(locations) == 2, (
        "the two printed lines still share one source_location, so they cannot be told "
        f"apart and deduplicating would delete a correct figure: {sorted(locations)}"
    )
    # And the two lines really do disagree in sign, which is the whole reason the identity
    # needs the coordinate: the parenthesised note is negative and the plain one positive.
    negatives = [d for d in mutual if d.value < 0]
    positives = [d for d in mutual if d.value > 0]
    assert negatives and positives, (
        "the parenthesised note and the plain one are no longer both being read, so one of "
        "two correct printed figures has been lost"
    )
    assert len({d.source_location for d in negatives} & {d.source_location for d in positives}) == 0, (
        "the negative and the positive readings are on the same line, which would mean the "
        "two printed lines are not being kept apart"
    )