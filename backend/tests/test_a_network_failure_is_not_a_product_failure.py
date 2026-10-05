"""A network failure must be reported as a network failure.

Two gates check a claim against a filer that is LIVE, and both were reading
``data.sec.gov`` directly. That made an HTTP timeout, a 429, or a reset
connection surface as a FAILED TEST -- indistinguishable from a defect in the
engine.

This is not hypothetical. ``test_a_company_tagging_only_the_including_variant_is_readable``
passed alone, passed as its own file, failed inside a 324-test run, and passed
again on an identical rerun of the same 324 tests. An intermittent gate cannot be
trusted to catch anything: a red build from it teaches the team to ignore red
builds, and then a real red build goes unread.

The ``network`` marker was already registered in ``pyproject.toml`` with the
description "fails when the network is unavailable", which describes the old
behaviour as though it were intended. Nothing honoured it -- CI runs
``pytest backend/tests -q`` with no ``-m`` filter.

These tests assert the skip actually happens, by making the request fail. Without
them the fix is a claim in a docstring.
"""

from __future__ import annotations

import contextlib
import gzip
import io
import urllib.error
import urllib.request

import pytest


def _fail_with(exc: BaseException):
    """Make every urlopen raise, the way an outage or a rate limit would."""

    def _raise(request, timeout=None):
        raise exc

    return _raise


def _respond(body: bytes):
    """Stand in for urlopen's response.

    ``urlopen`` returns a file-like object with ``.read()``, not the bytes
    themselves. Returning raw bytes from a double makes the code under test raise
    ``AttributeError`` -- which is a true statement about the double and no
    statement at all about the behaviour being checked.
    """

    def _open(request, timeout=None):
        return io.BytesIO(body)

    return _open


@contextlib.contextmanager
def network_is_up():
    """Turn any skip inside into a FAILURE.

    Skipping is correct when EDGAR is genuinely unreachable. These tests supply
    their own working response, so a skip here means the code refused to read a
    body it was handed -- and a skip reports as a pass, which would let the very
    bug this suite exists to catch go green.

    This hole was found by the mutation harness rather than by reading the tests:
    deleting the gzip branch makes ``json.loads`` fail on the compressed bytes,
    the helper skips as designed, and the test that exists to prove decompression
    works reports as SKIPPED rather than failed. Seven of eight mutations were
    caught; that one was not, and the reason was a skip counted as a pass.
    """
    try:
        yield
    except pytest.skip.Exception as exc:
        pytest.fail(
            f"the network is up in this test, so a skip means the reader refused a "
            f"response it was handed, not that EDGAR is down: {exc}"
        )


class TestANetworkFailureIsNotAProductFailure:
    def test_a_rate_limit_skips_rather_than_fails(self, monkeypatch):
        """429 is EDGAR refusing a shared client identity, not a wrong tag.

        This is the case that most looks like a product failure: the request
        succeeded in reaching EDGAR and was then refused, which is exactly what a
        rate limit looks like from inside the test.
        """
        from backend.tests import conftest

        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            _fail_with(
                urllib.error.HTTPError(
                    "https://data.sec.gov/x", 429, "Too Many Requests", {}, None
                )
            ),
        )

        with pytest.raises(pytest.skip.Exception) as skipped:
            conftest.fetch_company_facts(1712184)

        assert "429" in str(skipped.value), (
            "the skip must name what EDGAR answered, so a reader can tell a rate "
            f"limit from a genuine mismatch. Got: {skipped.value}"
        )

    def test_a_forbidden_skips_rather_than_fails(self, monkeypatch):
        """403 is the other refusal EDGAR returns for an unacceptable client."""
        from backend.tests import conftest

        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            _fail_with(
                urllib.error.HTTPError(
                    "https://data.sec.gov/x", 403, "Forbidden", {}, None
                )
            ),
        )

        with pytest.raises(pytest.skip.Exception):
            conftest.fetch_company_facts(1712184)

    def test_an_unreachable_host_skips_rather_than_fails(self, monkeypatch):
        """A DNS failure or a dropped connection is the same class of noise."""
        from backend.tests import conftest

        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            _fail_with(urllib.error.URLError("[Errno -2] Name or service not known")),
        )

        with pytest.raises(pytest.skip.Exception) as skipped:
            conftest.fetch_company_facts(1712184)

        assert "network" in str(skipped.value), (
            "the skip must say the network is at fault, because that is what "
            f"distinguishes it from a real failure. Got: {skipped.value}"
        )

    def test_a_timeout_skips_rather_than_fails(self, monkeypatch):
        from backend.tests import conftest

        monkeypatch.setattr(urllib.request, "urlopen", _fail_with(TimeoutError("timed out")))

        with pytest.raises(pytest.skip.Exception):
            conftest.fetch_company_facts(1712184)

    def test_a_truncated_body_skips_rather_than_fails(self, monkeypatch):
        """Half a response is uninformative about the tag, so it is not a verdict.

        A body that does not parse must not be treated as "the tag is absent",
        which is the failure mode this project refuses everywhere else: a broken
        fetch must never be reported as a complete answer.
        """
        from backend.tests import conftest

        monkeypatch.setattr(
            urllib.request, "urlopen", _respond(b'{"facts": {"us-gaap"')
        )

        with pytest.raises(pytest.skip.Exception) as skipped:
            conftest.fetch_company_facts(1712184)

        assert "did not parse" in str(skipped.value), (
            f"the skip must say the response was malformed. Got: {skipped.value}"
        )

    def test_a_body_that_is_not_an_object_skips_rather_than_fails(self, monkeypatch):
        """EDGAR returning a list where an object was expected is not a verdict."""
        from backend.tests import conftest

        monkeypatch.setattr(
            urllib.request, "urlopen", _respond(b"[1, 2, 3]")
        )

        with pytest.raises(pytest.skip.Exception) as skipped:
            conftest.fetch_company_facts(1712184)

        assert "rather than an object" in str(skipped.value), (
            f"the skip must name the shape that arrived. Got: {skipped.value}"
        )


