"""A ticker with no financials behind it is not a broken service.

The engine is meant to cover every listed ticker, which means it will meet many it
cannot yet value: a foreign ordinary with no filing in reach, a recent listing
with no annual report, a delisted symbol still in the index. Those are ordinary
outcomes and they are worth their own answer.

Answered as 500, a screen full of such tickers looked identical to a broken
service, and the stack traces that would have explained the real faults were
buried among them. Seven of fifty randomly drawn tickers returned 500 in one run,
all of them for this reason and none of them a defect.

A 500 must mean something now: it means the build broke.
"""

import pytest
from fastapi import HTTPException

from backend.api import routes
from backend.data import batch as batch_module
from backend.data.errors import NoFinancialsAvailable


class TestNoFinancialsIsNotAFault:
    def test_it_is_not_a_value_error(self):
        # It was an ordinary ValueError, so the route's broad handler re-raised it
        # as a 500. A caller that cannot tell the two cases apart cannot act on
        # either one.
        assert not issubclass(NoFinancialsAvailable, ValueError)

    def test_the_route_answers_it_as_temporary(self, tmp_path, monkeypatch):
        # Drive the real route handler and assert the response a user would get.
        monkeypatch.setattr(
            routes, "ensure_company_ingested",
            lambda *a, **k: (_ for _ in ()).throw(
                NoFinancialsAvailable("no statements behind this ticker")
            ),
        )
        monkeypatch.setattr(routes.ingest_throttle, "mark_failure", lambda *a, **k: None)
        monkeypatch.setattr(routes.ingest_throttle, "ingest_slot", _always_grant_slot)

        with pytest.raises(HTTPException) as caught:
            routes._build_spec_locked("ticker_us", tmp_path / "none.json", False)

        assert caught.value.status_code == 503
        assert "no financial statements could be sourced" in caught.value.detail.lower()

    def test_a_real_fault_still_answers_500(self, tmp_path, monkeypatch):
        # The other half of the guarantee: this change must not have turned
        # genuine faults into a polite retry. If it did, a real bug would be
        # reported to the user as "try again shortly" and never investigated.
        monkeypatch.setattr(
            routes, "ensure_company_ingested",
            lambda *a, **k: (_ for _ in ()).throw(ZeroDivisionError("a real bug")),
        )
        monkeypatch.setattr(routes.ingest_throttle, "mark_failure", lambda *a, **k: None)
        monkeypatch.setattr(routes.ingest_throttle, "ingest_slot", _always_grant_slot)

        with pytest.raises(ZeroDivisionError):
            routes._build_spec_locked("ticker_us", tmp_path / "none.json", False)

    def test_the_local_export_still_works_when_live_providers_fail(self, tmp_path, monkeypatch):
        # The regression this file guards against. A local source export is the
        # last-resort path for a transient outage at every live provider, which is
        # exactly when it matters. An earlier version of this change replaced the
        # call with a raise, and several companies that ship an export became
        # unavailable whenever the providers were down.
        from backend.data import batch

        export = tmp_path / "fictional_us.xlsx"
        export.write_bytes(b"not really a workbook")

        monkeypatch.setattr(
            batch, "_source_file_for", lambda cid: export
        )
        monkeypatch.setattr(
            "backend.data.ingestion.sec_edgar.fetch_and_parse_sec_edgar",
            _raises(NoFinancialsAvailable("SEC EDGAR returned nothing")),
        )
        monkeypatch.setattr(
            "backend.data.ingestion.us_live.fetch_and_parse_us_live",
            _raises(NoFinancialsAvailable("yfinance returned nothing")),
        )
        captured = {}

        def _capture(src, company_id):
            captured["file"] = src
            return ["datapoint"]

        monkeypatch.setattr(
            "backend.data.ingestion.sec_edgar.parse_sec_edgar_export", _capture
        )
        # These are imported inside the function, so they are patched where they
        # are defined rather than on the module that calls them.
        monkeypatch.setattr("backend.data.store.save_datapoints", lambda *a, **k: None)
        monkeypatch.setattr("backend.data.store.query_canonical_datapoints", lambda *a, **k: [])
        monkeypatch.setattr("backend.normalization.pipeline.run", lambda *a, **k: None)
        monkeypatch.setattr(batch, "_supplement_missing_lines", lambda *a, **k: None)

        batch.ensure_company_ingested("fictional_us", db_path=tmp_path / "db.sqlite")

        assert captured.get("file") == export, "the local export was never read"

    def test_a_bug_in_the_ingestion_is_not_reported_as_a_missing_ticker(
        self, tmp_path, monkeypatch
    ):
        # The guarantee that is easy to lose. The provider chain falls through on
        # the typed error, so a shape the parser did not expect must NOT be
        # mistaken for an outage: caught broadly, it walks to the end of the
        # chain, finds no export, tells the user to retry, and gets the company
        # negatively cached. The bug is then invisible.
        #
        # The condition is not rare in the way it looks. A provider being down and
        # a parser meeting a shape it did not expect both arrive as an exception,
        # and only one of them is the engine's fault.
        class Boom(Exception):
            pass

        monkeypatch.setattr(
            "backend.data.ingestion.sec_edgar.fetch_and_parse_sec_edgar",
            _raises(Boom("a shape the parser did not expect")),
        )
        monkeypatch.setattr(
            "backend.data.ingestion.us_live.fetch_and_parse_us_live",
            _raises(Boom("the same fault on the other provider")),
        )
        monkeypatch.setattr(
            "backend.data.store.query_canonical_datapoints", lambda *a, **k: []
        )

        with pytest.raises(Boom):
            batch_module.ensure_company_ingested(
                "fictional_us", db_path=tmp_path / "db.sqlite"
            )

    def test_the_reason_survives_to_the_log(self, tmp_path, monkeypatch):
        # The message has to survive, otherwise "why is this ticker not
        # available" is unanswerable from the outside.
        def _raise_nothing(cid):
            raise NoFinancialsAvailable("no statements behind this ticker")

        monkeypatch.setattr(batch_module, "_source_file_for", _raise_nothing)
        monkeypatch.setattr(
            "backend.data.ingestion.sec_edgar.fetch_and_parse_sec_edgar",
            _raises(NoFinancialsAvailable("SEC has nothing")),
        )
        monkeypatch.setattr(
            "backend.data.ingestion.us_live.fetch_and_parse_us_live",
            _raises(NoFinancialsAvailable("yfinance has nothing")),
        )
        monkeypatch.setattr("backend.data.store.query_canonical_datapoints", lambda *a, **k: [])

        with pytest.raises(NoFinancialsAvailable) as caught:
            batch_module.ensure_company_ingested(
                "fictional_us", db_path=tmp_path / "db.sqlite"
            )
        assert "no statements behind this ticker" in str(caught.value)


def _raises(exc):
    """A replacement that always fails, to simulate a provider outage."""

    def _boom(*_a, **_k):
        raise exc

    return _boom


def _always_grant_slot(*_a, **_k):
    """A context manager that grants the ingest slot, so no global throttle state
    is touched and the test is order-independent."""

    class _Granted:
        def __enter__(self):
            return True

        def __exit__(self, *_exc):
            return False

    return _Granted()
