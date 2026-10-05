"""Acquisition must be attempted, bounded, and quiet when it fails.

`nse_filings.py` is a 489-line acquirer that locates a balance sheet by content, and nothing in the
product called it. India published 0 of 2,593 for exactly that reason: the three companies with
filings had them because someone ran the CLI by hand three times.

This file covers the guard that makes calling it safe from the READ path, which is where it now runs.
Four properties:

  1. **Off unless a deployment asks.** One full suite run ingested a company with no cached filing
     and pulled a 193-page, 23MB results PDF from the exchange. A unit test that performs network I/O
     against a third party is the same defect as the network marker that promised otherwise and
     never did it.
  2. **Bounded.** A cached filing is never re-fetched; a failure is remembered briefly; a process has
     a ceiling. Without all three, browsing the site becomes a load on an exchange whose terms have
     not been checked.
  3. **Quiet.** Every failure writes nothing and raises nothing. The company falls back to its market
     feed with that labelled -- which is the fallback this project accepts, because it is visible. A
     fallback that silently produced a plausible *filed* answer would be worse than a failure.
  4. **Per-symbol.** One unavailable filer must not block acquisition for every other company.

Every test is offline. No test may reach the exchange, so the acquirer is always a double.
"""

from __future__ import annotations

import time

import pytest

from backend.data import pipeline
from backend.data.pipeline import (
    ACQUISITION_BUDGET,
    ACQUISITION_BUDGET_WINDOW_SECONDS,
    ACQUISITION_ENABLED_ENV,
    ACQUISITION_FAILED_TTL_SECONDS,
    acquire_filing,
    acquisition_state,
    reset_acquisition_state,
)


class _Result:
    """Stand-in for what `NSEFilings.acquire` returns."""

    def __init__(self, ok: bool, note: str = ""):
        self.ok = ok
        self.note = note
        self.pages = 12
        self.balance_sheet_pages = [5]
        self.url = "https://example.invalid/x.pdf"
        self.announced = None
        self.rejections = []


def _install(monkeypatch, result: _Result | Exception, counter: list | None = None):
    """Point the acquirer at a double.

    Patched where it is USED -- `nse_filings.NSEFilings`, not `pipeline.NSEFilings` -- because
    `acquire_filing` imports the name inside the function, so the module attribute is what the
    production path actually reads. The first version of this helper patched the wrong one and every
    "failure" test silently passed against a successful fetch.
    """
    from backend.data.ingestion import nse_filings

    if isinstance(result, Exception):
        class _Raising:
            def __init__(self, *a, **k):
                if counter is not None:
                    counter.append("constructed")

            def acquire(self, symbol, refresh=False):
                if counter is not None:
                    counter.append(symbol)
                raise result

        monkeypatch.setattr(nse_filings, "NSEFilings", _Raising)
        return

    class _Fixed:
        def __init__(self, *a, **k):
            if counter is not None:
                counter.append("constructed")

        def acquire(self, symbol, refresh=False):
            if counter is not None:
                counter.append(symbol)
            return result

    monkeypatch.setattr(nse_filings, "NSEFilings", _Fixed)


@pytest.fixture
def enabled(monkeypatch):
    """Acquisition switched ON. Every test below that exercises the guard opts in explicitly."""
    monkeypatch.setenv(ACQUISITION_ENABLED_ENV, "1")
    reset_acquisition_state()
    yield
    reset_acquisition_state()


@pytest.fixture
def disabled(monkeypatch):
    monkeypatch.setenv(ACQUISITION_ENABLED_ENV, "")
    reset_acquisition_state()
    yield
    reset_acquisition_state()


# ---------------------------------------------------------------------------------------------
# 1. Off unless asked for
# ---------------------------------------------------------------------------------------------


class TestAcquisitionIsOffByDefault:
    def test_it_is_disabled_with_no_environment_set(self, monkeypatch):
        monkeypatch.delenv(ACQUISITION_ENABLED_ENV, raising=False)
        assert acquisition_state("reliance_reliance") == (False, "disabled")

    def test_a_disabled_acquirer_makes_no_request(self, monkeypatch, disabled):
        calls: list[str] = []
        _install(monkeypatch, _Result(True), calls)

        assert acquire_filing("reliance_reliance") is False
        assert calls == [], f"a disabled acquirer still contacted the exchange: {calls}"

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "ON", "True"])
    def test_it_can_be_enabled_deliberately(self, monkeypatch, value):
        monkeypatch.setenv(ACQUISITION_ENABLED_ENV, value)
        assert pipeline.acquisition_enabled() is True

    def test_a_disabled_acquirer_does_not_even_open_a_session(self, monkeypatch, disabled):
        """Constructing the fetcher establishes a cookie session, which is itself a request."""
        calls: list[str] = []
        _install(monkeypatch, _Result(True), calls)

        acquire_filing("reliance_reliance")
        assert calls == [], f"a session was opened with acquisition disabled: {calls}"


