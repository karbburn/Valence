"""A company holding market-feed rows is not a company that has been ingested.

`ensure_company_ingested` skipped whenever the store held any canonical rows for the company. A
company can hold rows from `screener` and `yfinance_live` and have no filing rows at all, and for
such a company that shortcut returned before the India pipeline -- the only code that reads the
audited statements -- so the filings were never parsed.

Measured on a copy of the store, same committed filings, one flag apart:

    company              force    nse_filing rows
    tcs_tcs              False            0
    tcs_tcs              True           185
    hcltech_hcltech      False            0
    hcltech_hcltech      True            46
    infy_infy            False          260
    infy_infy            True           426

Three companies whose audited statements are committed under `backend/data/filings/`, producing
zero filing rows and a complete model built entirely from a market feed. India measured 0 of 20
obtaining any filing history, and the parser fixes that preceded this one changed nothing on that
path, because the parser was never called.

That is the shape this project treats as worst: not a crash but a plausible model. It had a
balance sheet, a share count and a bridge, all of it real, none of it filed.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from backend.data import batch
from backend.data.universe.store import DB_PATH

# TCS and HCLTech both have audited statements committed under backend/data/filings/nse/, so the
# locator finds them without touching the network and the test is offline.
HAS_COMMITTED_FILING = ["tcs_tcs", "hcltech_hcltech"]


def filing_rows(db: Path, company_id: str) -> int:
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM raw_datapoints "
            "WHERE company_id = ? AND source = 'nse_filing'",
            (company_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def canonical_rows(db: Path, company_id: str) -> int:
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM canonical_datapoints WHERE company_id = ?", (company_id,)
        ).fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def store_with_feed_rows_only(tmp_path):
    """A store where the companies hold market-feed rows and NO filing rows.

    This is the exact state that made the old shortcut skip. Built by copying the live store and
    deleting the filing rows, rather than by inventing rows, so the state is one the product has
    genuinely been in.
    """
    if not DB_PATH.exists():
        pytest.skip("no ingested store to copy; run the engine once locally")
    db = tmp_path / "feed_only.sqlite"
    shutil.copy(DB_PATH, db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("DELETE FROM raw_datapoints WHERE source = 'nse_filing'")
        conn.commit()
    finally:
        conn.close()
    return db


@pytest.mark.parametrize("company_id", HAS_COMMITTED_FILING)
def test_a_feed_only_company_is_not_treated_as_ingested(store_with_feed_rows_only, company_id):
    """The precondition, asserted so the test cannot pass for the wrong reason."""
    assert canonical_rows(store_with_feed_rows_only, company_id) > 0, (
        f"{company_id} holds no canonical rows in this fixture, so 'has rows but no filing rows' "
        "is not the state under test and a pass here would mean nothing"
    )
    assert filing_rows(store_with_feed_rows_only, company_id) == 0, (
        f"{company_id} already has filing rows in this fixture, so the shortcut's old behaviour "
        "would not have fired and this test proves nothing"
    )


@pytest.mark.parametrize("company_id", HAS_COMMITTED_FILING)
def test_a_feed_only_company_gets_its_filing_without_being_forced(
    store_with_feed_rows_only, company_id
):
    """The defect itself. No `force`, which is what every product call site passes."""
    batch.ensure_company_ingested(company_id, db_path=store_with_feed_rows_only)

    rows = filing_rows(store_with_feed_rows_only, company_id)
    assert rows > 0, (
        f"{company_id} has an audited statement committed under backend/data/filings/ and holds "
        f"market-feed rows, yet still has {rows} filing rows after an ordinary ingest. The "
        "skip-on-present shortcut is treating 'has rows' as 'is fully ingested' again."
    )


@pytest.mark.parametrize("company_id", HAS_COMMITTED_FILING)
def test_the_shortcut_still_fires_once_the_filing_is_stored(
    store_with_feed_rows_only, company_id, monkeypatch
):
    """Idempotency. The fix must not turn every read into a re-ingest.

    Asserted by counting how many times the India pipeline RUNS, not by comparing row counts.

    The row-count version of this test passed against a build where the shortcut was removed
    entirely: re-parsing the same committed PDFs writes the same rows, so the count is unchanged
    and the test reports green while the defect is at its worst. Found by the mutation harness,
    which is the only reason it was found. A behavioural assertion beats a state comparison when
    the state is reachable two ways -- here, "parsed once" and "parsed every call" both end with
    the rows stored.
    """
    calls: list[str] = []
    import backend.data.pipeline as india_pipeline

    real_run = india_pipeline.run

    def _counted(*args, **kwargs):
        calls.append(kwargs.get("company_id") or (args[0] if args else "?"))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(india_pipeline, "run", _counted)

    batch.ensure_company_ingested(company_id, db_path=store_with_feed_rows_only)
    first_pass = len(calls)
    assert filing_rows(store_with_feed_rows_only, company_id) > 0, (
        "precondition: the filing must be stored for this to test anything"
    )

    batch.ensure_company_ingested(company_id, db_path=store_with_feed_rows_only)
    second_pass = len(calls)

    assert first_pass == 1, (
        f"the filing was not ingested on the first call ({first_pass} pipeline runs), so the "
        "shortcut skipped a company that needed it"
    )
    assert second_pass == first_pass, (
        f"the India pipeline ran {second_pass - first_pass} extra times for {company_id} on an "
        "ordinary second call. The shortcut exists so a stored filing is parsed once; without it "
        "every API read re-parses the PDFs."
    )


def test_an_unreadable_store_is_not_read_as_proof_the_filing_is_stored(tmp_path):
    """A store that cannot be read is not evidence that there is nothing to do.

    Reading it the other way would reintroduce the silent skip through a different door: the count
    would come back non-zero, the shortcut would fire, and the filing would go unparsed because the
    database happened to be locked rather than because anything was already ingested.

    Returning zero on failure is the safe direction precisely because the consequence of being
    wrong is a re-parse rather than a gap.
    """
    missing = tmp_path / "no_such_directory" / "store.sqlite"

    assert batch._stored_filing_row_count("tcs_tcs", missing) == 0, (
        "an unreadable store must count as zero stored rows, so the caller goes on to try"
    )
    assert batch._an_available_filing_is_unstored("tcs_tcs", missing) is True, (
        "with the store unreadable and a filing on disk, the company must be treated as not yet "
        "ingested"
    )


def test_a_company_with_no_filing_is_still_left_alone():
    """The narrowness matters. Most companies have no India filing and must be untouched.

    Without this, the fix would re-ingest every company on the platform on every call, which is a
    far worse defect than the one it removes.
    """
    assert batch._an_available_filing_is_unstored("definitely_not_a_company_zz", DB_PATH) is False, (
        "a company with no located filing must never be treated as having an unstored one, or "
        "every API read becomes an ingest"
    )


def test_a_stored_filing_is_not_re_ingested_even_when_the_locator_still_finds_it():
    """The available-but-already-stored case, which is the ordinary steady state.

    A company whose filing rows are stored and whose PDFs are still cached is the normal condition
    for every India company after its first ingest. Reading that as "unstored" would re-parse on
    every request forever.
    """
    if not DB_PATH.exists():
        pytest.skip("no ingested store to read")
    for company_id in HAS_COMMITTED_FILING:
        if filing_rows(DB_PATH, company_id) == 0:
            pytest.skip(f"{company_id} has no filing rows in the live store yet")
        assert batch._an_available_filing_is_unstored(company_id, DB_PATH) is False, (
            f"{company_id} already has its filing rows stored, so it must not be treated as "
            "needing another ingest"
        )