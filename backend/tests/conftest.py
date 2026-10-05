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


def fetch_sec_json(url: str, *, what: str, timeout: int = 180) -> dict:
    """Download and parse a JSON document from EDGAR, or skip naming why.

    Two tests check a claim against a filer that is LIVE rather than against a
    fixture, which is the only way to know the claim still holds. Calling
    ``data.sec.gov`` directly made that claim untestable in practice: the request
    raised, and an HTTP timeout, a 429, or a reset connection surfaced as a
    failed test. The failure said nothing about the tag or the CIK it was checking
    and everything about the network at that moment.

    Observed, not hypothetical. ``test_a_company_tagging_only_the_including_variant_is_readable``
    passed alone, passed as its own file, and failed inside a 324-test run, then
    passed on an identical rerun of the same 324 tests. An intermittent gate
    cannot be trusted to catch anything, so a red build from it teaches the team
    to ignore red builds.

    The marker was registered in ``pyproject.toml`` with the description "fails
    when the network is unavailable", but nothing honoured it: CI runs
    ``pytest backend/tests -q`` with no ``-m`` filter, so the marker's promise was
    never kept. Two ways to keep it, and this takes the first.

      1. Skip with the actual exception named. The assertion still runs whenever
         EDGAR answers, so the check keeps its full value in CI, and an outage is
         reported as an outage instead of as a defect in the engine.
      2. Deselect network tests in CI. Simpler, and it gives up the check
         entirely -- which is how a tag silently stops matching a filer that
         changed its taxonomy, or a CIK registry entry drifts onto another filer
         without anyone noticing until a published figure names the wrong company.

    A malformed response is handled the same way as a failed request, because a
    truncated body is equally uninformative. The body is only trusted once it
    parses.

    ``what`` names the thing being checked, so a skip message says which claim went
    unverified rather than only that a URL failed.
    """
    import gzip
    import json
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Valence valuation research team@valence.com",
            "Accept-Encoding": "gzip",
        },
    )
    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read()
    except urllib.error.HTTPError as exc:
        # 403 and 429 are EDGAR refusing a shared client identity rather than
        # anything about this filer, which is exactly the case that must never be
        # reported as a product failure.
        pytest.skip(
            f"EDGAR answered {exc.code} {exc.reason} while checking {what}. That is "
            "the network or the rate limit, not the assertion under test."
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        pytest.skip(
            f"could not reach data.sec.gov while checking {what}: "
            f"{type(exc).__name__}: {exc}. That is the network, not the assertion."
        )

    try:
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        parsed = json.loads(raw)
    except (OSError, ValueError) as exc:
        pytest.skip(
            f"EDGAR's response for {what} did not parse: {type(exc).__name__}: {exc}. "
            "Truncated or malformed, and equally uninformative about the claim."
        )
    if not isinstance(parsed, dict):
        pytest.skip(
            f"EDGAR returned {type(parsed).__name__} rather than an object for {what}, "
            "so the shape this test expects is not what arrived."
        )
    return parsed


def fetch_company_facts(cik: int) -> dict:
    """A filer's XBRL company facts, or skip. See :func:`fetch_sec_json`."""
    return fetch_sec_json(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
        what=f"CIK {cik:010d} company facts",
    )
