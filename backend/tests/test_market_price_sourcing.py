"""Market-price sourcing: live free quotes, honest staleness, no hardcoded prices.

Regression cover for the NVDA bug where the UI showed "$100.00 as of
2026-09-26" next to a real ~$225 quote: yfinance's .info came back empty, the
fallback chain landed on the generic $100 US market default, and the UI
stamped it with today's date. These tests pin the corrected behaviour:

  - no price may be hardcoded in the registry,
  - a price must come from a live free source when one is reachable,
  - when every live source fails, the last-known-good cached quote is served
    with its ORIGINAL fetch_date and a stale_cache:* source,
  - the generic placeholder is last-resort only and is never persisted.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from backend.data.providers import market_data as md

LIVE_SOURCES = {"yfinance", "yfinance_history", "yahoo_chart", "twelvedata"}
FALLBACK_SOURCES = {"registry", "market_default"}


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Redirect the on-disk quote cache to a temp file and blank the fetchers."""
    cache_file = tmp_path / "market_data_cache.json"
    monkeypatch.setattr(md, "CACHE_FILE", cache_file)
    monkeypatch.setattr(md, "_fetch_yfinance", lambda *a, **k: {})
    monkeypatch.setattr(md, "_fetch_yfinance_history", lambda *a, **k: {})
    monkeypatch.setattr(md, "_fetch_yahoo_chart", lambda *a, **k: {})
    monkeypatch.setattr(md, "_fetch_twelvedata", lambda *a, **k: {})
    return cache_file


