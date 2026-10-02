"""A tracked snapshot must be served WITHOUT re-ingesting from the filing.

The cache was defeated by the thing that validated it.

`_cache_matches_database` answered "is this snapshot still current?" by building
a fresh historical model, and `_get_hist_model` calls `ensure_company_ingested`.
`_expected_forecast_contract` called it a second time. So the freshness check
performed a full live SEC ingestion for every shipped company whose model was not
already in the in-memory LRU.

`backend/data/valence.db` is gitignored. Twenty-three snapshots are tracked; no
database is. On a cold deploy -- which is every deploy -- all 23 miss the LRU, all
23 re-ingest from EDGAR on first request, and at `VALENCE_INGEST_CONCURRENCY=2`
the site answered

    HTTP 503  "The engine is busy compiling other models. Retry shortly."

to 11 of the 23 companies it already had on disk. The `site` gate reported it as
    FAIL  tatasteel_tatasteel: could not read the served model

which named neither the cause nor the companies affected.

This is worse than a wrong number, because it is no number. And it contradicts the
product's own headline claim that any listed ticker builds on first open: it failed
on the ones already built.

The property guarded here is the one that makes the cache a cache: **asking
whether we already hold something must never be the act that fetches it.**
"""

from __future__ import annotations

import inspect
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.api import routes  # noqa: E402

ROUTES = (REPO / "backend" / "api" / "routes.py").read_text(encoding="utf-8")
CODE = re.sub(r"#.*$", "", ROUTES, flags=re.M)

GITIGNORE = (REPO / ".gitignore").read_text(encoding="utf-8")


class TestTheFreshnessCheckDoesNotIngest:
    """The check must be answerable without fetching anything.

    A test that only asserts the final status code would pass for the wrong
    reason -- if the database happens to be populated locally, the old path
    returns the same answer. So the property is asserted structurally: the
    existence probe must be a pure read, and it must be consulted before the
    comparison that ingests.
    """

    def test_a_pure_existence_probe_exists(self):
        assert hasattr(routes, "_database_has_company"), (
            "there is no non-ingesting way to ask whether a company's statements "
            "are already stored, so the freshness check is still built out of the "
            "ingestion path"
        )

    def test_the_probe_does_not_call_anything_that_ingests(self):
        # Comments stripped FIRST. The docstring explains this defect at length
        # and names `ensure_company_ingested` and `_get_hist_model` while doing
        # so, so a raw search of the source is satisfied by the explanation of the
        # bug rather than by the absence of the bug -- which is how both of these
        # assertions failed on the fixed code.
        body = re.sub(r"#.*$", "", inspect.getsource(routes._database_has_company), flags=re.M)
        # The DOCSTRING is the other half of the trap. `inspect.getsource` includes
        # it, and this function's docstring names every one of these while explaining
        # why it must not call them. Both prose sources are removed before the search.
        body = re.sub(r'""".*?"""', "", body, flags=re.S)
        for forbidden in (
            "ensure_company_ingested",
            "_get_hist_model",
            "run_historical",
            "fetch_and_parse",
            "get_company_market_data",
        ):
            assert forbidden not in body, (
                "_database_has_company calls %s, so asking whether we hold a "
                "company's data is still the act of fetching it" % forbidden
            )

    def test_the_probe_is_asked_before_the_ingesting_comparison(self):
        """Order is the whole fix.

        With the probe after the comparison it would never run on the path that
        matters, and the outage would persist with the probe sitting right there
        looking like a fix.
        """
        body = inspect.getsource(routes._cache_matches_database)
        i_probe = body.find("_database_has_company(")
        i_ingest = body.find("_get_hist_model(")
        i_contract = body.find("_expected_forecast_contract(")
        assert i_probe != -1, (
            "_cache_matches_database no longer consults the existence probe, so it "
            "compares against a fresh assembly unconditionally"
        )
        assert i_ingest != -1, "the comparison appears to have been removed entirely"
        assert i_probe < i_ingest, (
            "the probe is asked AFTER the ingestion comparison, so it cannot "
            "prevent the ingestion it exists to prevent"
        )
        assert i_probe < i_contract, (
            "the probe is asked AFTER the forecast-contract comparison, which "
            "ingests a second time"
        )

    def test_an_absent_database_is_treated_as_current_not_stale(self):
        """No database means no correction happened, so nothing to detect.

        Returning False here would restore the outage in a subtler form: the
        snapshot would be discarded as stale and rebuilt from filings that are not
        present, which is the failure being fixed.
        """
        body = re.sub(r"#.*$", "", inspect.getsource(routes._cache_matches_database), flags=re.M)
        # The `return True` may sit behind a logger call, so adjacency to the `if`
        # is not the property. What matters is that the guard block reaches a
        # `return True` before the function reaches either ingestion call -- and
        # that `return False` is not what the absent-database branch returns.
        i_guard = body.find("if not _database_has_company(company_id):")
        assert i_guard != -1, "the absent-database guard is gone"
        i_true = body.find("return True", i_guard)
        i_ingest = body.find("_get_hist_model(", i_guard)
        assert i_true != -1, (
            "an absent database no longer short-circuits to True, so a shipped "
            "snapshot is declared stale on a cold deploy and re-ingested"
        )
        assert i_true < i_ingest, (
            "the absent-database branch reaches an ingestion call before it returns, "
            "so the short-circuit no longer prevents anything"
        )
        # And the guard must not return False, which is the outage in a subtler form.
        block = body[i_guard:i_ingest if i_ingest != -1 else i_true + 40]
        assert "return False" not in block, (
            "an absent database now returns False, so the snapshot is discarded as "
            "stale and rebuilt from filings that are not present"
        )


