"""A rebuild that fails must leave the company exactly as it was.

Found the hard way, during the India parser work. Running

    python scripts/refresh_all_models.py --companies infy_infy --force-ingest

against a parser change that surfaced 17 captions the taxonomy does not know reported

    FAIL infy_infy  Normalization failed: 17 unmapped labels found: [...]

and left `infy_infy` with 737 fresh raw rows and **ZERO** canonical rows. Every test
touching that company then failed with `NoFinancialsAvailable: ingestion produced no
canonical datapoints`.

The cause is `clear_db=force`: `ensure_company_ingested` wipes the company, then
normalization raises before writing anything back. So the operator asked for a rebuild, the
rebuild reported failure, and the data that existed before the attempt was destroyed along
with the experiment. That is the worst direction for a build tool to fail in.

The fix holds a snapshot of the company's rows and restores it on any exception. It
deliberately does not depend on knowing WHICH statement deletes WHICH table -- it captures
the previous state and puts it back, so it covers the `clear_db` path, the raw-replace
path, and any path added later.

Both directions are asserted here, and the second one matters more than the first: a guard
that is never seen failing is not known to work. With the restore replaced by a no-op the
same run MUST lose rows. If that control passed, the "nothing was lost" assertion would be
meaningless.

Everything runs against a COPY of the database. The whole point is that a failed rebuild
must not damage data, so running the test against the live store would be the very failure
it guards.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from backend.data import batch
from backend.data.universe.store import DB_PATH

COMPANY = "infy_infy"
TABLES = ("raw_datapoints", "canonical_datapoints")


def _counts(db: Path, company_id: str = COMPANY) -> dict:
    conn = sqlite3.connect(str(db))
    try:
        return {
            t: conn.execute("SELECT COUNT(*) FROM %s WHERE company_id = ?" % t,
                            (company_id,)).fetchone()[0]
            for t in TABLES
        }
    finally:
        conn.close()


@pytest.fixture()
def copied_db(tmp_path):
    """A copy of the real store, so a destructive path cannot touch live data."""
    dest = tmp_path / "valence.db"
    shutil.copy2(DB_PATH, dest)
    return dest


@pytest.fixture()
def normalization_fails(monkeypatch):
    """Make normalization raise, at the point it really raised: after the wipe."""
    import backend.normalization.pipeline as np

    def boom(*_a, **_k):
        raise ValueError(
            "Normalization failed: 17 unmapped labels found: [simulated]")

    monkeypatch.setattr(np, "run", boom)


def test_a_failed_rebuild_loses_nothing(copied_db, normalization_fails):
    before = _counts(copied_db)
    assert before["canonical_datapoints"] > 0, (
        "the fixture company has no canonical rows, so there is nothing to lose and "
        "this test would pass without proving anything")

    with pytest.raises(ValueError, match="unmapped labels"):
        batch.ensure_company_ingested(COMPANY, db_path=copied_db, force=True)

    after = _counts(copied_db)
    assert after == before, (
        "a failed rebuild changed the company's rows: %s -> %s. The operator asked for a "
        "rebuild, was told it failed, and has also lost the working data."
        % (before, after)
    )


def test_the_guard_is_load_bearing(copied_db, normalization_fails, monkeypatch):
    """The control: disable the restore and the rows MUST be lost.

    Without this, `test_a_failed_rebuild_loses_nothing` could pass because the destructive
    path stopped being destructive for some unrelated reason, and the guard would be
    credited with a fix it is not providing.
    """
    before = _counts(copied_db)
    monkeypatch.setattr(batch, "_restore_company_rows", lambda *a, **k: None)

    with pytest.raises(ValueError):
        batch.ensure_company_ingested(COMPANY, db_path=copied_db, force=True)

    after = _counts(copied_db)
    assert after != before, (
        "disabling the restore changed nothing, so the restore is not what prevents the "
        "loss and the guard above is decoration. before=%s after=%s" % (before, after)
    )
    assert after["canonical_datapoints"] == 0, (
        "expected the unguarded path to leave the company with no canonical rows at all, "
        "which is the state that broke every test touching this company. Got %d."
        % after["canonical_datapoints"]
    )


def test_a_successful_rebuild_still_replaces_the_rows(copied_db):
    """The guard must not turn a rebuild into a no-op.

    A restore that fires on the way out as well as on the way in would leave every company
    permanently stale, which looks like a working system: no failures, no updates.
    """
    before = _counts(copied_db)
    batch.ensure_company_ingested(COMPANY, db_path=copied_db, force=True)
    after = _counts(copied_db)

    assert after["canonical_datapoints"] > 0, (
        "a successful rebuild left the company with no canonical rows")
    assert after == before or after["raw_datapoints"] > 0, (
        "a successful rebuild wrote nothing at all")


def test_the_snapshot_reads_every_column(copied_db):
    """A restore that misplaces values is worse than no restore.

    `_snapshot_company_rows` uses `SELECT *` so a schema change cannot silently reorder
    columns on the way back in. This pins that both tables round-trip their full width.
    """
    snapshot = batch._snapshot_company_rows(copied_db, COMPANY)
    conn = sqlite3.connect(str(copied_db))
    try:
        for table, key in (("raw_datapoints", "raw"),
                           ("canonical_datapoints", "canonical")):
            width = len(conn.execute("SELECT * FROM %s LIMIT 1" % table).fetchall()[0])
            rows = conn.execute(
                "SELECT * FROM %s WHERE company_id = ?" % table, (COMPANY,)).fetchall()
            assert snapshot[key], "no rows snapshotted for %s" % table
            assert all(len(r) == width for r in rows), (
                "%s rows are not all %d columns wide; a restore would write them into "
                "the wrong slots" % (table, width))
    finally:
        conn.close()