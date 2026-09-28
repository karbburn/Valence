"""The /companies/resolve allowlist, which is the security boundary for /stock.

An unrecognised slug must never reach /api/model/{company_id}. That endpoint
accepts any pattern-valid company_id and will attempt live third-party ingestion
for it, so a public page route that passed unknown segments straight through
would let any well-formed URL on the internet start an ingestion.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.data.universe.master_list import seed_master_universe
from backend.data.universe.store import assign_slugs_to_universe, get_universe_by_slug


@pytest.fixture(scope="module", autouse=True)
def _seeded_universe():
    seed_master_universe()
    assign_slugs_to_universe()
    yield


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# --------------------------------------------------------------------------- #
# resolve
# --------------------------------------------------------------------------- #

def test_resolve_returns_the_company_for_a_known_slug(client):
    r = client.get("/api/companies/resolve", params={"slug": "NVDA"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["company_id"] == "nvda_us"
    assert body["ticker"] == "NVDA"
    assert body["slug"] == "NVDA"
    assert "has_model" in body


def test_resolve_is_case_insensitive(client):
    for variant in ("nvda", "Nvda", "NVDA", "  NVDA  "):
        r = client.get("/api/companies/resolve", params={"slug": variant})
        assert r.status_code == 200, f"{variant!r} did not resolve"
        assert r.json()["company_id"] == "nvda_us"


def test_resolve_returns_404_for_an_unknown_slug(client):
    """The behaviour the whole allowlist design exists for."""
    r = client.get("/api/companies/resolve", params={"slug": "ZZZZNOTREAL"})
    assert r.status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "../../etc/passwd",
        "NVDA'; DROP TABLE company_universe;--",
        "NVDA/../../secret",
        "a" * 64,
        "NV DA",
        "%2e%2e%2f",
        "null",
    ],
)
def test_resolve_rejects_malformed_slugs(client, bad):
    """Shape-gated before any query, so nothing hostile reaches SQLite."""
    r = client.get("/api/companies/resolve", params={"slug": bad})
    assert r.status_code in (400, 404), f"{bad!r} returned {r.status_code}"


def test_resolve_never_returns_a_financial_sector_company(client):
    """Financials are excluded from the model engine, so they get no slug."""
    r = client.get("/api/companies/resolve", params={"slug": "JPM"})
    assert r.status_code == 404, "a financial-sector company resolved to a public URL"


def test_shared_ticker_resolves_to_distinct_companies(client):
    """INFY exists twice. Both must be reachable, and at different URLs."""
    nse = client.get("/api/companies/resolve", params={"slug": "INFY"})
    nyse = client.get("/api/companies/resolve", params={"slug": "INFY-NYSE"})
    assert nse.status_code == 200, nse.text
    assert nyse.status_code == 200, nyse.text
    assert nse.json()["company_id"] == "infy_infy"
    assert nyse.json()["company_id"] == "infy_us"
    assert nse.json()["slug"] != nyse.json()["slug"]


# --------------------------------------------------------------------------- #
# manifest
# --------------------------------------------------------------------------- #

def test_manifest_lists_only_companies_with_a_slug(client):
    r = client.get("/api/companies/manifest", params={"limit": 500})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] > 0
    assert len(body["companies"]) > 0
    for c in body["companies"]:
        assert c["slug"], f"{c['company_id']} has no slug"
        assert c["market"] in ("india", "us")
        assert isinstance(c["has_model"], bool)


def test_manifest_excludes_financial_sector_companies(client):
    r = client.get("/api/companies/manifest", params={"limit": 500})
    tickers = {c["ticker"] for c in r.json()["companies"]}
    assert "JPM" not in tickers
    assert "HDFCBANK" not in tickers


def test_manifest_slugs_are_unique(client):
    """Two rows sharing a slug would make one of them permanently unreachable."""
    r = client.get("/api/companies/manifest", params={"limit": 5000})
    slugs = [c["slug"] for c in r.json()["companies"]]
    assert len(slugs) == len(set(slugs)), "duplicate slugs in the manifest"


def test_manifest_paging_is_consistent(client):
    first = client.get("/api/companies/manifest", params={"offset": 0, "limit": 5}).json()
    second = client.get("/api/companies/manifest", params={"offset": 5, "limit": 5}).json()
    assert first["total"] == second["total"]
    assert first["has_more"] is True
    assert {c["slug"] for c in first["companies"]}.isdisjoint(
        {c["slug"] for c in second["companies"]}
    )


def test_every_manifest_slug_resolves_back_to_its_own_company(client, unlimited_budget):
    """Round-trip: nothing listed may be unresolvable.

    Sweeps every slug the manifest lists, which is more requests than a person
    makes in a sitting. The budget is raised rather than the limiter removed, so
    the middleware still runs underneath.
    """
    listed = client.get("/api/companies/manifest", params={"limit": 500}).json()["companies"]
    for c in listed:
        r = client.get("/api/companies/resolve", params={"slug": c["slug"]})
        assert r.status_code == 200, f"{c['slug']} is listed but does not resolve"
        assert r.json()["company_id"] == c["company_id"]


# --------------------------------------------------------------------------- #
# store
# --------------------------------------------------------------------------- #

def test_get_universe_by_slug_is_exact_not_fuzzy():
    """A LIKE match would let /stock/NV resolve to something, which is wrong."""
    assert get_universe_by_slug("NV") is None
    assert get_universe_by_slug("NVDAX") is None
    assert get_universe_by_slug("nvda") is not None