class TestTheHappyPathStillWorks:
    """A fix to the failure path must not break the success path."""

    def test_a_gzipped_object_is_returned_and_decompressed(self, monkeypatch):
        from backend.tests import conftest

        body = gzip.compress(b'{"facts": {"us-gaap": {"Revenues": {}}}, "cik": 1712184}')
        monkeypatch.setattr(urllib.request, "urlopen", _respond(body))

        with network_is_up():
            facts = conftest.fetch_company_facts(1712184)

        assert "Revenues" in facts["facts"]["us-gaap"], (
            "the gzip path broke, so the live tests would skip on a working "
            "network and nobody would notice the check had stopped running"
        )

    def test_an_uncompressed_object_is_returned_as_is(self, monkeypatch):
        from backend.tests import conftest

        monkeypatch.setattr(
            urllib.request, "urlopen", _respond(b'{"name": "Liberty"}')
        )

        with network_is_up():
            submissions = conftest.fetch_sec_json(
                "https://data.sec.gov/submissions/CIK1.json", what="a filer"
            )

        assert submissions["name"] == "Liberty"

    def test_the_request_identifies_itself_to_edgar(self, monkeypatch):
        """EDGAR requires a User-Agent and refuses requests without one.

        A 403 for a missing User-Agent would be reported as a network problem by
        the skip, which would be the helper quietly hiding its own mistake. So the
        header is asserted rather than assumed.
        """
        from backend.tests import conftest

        seen: list[urllib.request.Request] = []

        def _record(request, timeout=None):
            seen.append(request)
            return io.BytesIO(b"{}")

        monkeypatch.setattr(urllib.request, "urlopen", _record)

        with network_is_up():
            conftest.fetch_company_facts(1712184)

        assert seen, "no request was made, so the header was never checked"
        agent = seen[0].get_header("User-agent")
        assert agent and "Valence" in agent, (
            f"EDGAR is asked to identify the client and this sends {agent!r}. A 403 "
            "here would be indistinguishable from a rate limit."
        )
        assert seen[0].get_header("Accept-encoding") == "gzip", (
            "the body is read as gzip, so the header has to ask for it"
        )

    def test_the_cik_is_zero_padded_to_ten_digits(self, monkeypatch):
        """A short CIK produces a URL EDGAR 404s on, which would look like a skip."""
        from backend.tests import conftest

        seen: list[str] = []

        def _record(request, timeout=None):
            seen.append(request.full_url)
            return io.BytesIO(b"{}")

        monkeypatch.setattr(urllib.request, "urlopen", _record)

        with network_is_up():
            conftest.fetch_company_facts(1712184)

        assert "CIK0001712184.json" in seen[0], (
            f"the CIK was not zero-padded: {seen[0]}"
        )