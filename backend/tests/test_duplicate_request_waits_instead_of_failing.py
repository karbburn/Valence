"""A duplicate request must WAIT for the build it collided with, not be refused.

`single_flight` yields False to the caller that loses the race. Its own docstring
then promises what the loser is supposed to do:

    Yields False immediately for the callers that lose the race. Combined with the
    LRU, the losers then read the winner's freshly-stored spec instead of starting
    a second identical build.

The caller did not do that. It raised 503:

    "This model is being compiled right now. Retry in a few seconds."

So the duplicate suppression worked and the reuse did not. The mechanism bought an
error instead of a saving -- and the error was worst exactly where the product is
slowest, because the window a build holds the lock for IS the build's duration.

Measured on 2026-10-02: the India models take 10-27s to serve, because their live
price is fetched per request from a market feed. The frontend and the audit loop
asking for the same company at the same moment produced exactly this 503, and the
site gate reported it as `tatasteel_tatasteel: HTTP 503 -- This model is being
compiled right now`.

Two readers of one cached value is not a reason to fail either of them.
"""

from __future__ import annotations

import inspect
import pathlib
import re
import sys
import threading
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.api import routes, throttle  # noqa: E402


class TestTheLoserWaitsRatherThanFails:
    def test_throttle_exposes_a_wait(self):
        assert hasattr(throttle, "wait_for_build"), (
            "there is no way for the loser of a race to wait, so the only options "
            "left are to fail or to build a duplicate"
        )

    def test_the_wait_returns_true_once_the_winner_releases(self):
        """The property itself, on a real lock."""
        throttle.reset_for_tests()
        cid = "wait_probe_us"
        with throttle.single_flight(cid):
            # From another thread, while the winner holds the lock.
            result = {}

            def loser():
                result["ok"] = throttle.wait_for_build(cid, timeout=5.0)

            th = threading.Thread(target=loser)
            th.start()
            time.sleep(0.25)
            assert "ok" not in result, (
                "wait_for_build returned while the winner still held the lock, so it "
                "is not waiting at all"
            )
        th.join(timeout=5)
        assert result.get("ok") is True, (
            "wait_for_build did not report success after the winner released the lock"
        )

    def test_the_wait_gives_up_on_timeout(self):
        throttle.reset_for_tests()
        cid = "timeout_probe_us"
        with throttle.single_flight(cid):
            t0 = time.time()
            assert throttle.wait_for_build(cid, timeout=0.4) is False
            waited = time.time() - t0
        assert 0.3 <= waited < 3.0, (
            "a timeout must actually block for roughly the timeout and then give "
            "up, not return instantly or hang"
        )

    def test_a_zero_timeout_does_not_block(self):
        throttle.reset_for_tests()
        cid = "zero_probe_us"
        with throttle.single_flight(cid):
            t0 = time.time()
            assert throttle.wait_for_build(cid, timeout=0) is False
            assert time.time() - t0 < 0.2


class TestTheCallerHonoursThePromise:
    def test_the_loser_reads_the_winners_result(self):
        """The bug was the CALLER, not the throttle, so the test reads the caller."""
        src = inspect.getsource(routes._get_or_build_spec)
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)

        i_flight = code.find("single_flight(")
        assert i_flight != -1, "the single-flight guard is gone entirely"

        branch = code[i_flight:]
        assert "wait_for_build(" in branch, (
            "the loser of a single-flight race no longer waits; it must wait for "
            "the winner and reuse the result"
        )
        assert "_lru_get(_MODEL_CACHE" in branch, (
            "the loser waits but never reads the winner's stored model, so the wait "
            "buys nothing and the duplicate build is still avoided at the cost of "
            "an error"
        )
        # The 503 must survive as a genuine fallback -- after the wait fails -- not
        # as the first thing a loser meets.
        i_wait = branch.find("wait_for_build(")
        i_503 = branch.find("status_code=503")
        assert i_503 == -1 or i_503 > i_wait, (
            "the 503 is raised before or instead of the wait, which is the defect"
        )

    def test_the_timeout_exceeds_the_slowest_observed_build(self):
        """Measured: India models take 10-27s to serve.

        A wait shorter than the slowest build turns ordinary contention into a
        failure, so the failure rate rises with model slowness -- backwards.
        """
        assert routes.SINGLE_FLIGHT_WAIT_SECONDS >= 30.0, (
            "the wait is %ss, below the slowest observed build (27s for an India "
            "model fetching a live price). Contention on the slowest models would "
            "still be reported as failures." % routes.SINGLE_FLIGHT_WAIT_SECONDS
        )

    def test_the_wait_is_configurable_at_module_level(self):
        src = inspect.getsource(routes)
        assert re.search(r"SINGLE_FLIGHT_WAIT_SECONDS\s*=\s*[\d.]+", src), (
            "the wait is no longer a named module constant, so the message cannot "
            "quote the same number the request used"
        )


class TestTheDuplicateIsStillAvoided:
    """Waiting must not quietly become "everyone builds it".

    A gate that fixes the 503 by removing the guard would trade a visible error for
    eleven simultaneous SEC ingests, which is the failure this project has spent a
    session removing.
    """

    def test_single_flight_still_excludes_a_concurrent_builder(self):
        throttle.reset_for_tests()
        cid = "exclusion_probe_us"
        with throttle.single_flight(cid):
            winners = []
            for _ in range(3):
                with throttle.single_flight(cid) as first:
                    winners.append(first)
        assert winners == [False, False, False], (
            "a second builder was admitted while one was in flight: %r" % winners
        )

    def test_exactly_one_caller_builds(self):
        throttle.reset_for_tests()
        cid = "one_probe_us"
        results = []
        lock = threading.Lock()

        def contend():
            with throttle.single_flight(cid) as first:
                with lock:
                    results.append(first)
                time.sleep(0.05)

        threads = [threading.Thread(target=contend) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert results.count(True) == 1, (
            "expected exactly one builder, got %d: %r" % (results.count(True), results)
        )