class TestThePremiseIsNotAccidental:
    """These hold only because the database is untracked. Assert them anyway.

    The outage is a property of the deployment, not of the function, and a future
    commit that tracks `valence.db` would silently make this test suite
    misleading rather than fixing it.
    """

    def test_the_database_is_not_tracked_by_git(self):
        import subprocess

        out = subprocess.run(
            ["git", "ls-files", "backend/data/valence.db"],
            cwd=str(REPO), capture_output=True, text=True, timeout=120,
        )
        assert out.stdout.strip() == "", (
            "backend/data/valence.db is now TRACKED, so a deploy ships it and the "
            "cold-deploy path this file guards stops being reachable. Re-check "
            "whether the fix is still load-bearing before removing this test."
        )

    def test_snapshots_are_tracked(self):
        import subprocess

        out = subprocess.run(
            ["git", "ls-files", "backend/data/cache"],
            cwd=str(REPO), capture_output=True, text=True, timeout=120,
        )
        count = len([ln for ln in out.stdout.splitlines() if ln.endswith(".json")])
        assert count >= 23, (
            "expected at least the 23 shipped snapshots to be tracked, found %d. "
            "If snapshots stopped shipping, the launch surface has changed and "
            "the outage above may no longer be reachable." % count
        )

    def test_the_database_is_listed_in_gitignore(self):
        assert re.search(r"^\*?\.?\*?valence\.db|valence\.db", GITIGNORE, re.M), (
            "valence.db is no longer gitignored, which means the deployment shape "
            "this whole file depends on has changed"
        )


class TestTheGateNamesTheCause:
    """A gate that cannot say why is the failure mode this project keeps hunting.

    The `site` gate reported `could not read the served model` for a 503. It is
    the same word for "the server said it was busy", "the request timed out" and
    "the response was not JSON" -- three conditions with three different fixes,
    collapsed into one line that reads like the model was broken.
    """

    def test_the_site_gate_does_not_swallow_the_status_code(self):
        gate_src = (REPO / "scripts" / "audit_loop.py").read_text(encoding="utf-8")
        m = re.search(
            r"except (\w+) as \w+:\s*\n\s*g\.fail\(f\"\{cid\}: could not read the served model\"",
            gate_src,
        )
        assert m is None, (
            "the site gate still catches every exception as one 'could not read the "
            "served model' line. An HTTPError carries a status code and should be "
            "reported as such: a 503 is the server declining under load and is "
            "fixed in the throttle, a timeout is fixed in the timeout, and a parse "
            "failure is a third thing entirely."
        )