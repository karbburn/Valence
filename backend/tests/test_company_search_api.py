"""The /companies/search payload contract, which the ticker's own badge depends on.

The search dropdown labels every result Ready or On demand, and it used to read
`onboarding_status` to decide. Those are different states: onboarded means the
filings are in the store, has_model means a valuation has actually been
compiled. Almost every company is onboarded, so the badge claimed a compiled
model for results that had none, which is the same overclaim this project keeps
finding in its own copy.

These tests pin the field the client reads, because a missing key is silent: the
badge falls back to a single label and nothing throws.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.data.universe.master_list import seed_master_universe
from backend.data.universe.store import assign_slugs_to_universe


@pytest.fixture(scope="module", autouse=True)
def _seeded_universe():
    seed_master_universe()
    assign_slugs_to_universe()
    yield


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# The search endpoint has to answer for a query that is not a ticker, because
# that is the case that proves the endpoint searches the universe rather than
# only the companies that happen to be modelled.
def test_search_is_not_limited_to_modelled_companies(client):
    """A broad term must return results, or "any listed ticker" is a lie."""
    r = client.get("/api/companies/search", params={"q": "a", "limit": 20})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) > 0, "a broad query returned nothing, so search is filtering"


def test_every_search_result_carries_has_model(client):
    """The field the badge reads. A missing key renders as a silent wrong label."""
    r = client.get("/api/companies/search", params={"q": "a", "limit": 20})
    assert r.status_code == 200
    for row in r.json():
        assert "has_model" in row, f"{row.get('ticker')} has no has_model key"
        assert isinstance(row["has_model"], bool), (
            f"{row.get('ticker')} has_model is {row['has_model']!r}, not a bool"
        )


def test_has_model_agrees_with_the_manifest(client):
    """The badge and the ticker index must not disagree about the same company.

    Both read the same helper, so this fails the moment one of them starts
    deriving it a second way.
    """
    manifest = client.get("/api/companies/manifest").json()["companies"]
    by_id = {c["company_id"]: c["has_model"] for c in manifest}

    found = 0
    for q in ("a", "e", "NV", "TCS"):
        for row in client.get(
            "/api/companies/search", params={"q": q, "limit": 50}
        ).json():
            cid = row["company_id"]
            if cid in by_id:
                assert row["has_model"] == by_id[cid], (
                    f"{cid}: search says has_model={row['has_model']}, "
                    f"manifest says {by_id[cid]}"
                )
                found += 1
    assert found > 0, "no company appeared in both, so nothing was cross-checked"


def test_search_still_returns_slug_for_canonical_navigation(client):
    """Selecting a result rewrites the address bar, so slug must survive."""
    for row in client.get("/api/companies/search", params={"q": "NV", "limit": 5}).json():
        assert row.get("slug"), f"{row.get('ticker')} came back without a slug"
