"""Shared test setup.

The store question
------------------

A few tests build a model from the ingested datastore rather than from a
fixture: the driver-panel and forecast-balance-sheet tests take a real company,
run it through historical, forecast and valuation, and assert on the result.

Those are the tests that caught the two worst defects in this engine's history,
so they are worth keeping. They are also the only tests that need a populated
`valence.db`, which is gitignored and therefore absent from a fresh clone, a CI
runner, and any contributor who has not run the engine locally.

Left alone they failed on a clean checkout, with a wall of
`NoFinancialsAvailable` that looked like a regression in the ingestion path. It
was not: there was simply nothing to ingest from.

They are now skipped, explicitly and with a reason naming what is missing, when
the store holds no company. A skip that says why is information. A test that
fails for a reason unrelated to the change under test is noise, and noise is what
teaches a team to ignore a red build.

The alternative considered and rejected: committing the database. It is hundreds
of megabytes of third-party filings, it goes stale the moment a filing lands, and
it would make every pull request a merge conflict over data nobody reviews.
"""

from __future__ import annotations

import pytest

from backend.data.universe.store import DB_PATH


def _store_has_company() -> bool:
    if not DB_PATH.exists():
        return False
    try:
        import sqlite3

        conn = sqlite3.connect(str(DB_PATH))
        try:
            row = conn.execute("SELECT 1 FROM canonical_datapoints LIMIT 1").fetchone()
        finally:
            conn.close()
    except Exception:
        return False
    return row is not None


_HAS_STORE = _store_has_company()

requires_store = pytest.mark.skipif(
    not _HAS_STORE,
    reason=(
        "needs an ingested datastore, which is gitignored and absent here. "
        "Run the engine once locally, or `python scripts/precompute.py`, to "
        "populate it. See the note in backend/tests/conftest.py."
    ),
)


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Clear the rate limiter's per-client state between tests.

    The limiter is process-global by design, which is what makes it cheap, and
    that is a problem for a test suite: the API tests drive the real app through
    a test client, they all share one client identity, and the budget is
    aggregate across reads. Left alone, the earlier tests in the run spend the
    budget and every later test receives 429 for a reason that has nothing to do
    with what it is checking. Those failures passed in isolation and failed in
    the suite, which is the worst kind.

    Only the tests that exercise the limiter itself assert on its behaviour, and
    they set the budget they need themselves.
    """
    from backend.api import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def unlimited_budget(monkeypatch):
    """Remove the rate limit for a test that is not about the rate limit.

    A handful of tests sweep an entire collection in one test: every manifest
    slug round-trips to its own company, and there are over a hundred of them.
    That is more requests than a person makes in a session by design, so the
    limiter correctly refuses partway through and the test fails for a reason
    that has nothing to do with the round-trip it is checking.

    Raising the budget rather than disabling the limiter keeps the code path
    under test. Disabling it would also let a real bug in the wiring pass, since
    nothing would be enforcing anything.
    """
    from backend.api import ratelimit

    monkeypatch.setattr(ratelimit, "READ_BUDGET", 1_000_000)
    monkeypatch.setattr(ratelimit, "WRITE_BUDGET", 1_000_000)
    ratelimit.reset()
    yield
    ratelimit.reset()
