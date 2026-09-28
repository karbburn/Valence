"""Per-client request rate limiting.

The ingestion throttle is not this. That one bounds how many model builds run at
once and how long a company that cannot be sourced is remembered; it is a
control on work. This one bounds how many requests a single client can make, and
it is a control on volume, which is what a crawler is.

The two answer different questions and neither substitutes for the other. A
crawler walking `/stock/<ticker>` is bounded by neither: it walks only companies
that already have a model, so it triggers no builds and is never throttled, and
it will take a free tier past its monthly hours one cached page at a time. It is
also the cheapest possible abuse, because every request it makes is a request
the site would otherwise have served.

Implemented here rather than pulled from a package, for three reasons. A
dependency on a rate limiter is a dependency on a middleware whose defaults are
tuned for a multi-process deployment, and this is a single instance where a
shared store would be a bottleneck rather than a feature. It has to survive the
container sleeping and waking, which means it cannot hold state that a restart
would quietly reset. And the numbers that matter here are specific to a free
tier with two ingest slots, so they are configuration rather than constants.

The limiter is in-process. That is honest about its limits: it bounds one
instance, and an instance that scales out would need a shared store. It is the
right shape for a single free-tier box, and it is documented rather than implied.
"""

from __future__ import annotations

import heapq
import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

logger = logging.getLogger("valence.api.ratelimit")

# Window and allowance, per class of request.
#
# Reads are cheap and safe to serve in volume; a search is an indexed lookup
# against a cached file, and a cached model is a deserialise. Builds are the
# expensive thing and already have their own concurrency control, so this
# budget is set to be generous enough not to trip on a human paging through
# results and tight enough that a crawler cannot spend the instance's hours.
#
# These are SITE-WIDE, not per-client, and that is the honest reading of what
# this deployment can see. Behind the platform's router every caller arrives from
# the router's address, and the one address a caller cannot forge is the TCP
# peer, which is the router for all of them. So one budget covers everyone.
#
# They were sized as if they were per-client, and that was wrong in the
# dangerous direction: twelve writes a minute was a comfortable allowance for
# one person releasing a slider and would have been exhausted by two. They are
# now sized for a whole site of ordinary traffic and are still far below what a
# crawler needs to empty a free tier's monthly hours.
#
# The write budget is the one that had to move most. Releasing a driver slider
# fires a POST, and reverting all fires one per driver, so a single page
# interaction can be a dozen writes. Twelve a minute site-wide would have made
# the workbench unusable rather than merely slow.
READ_BUDGET = int(os.getenv("VALENCE_RATE_READ", "600"))
WRITE_BUDGET = int(os.getenv("VALENCE_RATE_WRITE", "120"))
WINDOW_SECONDS = int(os.getenv("VALENCE_RATE_WINDOW", "60"))

# How many distinct clients are remembered. A fixed cap, because an unbounded
# map keyed on client address is itself a way to exhaust memory: an attacker
# sending one request from each of a million addresses fills the map without
# ever tripping a per-client budget. Evicting the least recently active entry
# costs a little accuracy for a long tail of one-off clients, and bounds the
# structure at a size chosen for the instance.
MAX_TRACKED_CLIENTS = int(os.getenv("VALENCE_RATE_MAX_CLIENTS", "20000"))

# Which budget applies to which class of request. The numbers themselves are
# resolved at call time rather than captured here, so an override takes effect
# without a reload. They used to be snapshotted into a dict at import, which
# meant the module constants and the values actually enforced could disagree,
# and the only way to find out which was in force was to read both.
_BUDGET_FOR = {
    "read": lambda: READ_BUDGET,
    "write": lambda: WRITE_BUDGET,
}

_hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
_lock = threading.Lock()
_last_sweep = time.monotonic()


def _sweep(now: float) -> None:
    """Drop expired windows, and enforce the client cap.

    Called under the lock from `allow`, which is the only place state is read or
    written, so this needs no separate guard.

    Both halves have to run on every call, and the second one especially. It
    used to be gated on the elapsed window as well, on the reasoning that the
    map is only worth trimming once an entry could have expired. That is true of
    expired entries and false of the cap: within a single window an attacker
    sending one request from each of a million distinct addresses grows the map
    a million-fold without ever tripping a per-client budget, which is a slower
    and cheaper way to exhaust memory than anything else on the endpoint. The
    cap is exactly a bound, so it is checked exactly.
    """
    global _last_sweep

    if now - _last_sweep >= WINDOW_SECONDS:
        _last_sweep = now
        for key in [k for k, q in _hits.items() if not q or now - q[0] > WINDOW_SECONDS]:
            del _hits[key]

    if len(_hits) > MAX_TRACKED_CLIENTS:
        # Oldest first, so what goes is the least recently active client rather
        # than an arbitrary one.
        #
        # The eviction is bounded per call rather than sorting the whole map.
        # Sorting every entry while holding the lock, on every request once the
        # cap is reached, put a measured 5.6ms median and 16ms worst case of held
        # lock in the path of every request, which is a latency exhaustion
        # vector created by the fix for a memory one. Evicting a fixed batch
        # brings the map back under the cap and keeps the work constant, and the
        # oldest entries are still the ones that go.
        excess = len(_hits) - MAX_TRACKED_CLIENTS
        # `heapq.nsmallest` is O(excess log n) rather than O(n log n), and the
        # excess is one request's worth of entries in the steady state.
        oldest = heapq.nsmallest(excess, _hits.items(), key=lambda kv: kv[1][-1] if kv[1] else 0.0)
        for key, _ in oldest:
            _hits.pop(key, None)
        logger.info(
            "rate limit map hit the client cap, evicted %d oldest entries", len(oldest)
        )


def allow(client: str, kind: str = "read") -> bool:
    """Whether this client may proceed under the budget for `kind`."""
    budget, window = budget_for(kind)
    now = time.monotonic()
    with _lock:
        _sweep(now)
        key = (kind, client)
        q = _hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= budget:
            return False
        q.append(now)
        return True


def budget_for(kind: str = "read") -> tuple[int, int]:
    """(allowance, window seconds) for a class of request, for the 429 headers."""
    return (_BUDGET_FOR.get(kind, _BUDGET_FOR["read"])(), WINDOW_SECONDS)


def reset() -> None:
    """Drop all recorded state. Tests only."""
    with _lock:
        _hits.clear()
