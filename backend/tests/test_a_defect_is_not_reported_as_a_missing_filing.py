"""A defect in this codebase must not be reported to a visitor as a fact about a company.

`mark_failure` used to take only a company_id and was called from a bare
`except Exception` wrapped around the whole ingest-and-compile in `_build_spec_locked`.
Every later request for that ticker, for NEGATIVE_CACHE_TTL seconds, was answered with the
ABSENCE message:

    503 "No financial statements could be sourced for this ticker yet. Try again shortly."

and the frontend renders a 503 as, in the visitor's words:

    INFY: the filings behind this company could not be reached. The company does file, so
    this is most likely a temporary failure to reach them.

So a TypeError in the forecast engine produced a confident, repeated, false statement about a
real listed company's filings, and each retry re-asserted it for five minutes. That is the
mechanism this project keeps refusing: inferring the cause from the class of failure rather
than from evidence for it, and then repeating the inference to everyone who asks.

Two things with different causes now get two different answers, and the distinction is
carried in the cache entry rather than in the wording of one message.

Driven through `_build_spec_locked`, which is where the handler lives, with the ingest slot
granted so no global throttle state is touched and the test stays order-independent.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.api import routes, throttle
from backend.data.errors import NoFinancialsAvailable

COMPANY = "probe_us"


def _grant_slot(*_a, **_k):
    class _Granted:
        def __enter__(self):
            return True

        def __exit__(self, *_exc):
            return False

    return _Granted()


def _raises(exc):
    def _boom(*_a, **_k):
        raise exc

    return _boom


@pytest.fixture(autouse=True)
def _clean():
    throttle.clear_failure(COMPANY)
    yield
    throttle.clear_failure(COMPANY)


def test_a_build_defect_is_not_cached_as_an_absence(tmp_path, monkeypatch):
    """The defect case, which is the one this change is about."""
    monkeypatch.setattr(routes.ingest_throttle, "ingest_slot", _grant_slot)
    monkeypatch.setattr(
        routes, "ensure_company_ingested",
        _raises(RuntimeError("a bug in the forecast engine")),
    )

    with pytest.raises(RuntimeError):
        routes._build_spec_locked(COMPANY, tmp_path / "none.json", False)

    assert throttle.is_negative(COMPANY) is False, (
        "a defect in this codebase was cached as an ingestion failure. Every request for "
        "the next five minutes is then answered with a statement about the company's "
        "filings that nothing supports, and each retry re-asserts it."
    )


def test_a_build_defect_is_not_converted_into_a_polite_retry(tmp_path, monkeypatch):
    """It must also still surface as itself, or a real bug is never investigated.

    The other half of the guarantee. Reporting a defect as "try again shortly" would be
    better than lying about the company, and still wrong.
    """
    monkeypatch.setattr(routes.ingest_throttle, "ingest_slot", _grant_slot)
    monkeypatch.setattr(
        routes, "ensure_company_ingested",
        _raises(ZeroDivisionError("a real bug")),
    )

    with pytest.raises(ZeroDivisionError):
        routes._build_spec_locked(COMPANY, tmp_path / "none.json", False)


def test_a_genuine_absence_is_still_cached(tmp_path, monkeypatch):
    """The other direction, because a check that only knows one branch is not a check.

    Removing the write would re-attempt the providers on every request forever, which is
    what the bookkeeping was added to prevent.
    """
    monkeypatch.setattr(routes.ingest_throttle, "ingest_slot", _grant_slot)
    monkeypatch.setattr(
        routes, "ensure_company_ingested",
        _raises(NoFinancialsAvailable("no statements behind this ticker")),
    )

    with pytest.raises(HTTPException) as caught:
        routes._build_spec_locked(COMPANY, tmp_path / "none.json", False)

    assert caught.value.status_code == 503
    assert throttle.is_negative(COMPANY) is True, (
        "a ticker with nothing behind it is not recorded, so a crawler re-attempts the "
        "providers forever"
    )
    assert throttle.failure_kind(COMPANY) == throttle.ABSENT


def test_the_two_failures_are_answered_differently(tmp_path, monkeypatch):
    """Same status code, different claim, because they are different facts."""
    monkeypatch.setattr(routes.ingest_throttle, "ingest_slot", _grant_slot)
    monkeypatch.setattr(
        routes, "ensure_company_ingested",
        _raises(NoFinancialsAvailable("nothing")),
    )
    with pytest.raises(HTTPException) as caught:
        routes._build_spec_locked(COMPANY, tmp_path / "none.json", False)
    absence = caught.value.detail

    throttle.clear_failure(COMPANY)
    throttle.mark_failure(COMPANY, throttle.UPSTREAM)
    # No force_retry: it clears the negative cache first, which is correct behaviour for an
    # operator but takes this request down the ingestion branch and answers with the
    # absence message again. The first version of this test did exactly that and compared
    # two copies of the same string, which agreed.
    with pytest.raises(HTTPException) as caught:
        routes._get_or_build_spec(COMPANY)
    upstream = caught.value.detail

    assert absence != upstream, (
        "an absent filing and an unreachable provider are answered identically, and the "
        "frontend turns that answer into a claim about the company rather than about us"
    )
    assert "sourced" in absence.lower()
    assert "reached" in upstream.lower()


def test_an_unknown_failure_kind_is_refused():
    """A typo must not silently become an absence, which is what it would default to."""
    with pytest.raises(ValueError):
        throttle.mark_failure(COMPANY, "provider_was_being_rude")
