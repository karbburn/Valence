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

import pytest

from backend.data.universe import ticker_index as ti


@pytest.fixture
def isolated_cache(monkeypatch):
    """An empty cache directory, so the fetch path is genuinely exercised."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setattr(ti, "CACHE_DIR", tmp)
    for market in ti.SUPPORTED:
        ti._cache.pop(market, None)
    yield tmp


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

    def genuinely_slow_us_fetch():
        us_started.set()
        # A real 2.5s of wall clock, not an event release, so the blocking
        # window is wide enough to measure rather than race against.
        time.sleep(2.5)
        return {"ZZZ": ti.ListedCompany("ZZZ", "Slow Co", "us", "SEC")}

    ti._FETCHERS["us"] = genuinely_slow_us_fetch

    def fetch_us() -> None:
        us_result["value"] = ti.index_for("us")

    def fetch_india() -> None:
        us_started.wait(timeout=5)
        t0 = time.time()
        got = ti.index_for("india")
        india_latency.append(time.time() - t0)
        assert got == {"INR": india_entry}

    us_thread = threading.Thread(target=fetch_us)
    india_thread = threading.Thread(target=fetch_india)
    us_thread.start()
    us_started.wait(timeout=5)  # the US fetch now holds whatever lock it takes
    india_thread.start()
    us_thread.join(timeout=30)
    india_thread.join(timeout=30)

    assert india_latency, "the India caller never ran"
    # A global lock blocks India for the full 2.5s of the US fetch. Per-market
    # in-flight markers make it independent, so it is milliseconds.
    assert india_latency[0] < 0.5, (
        f"an unrelated market was blocked for {india_latency[0]:.2f}s by a US fetch"
    )


def test_concurrent_callers_share_one_fetch(isolated_cache, monkeypatch):
    """Five callers racing for one cold market must produce one fetch."""
    counter = _install_slow_fetcher(monkeypatch, seconds=1.0)

    latencies: list[float] = []
    start = threading.Barrier(5)

    def hit() -> None:
        start.wait()
        t0 = time.time()
        ti.index_for("us")
        latencies.append(time.time() - t0)

    threads = [threading.Thread(target=hit) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(latencies) == 5
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


def test_a_ticker_listed_on_two_markets_is_not_deduplicated_away(
    isolated_cache, monkeypatch
):
    """(ticker, market) is the identity. Ticker alone collapses two companies."""
    monkeypatch.setitem(
        ti._FETCHERS,
        "us",
        lambda: {"INFO": ti.ListedCompany("INFO", "Infosys ADR", "us", "SEC")},
    )
    monkeypatch.setitem(
        ti._FETCHERS,
        "india",
        lambda: {"INFO": ti.ListedCompany("INFO", "Infosys Ltd", "india", "NSE")},
    )

    both = ti.search("INFO", limit=10)
    markets = sorted(c.market for c in both)
    assert markets == ["india", "us"], f"collapsed to {markets}"
