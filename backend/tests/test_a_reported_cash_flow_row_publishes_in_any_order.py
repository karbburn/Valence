"""A filed cash-flow figure publishes however the rows arrive.

The statement folded every canonical row for a (key, period) into one map in
whatever order the store returned them, last row wins, and the query behind the
store has no ORDER BY. The filing's section totals and the aggregator's
estimates for the same period both live in that store, so which figure
published was decided by insertion order alone: an ingest that re-saved the
screener's rows after the filing's would silently put the estimate back on the
statement, which is the very defect the filing mappings were made to end.

A row read from a filing now wins over a row that was not, in either order.
Rows of equal rank keep last-row-wins, which is the documented tiebreak for a
period printed in two documents (their figures agree today, so either row
publishes the same number).
"""
from __future__ import annotations

from datetime import date

from backend.models.statements.cash_flow import assemble_cash_flow
from backend.normalization.taxonomy.models import CanonicalDatapoint

PERIOD = "FY26"
KEY = "canonical.cf.investing_activities"

# The filing prints 108 for FY26 investing; the aggregator estimates 3,546.
FILED = 108.0
ESTIMATE = 3546.0


def _dp(value: float, status: str, source: str) -> CanonicalDatapoint:
    return CanonicalDatapoint(
        company_id="fixture_co",
        canonical_key=KEY,
        metric_raw="Net cash generated from investing activities",
        period_label=PERIOD,
        period_end_date=date(2026, 3, 31),
        value=value,
        currency="INR",
        units="crores",
        status=status,
        source_datapoint_ids=[source],
    )


def _publishes(rows: list[CanonicalDatapoint]) -> float | None:
    return assemble_cash_flow(rows).get_value(KEY, PERIOD)


def test_the_filed_figure_publishes_when_it_arrives_first():
    value = _publishes([_dp(FILED, "reported", "filing"), _dp(ESTIMATE, "estimated", "screener")])
    assert value == FILED, (
        "the filing's row arrived first and the screener's estimate replaced it: "
        "the statement publishes %.0f where the filing says %.0f" % (value, FILED)
    )


def test_the_filed_figure_publishes_when_it_arrives_last():
    value = _publishes([_dp(ESTIMATE, "estimated", "screener"), _dp(FILED, "reported", "filing")])
    assert value == FILED, (
        "the filing's row arrived second and still lost: the statement publishes "
        "%.0f where the filing says %.0f" % (value, FILED)
    )


def test_rows_of_equal_rank_keep_the_last_one():
    """The documented tiebreak: equal rank, last row wins, whatever the order.

    Two documents printing the same period both land in the store, and their
    figures agree today, so this is about pinning the rule rather than which
    number a reader sees.
    """
    first = _dp(36786.0, "reported", "fy25-document-1")
    second = _dp(36787.0, "reported", "fy25-document-2")
    assert _publishes([first, second]) == 36787.0, (
        "two equally ranked rows did not resolve to the last one"
    )

    early = _dp(3546.0, "estimated", "screener-a")
    late = _dp(3547.0, "estimated", "screener-b")
    assert _publishes([early, late]) == 3547.0, (
        "two equally ranked estimates did not resolve to the last one"
    )
