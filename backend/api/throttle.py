"""Throttle around on-demand model ingestion.

`ensure_company_ingested` performs live third-party ingestion (SEC EDGAR,
yfinance, Indian equity providers) with no limit of its own, and
`_get_or_build_spec` calls it inline on the request thread. Once a public
`/stock/<ticker>` route exists, that turns an open ingestion path into a
crawl-triggerable one: a crawler walking single-letter tickers would otherwise
fire unbounded concurrent builds at a single-instance free-tier deployment.

Three controls, because each covers a different failure:

* a **semaphore**, so concurrent builds queue instead of piling onto the box
* **in-flight de-dupe**, so N requests for the same uncached ticker cause one
  build rather than N
* a **negative cache**, so a slug that cannot be sourced is not retried on
  every request

Depth is configuration, not a constant, because it is a measurement. See
`01-load-test-protocol.md` for how it was derived.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Dict, Iterator, Set

logger = logging.getLogger("valence.api.ingest")

# Measured against the free-tier instance, not guessed. Override per environment
# once a load test has been run against that environment.
INGEST_CONCURRENCY = int(os.getenv("VALENCE_INGEST_CONCURRENCY", "2"))

# How long a failed ingestion is remembered. Long enough that a crawler probing
# slugs cannot hammer the upstream providers, short enough that a provider
# coming back online is picked up quickly.
NEGATIVE_CACHE_TTL = int(os.getenv("VALENCE_INGEST_NEGATIVE_TTL", "300"))

_ingest_slots = threading.Semaphore(max(1, INGEST_CONCURRENCY))

_build_locks: Dict[str, threading.Lock] = {}
_build_locks_guard = threading.Lock()

_inflight: Set[str] = set()
_inflight_guard = threading.Lock()

_negative: Dict[str, float] = {}
_negative_guard = threading.Lock()


def _lock_for(company_id: str) -> threading.Lock:
    with _build_locks_guard:
        lock = _build_locks.get(company_id)
        if lock is None:
            lock = threading.Lock()
            _build_locks[company_id] = lock
        return lock


def is_negative(company_id: str) -> bool:
    """True when this company recently failed to ingest and must not be retried."""
    now = time.monotonic()
    with _negative_guard:
        expiry = _negative.get(company_id)
        if expiry is None:
            return False
        if expiry <= now:
            _negative.pop(company_id, None)
            return False
        return True


def mark_failure(company_id: str) -> None:
    with _negative_guard:
        _negative[company_id] = time.monotonic() + NEGATIVE_CACHE_TTL


def clear_failure(company_id: str) -> None:
    with _negative_guard:
        _negative.pop(company_id, None)


def negative_cache_size() -> int:
    with _negative_guard:
        return len(_negative)


@contextmanager
def ingest_slot(company_id: str) -> Iterator[bool]:
    """Hold one of the ingestion slots, and mark this company as in flight.

    Yields False, without blocking, when every slot is already taken. Callers
    treat that as "serve what we have" rather than queueing, so a burst of
    uncached slugs degrades into fast partial answers instead of a pile of
    threads all waiting on a provider that will not answer faster.
    """
    acquired = _ingest_slots.acquire(blocking=False)
    if not acquired:
        logger.warning("Ingestion saturated (%d slots busy); skipping live build for %s",
                       INGEST_CONCURRENCY, company_id)
        yield False
        return
    with _inflight_guard:
        _inflight.add(company_id)
    try:
        yield True
    finally:
        with _inflight_guard:
            _inflight.discard(company_id)
        _ingest_slots.release()


@contextmanager
def single_flight(company_id: str) -> Iterator[bool]:
    """Yield True for exactly one caller at a time per company_id.

    Yields False immediately for the callers that lose the race. Combined with
    the LRU, the losers then read the winner's freshly-stored spec instead of
    starting a second identical build.
    """
    lock = _lock_for(company_id)
    if not lock.acquire(blocking=False):
        yield False
        return
    try:
        yield True
    finally:
        lock.release()


def in_flight_count() -> int:
    with _inflight_guard:
        return len(_inflight)


def reset_for_tests() -> None:
    """Drop all throttle state. Tests only."""
    global _ingest_slots
    _ingest_slots = threading.Semaphore(max(1, INGEST_CONCURRENCY))
    with _build_locks_guard:
        _build_locks.clear()
    with _inflight_guard:
        _inflight.clear()
    with _negative_guard:
        _negative.clear()
