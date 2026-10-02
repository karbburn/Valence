"""A CIK must be checked against the filer it claims to identify.

The engine resolved a company's SEC identifier from a hand-kept table and returned
it without a check. One entry was wrong: `infy_us` held 0001065280, which is
NETFLIX. So the page titled "Infosys Limited (NYSE ADR)", served under the ticker
INFY, was built from Netflix's 10-K. Revenue 45,183, total assets 55,597, cash
9,033.7 and equity 26,616 are Netflix's FY2025 figures, the enterprise bridge was
Netflix's, and the page published an implied share price of $63.25 against a market
price of $10.64.

Nothing downstream could catch it. The statements footed, EBITDA was above EBIT,
net debt reconciled to its own components, the workbook agreed with the model, the
QA gate had no regression, and the tie-out called the filer "not auditable because
it reports under IFRS" — a true statement about the taxonomy that read as though
the numbers had been left alone. Every check asks whether a figure is consistent;
none of them asks whether it is the right company's.

The registry is therefore a fallback for SEC being unreachable, not an authority.
These tests hold that ordering in place, and they check the shipped identifiers
against EDGAR so a wrong one cannot sit in the table unnoticed between runs.
"""

from __future__ import annotations

import json

import pytest

from backend.data.errors import NoFinancialsAvailable
from backend.data.ingestion import sec_edgar
from backend.data.ingestion.sec_edgar import CIK_REGISTRY, resolve_cik

# The identifiers the shipped models depend on, and the filer each one must be.
# Checked against EDGAR below; this table is what makes the failure legible.
EXPECTED_FILER = {
    "aapl_us": "Apple Inc.",
    "msft_us": "Microsoft Corp",
    "infy_us": "Infosys Ltd",
}


def _same_filer(filed: str, expected: str) -> bool:
    """EDGAR carries registrants under whichever legal form they last used.

    Microsoft's own name at EDGAR is the all-caps MICROSOFT CORP its charter was
    filed under, and Infosys changed from INFOSYS TECHNOLOGIES LTD in 2011. So the
    comparison is on the words, not the casing or the suffix.
    """
    def words(s: str) -> set[str]:
        return {w for w in "".join(c if c.isalnum() else " " for c in s.upper()).split()}

    filed_words, expected_words = words(filed), words(expected)
    # "Ltd", "Limited", "Corp", "Corporation", "Inc" and "Co" are the same word
    # written four ways; comparing them as distinct tokens would make this test
    # fail for a spelling and pass for a wrong company.
    for noise in ("LTD", "LIMITED", "CORP", "CORPORATION", "INC", "CO", "COMPANY", "PLC", "SA", "NV"):
        filed_words.discard(noise)
        expected_words.discard(noise)
    return filed_words == expected_words and bool(filed_words)


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _sec_payload(**overrides):
    """A ticker file shaped like SEC's, with Netflix under the wrong CIK."""
    entries = {
        "AAPL": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."},
        "MSFT": {"ticker": "MSFT", "cik_str": 789019, "title": "Microsoft Corp"},
        "INFY": {"ticker": "INFY", "cik_str": 1067491, "title": "Infosys Ltd"},
        "NFLX": {"ticker": "NFLX", "cik_str": 1065280, "title": "Netflix Inc."},
    }
    entries.update(overrides)
    return entries


def _stub_sec(monkeypatch, payload=None, status=200, raises=False):
    calls = {"n": 0}

    def _get(url, **kwargs):
        calls["n"] += 1
        if raises:
            raise OSError("network unreachable")
        return _Response(payload if payload is not None else _sec_payload(), status)

    monkeypatch.setattr(sec_edgar.requests, "get", _get)
    return calls