def _write_cache(cache_file, company_id, value, source, fetch_date):
    cache_file.write_text(
        json.dumps(
            {
                company_id: {
                    "fetch_date": fetch_date,
                    "data": {
                        "company_id": company_id,
                        "ticker": company_id.split("_")[0].upper(),
                        "market": "us",
                        "price": {
                            "value": value,
                            "source": source,
                            "fetch_date": fetch_date,
                            "provenance_note": "cached",
                        },
                        "shares_outstanding": {
                            "value": 1000.0,
                            "source": source,
                            "fetch_date": fetch_date,
                            "provenance_note": "cached",
                        },
                        "beta": {
                            "value": 1.0,
                            "source": source,
                            "fetch_date": fetch_date,
                            "provenance_note": "cached",
                        },
                        "risk_free_rate": {
                            "value": 4.6,
                            "source": source,
                            "fetch_date": fetch_date,
                            "provenance_note": "cached",
                        },
                        "equity_risk_premium": {
                            "value": 4.5,
                            "source": source,
                            "fetch_date": fetch_date,
                            "provenance_note": "cached",
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def test_registry_stores_no_prices():
    """Structural registry carries shares/beta only — price is a daily quote."""
    offenders = [cid for cid, entry in md.REGISTRY_FALLBACKS.items() if "price" in entry]
    assert offenders == [], f"hardcoded prices found in registry: {offenders}"


def test_retired_ticker_falls_through_to_its_successor(isolated_cache):
    """A demerger must not pin a model to a months-old price forever."""
    _write_cache(isolated_cache, "tatamotors_tatamotors", 480.0, "registry", "2026-08-23")
    monkey = md.requests
    original_get = monkey.get
    monkey.get = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network"))
    try:
        # Primary TATAMOTORS.NS resolves to nothing; TMPV.NS answers.
        md._fetch_yfinance_history = lambda cid, m, tkr: (
            {"price": md.MarketDataPoint(
                value=290.45, source="yfinance_history", fetch_date="2026-09-25",
                provenance_note="yfinance daily close for TMPV.NS",
            )} if tkr.upper().startswith("TMPV") else {}
        )
        md._fetch_yahoo_chart = lambda *a, **k: {}
        md._fetch_yfinance = lambda *a, **k: {}
        cmd = md.get_company_market_data("tatamotors_tatamotors", force_refresh=True)
    finally:
        monkey.get = original_get

    assert cmd.price.value == pytest.approx(290.45)
    # Tagged so the UI suppresses the vs-market %, which would otherwise compare
    # a successor entity's price against pre-action financials.
    assert cmd.price.source == "yfinance_history:successor_ticker"
    assert cmd.price.fetch_date == "2026-09-25"
    assert "successor entity" in cmd.price.provenance_note


def test_quote_date_is_the_bar_date_not_today():
    """A Friday close must never be stamped with a weekend request date."""
    friday = datetime(2026, 9, 25, 16, 0, tzinfo=timezone.utc).timestamp()
    pt = md._last_close_point("NVDA", [None, 224.58, 225.07], [0, 0, friday])
    assert pt is not None
    assert pt.value == pytest.approx(225.07)
    assert pt.fetch_date == "2026-09-25"
    assert pt.source == "yfinance_history"
    # A datapoint with no usable bar date falls back to today, not to a guess.
    undated = md._last_close_point("NVDA", [225.07], [])
    assert undated is not None and undated.fetch_date == date.today().isoformat()
    # Nothing usable -> no datapoint at all (chain moves on to the next source).
    assert md._last_close_point("NVDA", [None, 0, -1], [0, 1, 2]) is None


def test_yahoo_chart_is_an_independent_price_path():
    """The chain must not depend on the yfinance wrapper alone."""
    calls = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "chart": {
                    "result": [
                        {
                            "timestamp": [1787788800],
                            "indicators": {"quote": [{"close": [225.07]}]},
                        }
                    ]
                }
            }

    def _fake_get(url, **kwargs):
        calls.append(url)
        return _Resp()

    monkey = md.requests
    original_get = monkey.get
    monkey.get = _fake_get
    try:
        out = md._fetch_yahoo_chart("nvda_us", "us", "NVDA")
    finally:
        monkey.get = original_get

    assert out["price"].value == pytest.approx(225.07)
    assert out["price"].source == "yahoo_chart"
    assert any("finance/chart/NVDA" in c for c in calls)


def test_live_source_wins_over_cache(monkeypatch, isolated_cache):
    """A reachable free source always beats a same-day cached quote."""
    _write_cache(isolated_cache, "nvda_us", 1.0, "yfinance", date.today().isoformat())
    monkeypatch.setattr(
        md,
        "_fetch_yfinance_history",
        lambda *a, **k: {
            "price": md.MarketDataPoint(
                value=225.07,
                source="yfinance_history",
                fetch_date=date.today().isoformat(),
                provenance_note="yfinance daily close for NVDA",
            )
        },
    )
    cmd = md.get_company_market_data("nvda_us", force_refresh=True)
    assert cmd.price.value == pytest.approx(225.07)
    assert cmd.price.source in LIVE_SOURCES


def test_outage_serves_stale_cache_with_original_date(isolated_cache):
    """Total live outage -> last-known-good quote, original date, stale source."""
    _write_cache(isolated_cache, "nvda_us", 225.07, "yfinance", "2026-09-26")
    cmd = md.get_company_market_data("nvda_us", force_refresh=True)
    assert cmd.price.value == pytest.approx(225.07)
    assert cmd.price.source == "stale_cache:yfinance"
    assert cmd.price.fetch_date == "2026-09-26", "stale quote must not claim today's date"
    assert "stale" in cmd.price.provenance_note.lower()


def test_placeholder_is_last_resort_and_never_persisted(isolated_cache):
    """No live source and no cache -> $100 placeholder, and it is not written back."""
    cmd = md.get_company_market_data("nvda_us", force_refresh=True)
    assert cmd.price.value == pytest.approx(md.MARKET_DEFAULTS["us"]["price"])
    assert cmd.price.source == "market_default"
    assert not isolated_cache.exists(), "the $100 placeholder must never be cached"


def test_source_provenance_survives_into_valuation_output():
    """market_price_source is exposed so the UI can label Live/Stale/Benchmark."""
    spec_model = md.CompanyMarketData
    assert "price" in spec_model.model_fields
    from backend.models.spec.valuation import ReverseDCF

    assert "market_price_source" in ReverseDCF.model_fields
    rd = ReverseDCF(market_price=225.07, market_price_source="stale_cache:yfinance")
    assert rd.model_dump()["market_price_source"] == "stale_cache:yfinance"


def test_live_source_names_are_shared_with_frontend():
    """Keep backend/frontend source vocabularies in sync (see KPIBar/QuickDCFView)."""
    for frontend in (
        "frontend/src/components/KPIBar.tsx",
        "frontend/src/components/QuickDCFView.tsx",
    ):
        text = (md.Path(__file__).resolve().parents[2] / frontend).read_text(encoding="utf-8")
        for source in LIVE_SOURCES:
            assert f"'{source}'" in text, f"{frontend} does not recognise live source '{source}'"
        assert "'stale_cache'" in text, f"{frontend} does not recognise stale quotes"
        assert "successor_ticker" in text, f"{frontend} does not recognise successor-ticker quotes"
    for source in FALLBACK_SOURCES:
        assert f"'{source}'" in (md.Path(__file__).resolve().parents[2]
                                 / "frontend/src/components/KPIBar.tsx").read_text(encoding="utf-8")