# ---------------------------------------------------------------------------------------------
# 2. Bounded
# ---------------------------------------------------------------------------------------------


class TestNothingIsFetchedWhenItIsNotNeeded:
    def test_a_cached_company_is_never_fetched(self, monkeypatch, enabled):
        """TCS has a filing on disk. Asking again would be pure waste."""
        assert acquisition_state("tcs_tcs") == (False, "cached")

    def test_a_fetched_company_is_not_fetched_again(self, monkeypatch, enabled):
        """The locator is what knows a fetch landed -- it reads the metadata the acquirer writes."""
        landed = {"yes": False}
        monkeypatch.setattr(
            pipeline, "_cached_nse_pdfs", lambda cid: [(None, {})] if landed["yes"] else []
        )
        assert acquisition_state("newco_newco") == (True, "allowed")

        landed["yes"] = True
        assert acquisition_state("newco_newco") == (False, "cached")

    def test_an_empty_company_id_is_refused_without_a_request(self, monkeypatch, enabled):
        calls: list[str] = []
        _install(monkeypatch, _Result(True), calls)

        assert acquire_filing("_") is False
        assert calls == [], f"an empty company id still produced a request: {calls}"

    def test_a_failure_is_not_retried(self, monkeypatch, enabled):
        _install(monkeypatch, _Result(False, note="no attachment carried a balance sheet"))

        assert acquire_filing("newco_newco") is False
        assert acquisition_state("newco_newco") == (False, "recent-failure"), (
            "a filer with no available statement must not be retried on every request"
        )

    def test_a_transport_error_is_remembered_too(self, monkeypatch, enabled):
        _install(monkeypatch, RuntimeError("connection reset"))

        assert acquire_filing("newco_newco") is False
        assert acquisition_state("newco_newco") == (False, "recent-failure")

    def _age_the_failure(self, ticker: str, seconds: float) -> None:
        """Backdate a recorded failure so the TTL can be tested without touching the clock.

        Two earlier versions of this test tried to patch the clock instead. The first patched
        `pipeline.time.monotonic` with a lambda that CALLS it, which is infinite recursion rather
        than a passing test; the second found that `time` is imported inside the function precisely
        so the module keeps its lint count, so there is no module attribute to patch at all.

        Backdating the recorded timestamp is the direct expression of what the code checks -- "is
        this failure older than the TTL" -- and needs no monkeypatching of shared state.
        """
        pipeline._acquisition_failed[ticker] = time.monotonic() - seconds

    def test_the_memory_expires(self, monkeypatch, enabled):
        """Five minutes is a decision: a filing posted tomorrow must eventually be seen."""
        _install(monkeypatch, _Result(False, note="no attachment"))
        acquire_filing("newco_newco")
        assert acquisition_state("newco_newco") == (False, "recent-failure")

        self._age_the_failure("NEWCO", ACQUISITION_FAILED_TTL_SECONDS + 1)
        assert acquisition_state("newco_newco") == (True, "allowed"), (
            "the failure never expired, so a filing posted later could never be picked up"
        )

    def test_the_memory_is_not_expired_early(self, monkeypatch, enabled):
        """The other side of the TTL, because a TTL that expires early is just a shorter retry."""
        _install(monkeypatch, _Result(False, note="no attachment"))
        acquire_filing("newco_newco")

        self._age_the_failure("NEWCO", ACQUISITION_FAILED_TTL_SECONDS / 2)
        assert acquisition_state("newco_newco") == (False, "recent-failure"), (
            "the failure was forgotten half way through its own TTL"
        )

    def test_a_success_clears_a_previous_failure(self, monkeypatch, enabled):
        """Otherwise a company that failed once and then succeeded stays blocked for five minutes.

        The negative memory has to expire before a second attempt can even be made, so the sequence
        is fail, age past the TTL, then succeed. The first version of this test skipped the ageing
        and asserted that the second call returned True -- which contradicts the memory working at
        all, and the test failed for the right reason: you cannot test the recovery path through a
        guard that is correctly refusing you.
        """
        _install(monkeypatch, _Result(False, note="no attachment"))
        acquire_filing("newco_newco")
        assert acquisition_state("newco_newco") == (False, "recent-failure")

        self._age_the_failure("NEWCO", ACQUISITION_FAILED_TTL_SECONDS + 1)

        _install(monkeypatch, _Result(True))
        assert acquire_filing("newco_newco") is True, (
            "the attempt should succeed once the failure has aged out"
        )
        assert "NEWCO" not in pipeline._acquisition_failed, (
            "a successful fetch must clear the failure record, or the company is re-blocked for the "
            "full TTL immediately after succeeding"
        )