class TestSecDecidesTheIdentifier:
    def test_resolves_from_the_ticker_file(self, monkeypatch):
        _stub_sec(monkeypatch)
        assert resolve_cik("infy_us") == "0001067491"

    def test_a_wrong_registry_entry_never_wins(self, monkeypatch):
        """The exact defect: the table says Netflix, SEC says Infosys, SEC wins."""
        monkeypatch.setitem(CIK_REGISTRY, "infy_us", "0001065280")
        _stub_sec(monkeypatch)
        assert resolve_cik("infy_us") == "0001067491"

    def test_a_stale_entry_is_reported_rather_than_used(self, monkeypatch, caplog):
        monkeypatch.setitem(CIK_REGISTRY, "infy_us", "0001065280")
        _stub_sec(monkeypatch)
        with caplog.at_level("WARNING"):
            resolve_cik("infy_us")
        assert any("0001065280" in r.message for r in caplog.records), (
            "a registry entry that disagrees with SEC must be reported, because "
            "that is the only signal that the identifier was ever wrong"
        )

    def test_sec_is_asked_on_every_call_not_only_on_a_miss(self, monkeypatch):
        """A table consulted first is a table that is never checked.

        If the registry short-circuited, the request count would be zero for a
        company the table already contains, and the wrong-identifier class would be
        back with nothing to catch it.
        """
        calls = _stub_sec(monkeypatch)
        resolve_cik("aapl_us")
        assert calls["n"] == 1


class TestTheFallbackIsNotSilent:
    def test_registry_is_used_only_when_sec_is_unreachable(self, monkeypatch):
        _stub_sec(monkeypatch, raises=True)
        assert resolve_cik("aapl_us") == CIK_REGISTRY["aapl_us"]

    def test_a_fallback_hit_is_logged_as_unverified(self, monkeypatch, caplog):
        _stub_sec(monkeypatch, raises=True)
        with caplog.at_level("WARNING"):
            resolve_cik("infy_us")
        assert any("unverified" in r.message for r in caplog.records), (
            "an identifier that has not been checked against the filer must say so"
        )

    def test_unknown_ticker_raises_rather_than_guessing(self, monkeypatch):
        _stub_sec(monkeypatch)
        # NoFinancialsAvailable, not ValueError.
        #
        # A ticker absent from SEC's own file is a listed company with no filing in
        # reach -- the "not available" case that the API answers 503, and the one
        # `backend/data/errors.py` exists to keep distinct from a broken build.
        # As a bare ValueError it became a 500 "Failed to build model. See server
        # logs": a fabricated fault, for a company that simply files nothing.
        #
        # The point of this test is unchanged and still holds: nothing is guessed.
        with pytest.raises(NoFinancialsAvailable):
            resolve_cik("nosuch_us")

    def test_an_unknown_ticker_still_refuses_to_guess(self, monkeypatch):
        """The behaviour the original test guarded, stated in its own terms.

        `resolve_cik` must never return an identifier it has not verified. Raising
        a different exception type does not make this easier to satisfy by accident,
        so it is asserted directly rather than as a side effect of the raise.
        """
        _stub_sec(monkeypatch)
        try:
            resolved = resolve_cik("nosuch_us")
        except NoFinancialsAvailable:
            return
        pytest.fail(
            "resolve_cik returned %r for a ticker SEC does not list; falling back "
            "to another company's CIK would read the wrong filer's financials"
            % (resolved,)
        )


@pytest.mark.network
class TestShippedIdentifiersMatchTheirFilers:
    """Checked against EDGAR, because this is the check that would have caught it."""

    def test_every_registry_entry_is_the_filer_it_claims(self):
        import gzip
        import urllib.request

        for company_id, expected_name in EXPECTED_FILER.items():
            cik = CIK_REGISTRY[company_id]
            req = urllib.request.Request(
                f"https://data.sec.gov/submissions/CIK{cik}.json",
                headers={"User-Agent": "Valence valuation research team@valence.com",
                         "Accept-Encoding": "gzip"},
            )
            raw = urllib.request.urlopen(req, timeout=60).read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            name = json.loads(raw).get("name")
            assert _same_filer(name or "", expected_name), (
                f"CIK_REGISTRY['{company_id}'] is {cik}, which is {name!r}, not "
                f"{expected_name!r}. Every figure this engine publishes for that "
                f"company is currently the other filer's."
            )
