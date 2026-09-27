"""Concurrency and scoping tests for the listed-universe index.

Three defects that only appear under load or under a market scope, so they are
pinned here rather than left to a manual check:

1. The fetch used to run inside a process-global lock. Five concurrent callers
   against a 2-second upstream serialised into 10 seconds, and because a search
   reads two markets one user request could hold a search open for a minute.
2. A failed fetch was not cached, so an outage re-paid the full timeout on every
   subsequent request, on an unauthenticated endpoint.
3. The market scope was applied after ranking, so a request scoped to one
   market spent its result budget on the other market's rows and then discarded
   them.
"""

from __future__ import annotations

import pathlib
import tempfile
import threading
import time
import types

import pytest

from backend.data.universe import ticker_index as ti


@pytest.fixture
def isolated_cache(monkeypatch):
    """An empty cache directory, so the fetch path is genuinely exercised.

    The module globals are saved and restored, not just emptied. `monkeypatch`
    puts CACHE_DIR back but nothing put `_cache` back: every test here leaves
    fabricated entries behind, and after this file ran, `index_for`, `search`,
    `lookup` and `resolve_or_register` in the same process answered from them
    and never touched the network or the real cache directory again. Any later
    test asserting on real universe behaviour was then asserting on data this
    file invented. `_inflight` goes the same way, because a gate stranded by
    one test turns the next test's first caller into a waiter.
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setattr(ti, "CACHE_DIR", tmp)
    saved_cache = dict(ti._cache)
    saved_inflight = dict(ti._inflight)
    ti._cache.clear()
    ti._inflight.clear()
    yield tmp
    ti._cache.clear()
    ti._cache.update(saved_cache)
    ti._inflight.clear()
    ti._inflight.update(saved_inflight)


def _install_slow_fetcher(monkeypatch, seconds: float = 2.0) -> dict:
    counter = {"n": 0}

    def fetch():
        counter["n"] += 1
        time.sleep(seconds)
        return {"ZZZ": ti.ListedCompany("ZZZ", "Slow Co", "us", "SEC")}

    monkeypatch.setitem(ti._FETCHERS, "us", fetch)
    return counter


def test_one_market_slow_fetch_does_not_block_the_other_market(
    isolated_cache, monkeypatch
):
    """A cold US index must not hold up a caller that only needs India.

    This is the defect the global lock actually caused, and it is worth being
    precise about which one it is, because the obvious version of the claim is
    false: five callers racing for the *same* market were never serialised into
    five fetches, because the first one published to the cache and the rest read
    it. That case was always fine.

    The real cost was cross-market. `_lock` was global, so a request for India
    could not even read a fresh India cache entry while a US fetch was in
    flight, and `search` reads both markets, so one slow upstream put a floor
    under every search in the process.
    """
    india_entry = ti.ListedCompany("INR", "India Cached", "india", "NSE")
    monkeypatch.setitem(
        ti._FETCHERS, "india", lambda: {"INR": india_entry}
    )

    us_started = threading.Event()
    us_result: dict = {}
    india_latency: list[float] = []
    india_result: dict = {}

    def genuinely_slow_us_fetch():
        us_started.set()
        # A real 2.5s of wall clock, not an event release, so the blocking
        # window is wide enough to measure rather than race against.
        time.sleep(2.5)
        return {"ZZZ": ti.ListedCompany("ZZZ", "Slow Co", "us", "SEC")}

    monkeypatch.setitem(ti._FETCHERS, "us", genuinely_slow_us_fetch)

    def fetch_us() -> None:
        us_result["value"] = ti.index_for("us")

    def fetch_india() -> None:
        us_started.wait(timeout=5)
        t0 = time.time()
        got = ti.index_for("india")
        india_latency.append(time.time() - t0)
        # Recorded, not asserted. An assert in a non-main thread is swallowed:
        # pytest reports the failure as a warning and the test passes, which is
        # how a waiter returning `{}` — the exact regression this suite exists to
        # catch — could leave this green. The claim under test below is about
        # latency, and it is only half a claim without the data being right.
        india_result["value"] = got

    us_thread = threading.Thread(target=fetch_us)
    india_thread = threading.Thread(target=fetch_india)
    us_thread.start()
    us_started.wait(timeout=5)  # the US fetch now holds whatever lock it takes
    india_thread.start()
    us_thread.join(timeout=30)
    india_thread.join(timeout=30)

    assert not us_thread.is_alive(), "the US fetch never finished"
    assert not india_thread.is_alive(), "the India caller never finished"
    assert india_latency, "the India caller never ran"
    # A global lock blocks India for the full 2.5s of the US fetch. Per-market
    # in-flight markers make it independent, so it is milliseconds.
    assert india_latency[0] < 0.5, (
        f"an unrelated market was blocked for {india_latency[0]:.2f}s by a US fetch"
    )
    assert india_result.get("value") == {"INR": india_entry}, (
        f"India got {india_result.get('value')!r}, which is not the fetched index"
    )
    assert us_result.get("value") == {
        "ZZZ": ti.ListedCompany("ZZZ", "Slow Co", "us", "SEC")
    }, f"the US fetch returned {us_result.get('value')!r}"


def test_concurrent_callers_share_one_fetch(isolated_cache, monkeypatch):
    """Five callers racing for one cold market must produce one fetch.

    What each of them *receives* is asserted as well as how many fetches ran.
    One fetch is compatible with four waiters getting nothing: the count holds
    whether the waiters return the published index or an empty dict, and the
    empty answer is the one that is indistinguishable from "no such company".
    """
    counter = _install_slow_fetcher(monkeypatch, seconds=1.0)
    expected = {"ZZZ": ti.ListedCompany("ZZZ", "Slow Co", "us", "SEC")}

    latencies: list[float] = []
    got: list[dict] = []
    start = threading.Barrier(5)

    def hit() -> None:
        start.wait()
        t0 = time.time()
        got.append(ti.index_for("us"))
        latencies.append(time.time() - t0)

    threads = [threading.Thread(target=hit) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(latencies) == 5
    assert not any(t.is_alive() for t in threads), "a caller never returned"
    for received in got:
        assert received == expected, f"a caller received {received!r}"
    assert counter["n"] == 1, f"made {counter['n']} fetches, expected 1"


def test_a_failed_fetch_is_cached_so_an_outage_is_not_re_paid(
    isolated_cache, monkeypatch
):
    """An upstream outage must cost one attempt per window, not one per call."""
    attempts = {"n": 0}

    def failing():
        attempts["n"] += 1
        raise RuntimeError("upstream down")

    monkeypatch.setitem(ti._FETCHERS, "us", failing)

    latencies = []
    for _ in range(4):
        t0 = time.time()
        assert ti.index_for("us") == {}
        latencies.append(time.time() - t0)

    assert attempts["n"] == 1, f"re-fetched {attempts['n']} times during an outage"
    # The first call may pay the timeout; the rest must not.
    assert max(latencies[1:]) < 0.01, f"later calls still slow: {latencies}"


def test_a_waiter_waits_out_a_slow_but_successful_fetch(
    isolated_cache, monkeypatch
):
    """A fetch that takes longer than one request leg must still reach waiters.

    `requests` applies `timeout` to the connect and to the read separately, so
    a fetch that spends FETCH_TIMEOUT connecting and FETCH_TIMEOUT reading is
    twice that and *succeeds*. A waiter bound of FETCH_TIMEOUT + 5 therefore
    expires while the fetch it is waiting for is about to publish a perfectly
    good index, and every concurrent caller gets `{}` — an empty answer with a
    200, indistinguishable from "no such company", on precisely the degraded
    network this path exists for. The global lock it replaced queued waiters
    and handed them the data, so this was a regression, not a trade.

    The bound is scaled down rather than waited out at production size:
    FETCH_TIMEOUT is patched to 0.2s, which puts the old bound at 5.2s and the
    current one (two timeouts plus the allowance) at 15.4s, and the fetch is
    given 6s. Six seconds is the floor here, not a choice — the old bound has a
    hard-coded 5 on it, so any fetch that outlasts it has to outlast 5s.
    """
    monkeypatch.setattr(ti, "FETCH_TIMEOUT", 0.2)
    slow_seconds = 6.0
    entry = {"ZZZ": ti.ListedCompany("ZZZ", "Slow Co", "us", "SEC")}

    started = threading.Event()

    def slow_but_successful():
        started.set()
        time.sleep(slow_seconds)
        return entry

    monkeypatch.setitem(ti._FETCHERS, "us", slow_but_successful)

    first_result: dict = {}
    waiter_results: list[dict] = []

    def fetch_it() -> None:
        first_result["value"] = ti.index_for("us")

    def wait_for_it() -> None:
        started.wait(timeout=5)
        waiter_results.append(ti.index_for("us"))

    first = threading.Thread(target=fetch_it)
    waiter = threading.Thread(target=wait_for_it)
    first.start()
    started.wait(timeout=5)
    waiter.start()
    first.join(timeout=60)
    waiter.join(timeout=60)

    assert not first.is_alive() and not waiter.is_alive(), "a caller never returned"
    assert first_result.get("value") == entry, "the fetch itself did not land"
    assert waiter_results == [entry], (
        f"the waiter received {waiter_results!r} from a fetch that succeeded "
        f"after {slow_seconds}s"
    )


def test_market_scope_is_applied_before_the_limit(isolated_cache, monkeypatch):
    """A scoped search must fill its budget from the scoped market."""
    monkeypatch.setitem(
        ti._FETCHERS,
        "us",
        lambda: {
            "USAA": ti.ListedCompany("USAA", "US Alpha", "us", "SEC"),
            "USAB": ti.ListedCompany("USAB", "US Bravo", "us", "SEC"),
            "USAC": ti.ListedCompany("USAC", "US Charlie", "us", "SEC"),
        },
    )
    monkeypatch.setitem(
        ti._FETCHERS,
        "india",
        lambda: {
            "INAA": ti.ListedCompany("INAA", "India Alpha", "india", "NSE"),
            "INAB": ti.ListedCompany("INAB", "India Bravo", "india", "NSE"),
            "INAC": ti.ListedCompany("INAC", "India Charlie", "india", "NSE"),
        },
    )

    us_only = ti.search("USA", limit=3, market="us")
    assert {c.ticker for c in us_only} == {"USAA", "USAB", "USAC"}
    assert all(c.market == "us" for c in us_only), "scope leaked another market"

    india_only = ti.search("INA", limit=3, market="india")
    assert {c.ticker for c in india_only} == {"INAA", "INAB", "INAC"}
    assert all(c.market == "india" for c in india_only)

    unscoped = ti.search("USA", limit=3)
    assert len(unscoped) == 3, "an unscoped search still has to fill its budget"


def _install_dual_listed_info(monkeypatch) -> None:
    """The index lists INFO on both exchanges, as SEC and the NSE both do."""
    monkeypatch.setitem(
        ti._FETCHERS,
        "us",
        lambda: {
            "INFO": ti.ListedCompany(
                "INFO", "Infosys ADR", "us", "SEC", cik="0001067983"
            )
        },
    )
    monkeypatch.setitem(
        ti._FETCHERS,
        "india",
        lambda: {
            "INFO": ti.ListedCompany(
                "INFO", "Infosys Ltd", "india", "NSE", isin="INE009A08021"
            )
        },
    )


def _store_holding_only_india(monkeypatch) -> None:
    """The local store holds the Indian line of INFO and nothing else.

    The other exchange lists the same ticker, which is the case that matters:
    `slugs.LISTING_PRIMARY` makes the Indian line the primary, so it is the one
    a search registers first, and the ADR is the one a later user is left
    unable to reach. `search_universe_companies` honours `market`, which is the
    point — a store stub that ignored the filter could not tell a scoped query
    from an unscoped one.
    """
    from backend.data.universe import store
    from backend.data.universe.models import UniverseCompany

    stored = UniverseCompany(
        company_id="info_info",
        ticker="INFO",
        name="Infosys Ltd",
        market="india",
        exchange="NSE",
        sector="",
        industry="",
    )

    def search_universe_companies(query, market=None, limit=50, **kwargs):
        if market == "us":
            return []
        return [stored]

    monkeypatch.setattr(store, "search_universe_companies", search_universe_companies)


def test_discover_keeps_the_other_market_when_one_listing_is_stored(
    isolated_cache, monkeypatch
):
    """(ticker, market) is the identity, in the exclusion set as well as the dedup.

    The previous version of this test called `search`, whose key was already
    (ticker, market) before the change, so it passed on the code it was written
    to cover. `discover` is where the exclusion actually happens: it drops the
    index rows the local store already holds, and it was doing that by ticker
    alone against a store query spanning both markets. So the Indian INFO in the
    store removed the US ADR, `discover` returned nothing, and the caller's own
    (ticker, market) dedup could not put back a row it never saw — which is the
    "a user who wanted the ADR has no way to reach it" case, unfixed.
    """
    _install_dual_listed_info(monkeypatch)
    _store_holding_only_india(monkeypatch)

    # Precondition: both listings are in the index. Without this, an empty result
    # below could be a missing fixture rather than a broken exclusion.
    assert sorted(c.market for c in ti.search("INFO", limit=10)) == ["india", "us"]

    found = ti.discover("INFO", limit=10)
    assert [(c.ticker, c.market) for c in found] == [("INFO", "us")], (
        f"discover returned {[(c.ticker, c.market) for c in found]}, so the stored "
        f"Indian line took the US listing with it"
    )

    scoped = ti.discover("INFO", limit=10, market="us")
    assert [(c.ticker, c.market) for c in scoped] == [("INFO", "us")]


def test_the_search_endpoint_still_offers_the_adr_when_the_primary_is_stored(
    isolated_cache, monkeypatch
):
    """The endpoint has to reach both listings, and so does its own dedup key.

    Driven through `search_companies` rather than `discover`, because the
    endpoint is where a user meets this: the local pass runs first and the index
    fills the remaining room, and both passes have to agree that INFO-on-NSE and
    INFO-on-SEC are two companies. A ticker-only key on either side of that
    boundary costs the user one of them.
    """
    from backend.api import routes
    from backend.data.universe import store
    from backend.models.spec import metadata

    _install_dual_listed_info(monkeypatch)
    _store_holding_only_india(monkeypatch)
    monkeypatch.setattr(routes, "_ensure_universe_seeded", lambda: None)
    monkeypatch.setattr(routes, "_has_compiled_model", lambda company_id: False)
    monkeypatch.setattr(store, "preview_slug", lambda ticker: ticker.lower())
    monkeypatch.setattr(
        metadata,
        "get_metadata_for_company",
        lambda company_id: types.SimpleNamespace(
            currency="INR", units="ones", fiscal_year_end=None
        ),
    )

    rows = routes.search_companies("INFO", limit=10)
    by_market = {row["market"]: row for row in rows}

    assert "us" in by_market, (
        "the ADR is missing from the response: "
        f"{[(r['ticker'], r['market']) for r in rows]}"
    )
    assert by_market["us"]["company_id"] != by_market["india"]["company_id"]
    assert by_market["us"]["has_model"] is False