class TestTheBudgetIsBounded:
    def test_a_process_cannot_fetch_without_limit(self, monkeypatch, enabled):
        _install(monkeypatch, _Result(True))
        for i in range(ACQUISITION_BUDGET):
            assert acquire_filing(f"co{i}_co{i}") is True, f"blocked early at {i}"

        assert acquisition_state("overflow_overflow") == (False, "budget-exhausted"), (
            f"a process fetched more than {ACQUISITION_BUDGET} filings with no ceiling"
        )

    def test_a_failure_still_costs_budget(self, monkeypatch, enabled):
        """Otherwise failures are free and a broken endpoint costs unlimited requests."""
        _install(monkeypatch, RuntimeError("connection reset"))
        for i in range(ACQUISITION_BUDGET):
            acquire_filing(f"f{i}_f{i}")
        assert acquisition_state("overflow_overflow") == (False, "budget-exhausted")

    def test_the_budget_is_a_window_not_a_lifetime_cap(self, monkeypatch, enabled):
        """A long-running server must keep acquiring, or acquisition is dead with no symptom.

        The first version counted 25 fetches for the life of the process. A server would acquire 25
        filings and then stop forever, and nothing would distinguish that from acquisition being
        broken. Ages every recorded spend out of the window and the allowance returns.
        """
        _install(monkeypatch, _Result(True))
        for i in range(ACQUISITION_BUDGET):
            acquire_filing(f"co{i}_co{i}")
        assert acquisition_state("lateco_lateco") == (False, "budget-exhausted")

        stale = time.monotonic() - ACQUISITION_BUDGET_WINDOW_SECONDS - 1
        pipeline._acquisition_spends[:] = [stale] * len(pipeline._acquisition_spends)

        assert acquisition_state("lateco_lateco") == (True, "allowed"), (
            "the allowance never returned, so a long-running process acquires 25 filings and then "
            "stops silently for the rest of its life"
        )

    def test_the_budget_resets(self, monkeypatch, enabled):
        _install(monkeypatch, _Result(True))
        acquire_filing("newco_newco")
        assert len(pipeline._acquisition_spends) == 1

        reset_acquisition_state()
        assert pipeline._acquisition_spends == []

    def test_a_refused_call_does_not_spend_budget(self, monkeypatch, enabled):
        """A cached or recently-failed company must not consume the allowance."""
        _install(monkeypatch, _Result(True))
        acquire_filing("tcs_tcs")  # cached, refused
        assert pipeline._acquisition_spends == [], (
            "a refused call spent budget, so browsing cached companies would exhaust the allowance"
        )


# ---------------------------------------------------------------------------------------------
# 3. Quiet, and 4. per-symbol
# ---------------------------------------------------------------------------------------------


class TestFailureIsQuietAndWritesNothing:
    def test_a_clean_miss_returns_false_and_does_not_raise(self, monkeypatch, enabled):
        _install(monkeypatch, _Result(False, note="no attachment carried a balance sheet"))
        assert acquire_filing("newco_newco") is False

    def test_an_exception_returns_false_and_does_not_raise(self, monkeypatch, enabled):
        """The caller is a read path. An acquisition failure must never become an error page."""
        _install(monkeypatch, RuntimeError("boom"))
        assert acquire_filing("newco_newco") is False

    def test_one_companys_failure_does_not_block_another(self, monkeypatch, enabled):
        """Otherwise a single unavailable filer stops acquisition for the whole universe."""
        _install(monkeypatch, _Result(False, note="no attachment"))
        acquire_filing("badco_badco")

        assert acquisition_state("otherco_otherco") == (True, "allowed")

    def test_the_hook_in_batch_cannot_break_a_read(self):
        """The guard around the guard. A broken acquirer must not break ingestion.

        Asserted on the source rather than by running ingestion, because running it needs a store and
        a store makes this a test about the fixture. The property is structural: the call site is
        wrapped, so no exception from acquisition can reach a caller.
        """
        import inspect

        from backend.data.batch import ensure_company_ingested

        source = inspect.getsource(ensure_company_ingested)
        assert "acquire_filing" in source, (
            "the acquisition hook is missing, so a feed-only company is never asked for its filing"
        )
        assert "except Exception" in source, (
            "the acquisition call is unwrapped, so a broken acquirer breaks every read"
        )