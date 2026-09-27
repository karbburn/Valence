"""Ingestion throttle behaviour.

Live ingestion is the only expensive, unbounded, network-dependent work the API
does. Once /stock/<ticker> is public, an unrecognised-but-well-formed slug must
not be able to reach it, and a recognised one must not be able to arrive in a
stampede. These tests pin the three controls that prevent both.
"""

from __future__ import annotations

import threading
import time

import pytest

from backend.api import throttle


@pytest.fixture(autouse=True)
def _clean_throttle():
    throttle.reset_for_tests()
    yield
    throttle.reset_for_tests()


def test_ingest_slot_is_granted_when_capacity_is_free():
    with throttle.ingest_slot("nvda_us") as got:
        assert got is True
    assert throttle.in_flight_count() == 0


def test_ingest_slot_refuses_rather_than_queueing_when_saturated():
    """Saturation degrades to a fast refusal, not a pile of waiting threads.

    A burst of uncached slugs should produce quick, honest 503s rather than an
    unbounded queue of threads all blocked on a provider that will not answer
    any faster for being asked twice. Capacity is configuration, so the test
    exhausts whatever it is set to rather than assuming a number.
    """
    capacity = throttle.INGEST_CONCURRENCY
    assert capacity >= 1

    release = threading.Event()
    granted = []
    errors = []

    def hold_one(i):
        try:
            with throttle.ingest_slot(f"filler_{i}_us") as got:
                granted.append(got)
                release.wait(15)
        except Exception as exc:
            errors.append(exc)

    workers = [threading.Thread(target=hold_one, args=(i,), daemon=True) for i in range(capacity)]
    for w in workers:
        w.start()

    # Poll the real condition rather than synchronising on a barrier. A barrier
    # releases its waiters and immediately resets for a new generation, so a
    # thread that arrives after the trip waits for a cycle that never comes.
    deadline = time.monotonic() + 10
    while throttle.in_flight_count() < capacity and time.monotonic() < deadline:
        time.sleep(0.01)
    assert throttle.in_flight_count() == capacity, (
        f"only {throttle.in_flight_count()} of {capacity} slots were taken"
    )

    try:
        with throttle.ingest_slot("overflow_us") as got:
            assert got is False, f"a slot was granted with all {capacity} slots held"
    finally:
        release.set()
        for w in workers:
            w.join(10)

    assert not errors, errors
    assert granted == [True] * capacity


def test_single_flight_admits_exactly_one_caller():
    outcomes = []
    inside = threading.Event()
    release = threading.Event()

    def run(name):
        with throttle.single_flight(name) as first:
            outcomes.append((name, first))
            if first:
                inside.set()
                release.wait(5)

    workers = [threading.Thread(target=run, args=("nvda_us",), daemon=True) for _ in range(6)]
    for w in workers:
        w.start()
    assert inside.wait(5), "no caller acquired single-flight"
    time.sleep(0.15)
    release.set()
    for w in workers:
        w.join(5)

    winners = [n for n, first in outcomes if first]
    assert len(winners) == 1, f"single-flight admitted {len(winners)} callers: {outcomes}"


def test_single_flight_is_scoped_per_company():
    """Two different uncached tickers must not block each other."""
    with throttle.single_flight("nvda_us") as a:
        with throttle.single_flight("aapl_us") as b:
            assert a is True
            assert b is True


def test_negative_cache_blocks_retry_inside_the_ttl():
    throttle.mark_failure("broken_us")
    assert throttle.is_negative("broken_us") is True
    assert throttle.negative_cache_size() == 1


def test_negative_cache_is_cleared_by_a_later_success():
    throttle.mark_failure("broken_us")
    throttle.clear_failure("broken_us")
    assert throttle.is_negative("broken_us") is False
    assert throttle.negative_cache_size() == 0


def test_negative_cache_expires(monkeypatch):
    """A provider coming back online must be picked up, not blocked for hours."""
    clock = {"t": 1000.0}
    monkeypatch.setattr(throttle.time, "monotonic", lambda: clock["t"])

    throttle.mark_failure("broken_us")
    assert throttle.is_negative("broken_us") is True

    clock["t"] += throttle.NEGATIVE_CACHE_TTL + 1
    assert throttle.is_negative("broken_us") is False
    assert throttle.negative_cache_size() == 0, "expired entry was not evicted"


def test_is_negative_is_false_for_an_unknown_company():
    assert throttle.is_negative("never_seen_us") is False


def test_in_flight_count_tracks_the_slot():
    assert throttle.in_flight_count() == 0
    with throttle.ingest_slot("nvda_us"):
        assert throttle.in_flight_count() == 1
    assert throttle.in_flight_count() == 0
