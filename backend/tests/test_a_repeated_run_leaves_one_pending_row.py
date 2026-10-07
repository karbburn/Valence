"""One pending row per label per company, however many times routing runs.

route_to_review_queue minted a fresh uuid4 row on every call, and the only
deduplication lived inside a single map_raw_datapoints call, so every ingest
and every test run appended another full set of duplicates: the queue grew to
five figures with the worst labels copied nearly two hundred times. A reviewer
opening the pending list met the old copies before the first genuinely new
decision.

Routing now updates the existing pending row for the same (company, label)
instead of inserting another one, and only a row that is still pending counts:
a resolved decision must not swallow the next time the label comes back.
"""
from __future__ import annotations

import sqlite3

from backend.data.universe.models import MappingConfidenceResult
from backend.normalization.taxonomy.mapping_engine import route_to_review_queue


def _suggested() -> MappingConfidenceResult:
    return MappingConfidenceResult(
        metric_raw="Right-of-use assets",
        canonical_key=None,
        statement=None,
        confidence_score=0.2,
        level="low",
        reason="Unrecognized label, requires human review",
    )


def _rows(db_path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT company_id, metric_raw, status FROM taxonomy_review_queue "
            "ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()


def test_routing_the_same_label_twice_leaves_one_pending_row(tmp_path):
    db = tmp_path / "queue.db"
    route_to_review_queue("fixture_co", "Right-of-use assets", _suggested(), db_path=db)
    route_to_review_queue("fixture_co", "Right-of-use assets", _suggested(), db_path=db)

    rows = _rows(db)
    assert rows == [("fixture_co", "Right-of-use assets", "pending")], (
        "routing twice produced %r; the queue grows by one duplicate set per run"
        % (rows,)
    )


def test_a_different_company_keeps_its_own_row(tmp_path):
    db = tmp_path / "queue.db"
    route_to_review_queue("fixture_co", "Right-of-use assets", _suggested(), db_path=db)
    route_to_review_queue("other_co", "Right-of-use assets", _suggested(), db_path=db)

    rows = _rows(db)
    assert len(rows) == 2, "the dedupe collapsed two different companies: %r" % (rows,)


def test_a_resolved_row_does_not_swallow_the_next_pending_one(tmp_path):
    db = tmp_path / "queue.db"
    route_to_review_queue("fixture_co", "Right-of-use assets", _suggested(), db_path=db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("UPDATE taxonomy_review_queue SET status = 'resolved'")
        conn.commit()
    finally:
        conn.close()

    route_to_review_queue("fixture_co", "Right-of-use assets", _suggested(), db_path=db)

    rows = _rows(db)
    assert len(rows) == 2 and rows[-1][2] == "pending", (
        "a label resolved once can never be queued again: %r" % (rows,)
    )
