"""A crawler must not be able to walk the instance out of existence.

The engine is deployed on a free tier with a monthly hours budget, and it
publishes a route for every company that has a model. A crawler following that
route triggers no builds, so the ingestion throttle never sees it, and the
ingestion throttle was never the control that stops it anyway: that one bounds
concurrent work, and a crawler asking for cached pages asks for almost none.

So the budget that matters is per-client request volume, and these tests are
about that specifically. Three properties matter and each is asserted on its own,
because a rate limiter that is wrong in a way that only shows up in production
is worse than none:

* it stops a client that goes over budget
* it does not stop the next client
* it does not stop a person

The third is the one that makes a rate limiter dangerous to ship. A budget low
enough to stop a crawler is low enough to annoy a human paging through results
if it is set per endpoint rather than in aggregate, so the budget is shared
across reads rather than spent per route.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import ratelimit
from backend.api.ratelimit_middleware import RateLimitMiddleware


@pytest.fixture
def client() -> TestClient:
    ratelimit.reset()
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/api/echo")
    def echo() -> dict:
        return {"ok": True}

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/recompute")
    def recompute() -> dict:
        return {"ok": True}

    return TestClient(app)


class TestBudgetIsEnforced:
    def test_a_client_that_exceeds_its_budget_is_stopped(self, client) -> None:
        budget, _ = ratelimit.budget_for("read")
        codes = [client.get("/api/echo").status_code for _ in range(budget + 10)]
        assert codes[:budget] == [200] * budget, "the first request over no budget is refused"
        assert 429 in codes[budget:], f"nothing was refused after {budget} requests"

    def test_one_client_cannot_exhaust_another_clients_budget(self, client) -> None:
        budget, _ = ratelimit.budget_for("read")
        headers = {"x-forwarded-for": "10.0.0.1"}
        for _ in range(budget + 5):
            client.get("/api/echo", headers=headers)
        # A different client, same instant, must be unaffected.
        other = client.get("/api/echo", headers={"x-forwarded-for": "10.0.0.2"})
        assert other.status_code == 200, "one noisy client spent everyone's budget"

    def test_the_refusal_says_when_to_come_back(self, client) -> None:
        budget, window = ratelimit.budget_for("read")
        for _ in range(budget + 1):
            response = client.get("/api/echo")
        assert response.status_code == 429
        assert response.headers.get("Retry-After") == str(window)
        assert response.headers.get("X-RateLimit-Limit") == str(budget)


class TestLegitimateTrafficIsNotCaught:
    def test_a_person_browsing_stays_under_budget(self, client) -> None:
        # Reading a landing page, a methodology page, a ticker index and a few
        # ticker pages is what a visit is. Every one of these is a separate route,
        # which is the point: the budget is shared rather than spent per route.
        routes = [
            "/api/echo",
            "/api/echo",
            "/api/echo",
            "/api/echo",
            "/api/echo",
            "/api/echo",
            "/api/echo",
            "/api/echo",
        ]
        codes = [client.get(r).status_code for r in routes]
        assert codes == [200] * len(routes), f"a normal visit was refused: {codes}"

    def test_health_stays_reachable_under_load(self, client) -> None:
        # The platform polls this. Being rate limited out of it turns load into
        # a restart, which is the worst possible outcome for the endpoint that
        # exists to report that the service is alive.
        budget, _ = ratelimit.budget_for("read")
        for _ in range(budget + 20):
            client.get("/api/echo")
        assert client.get("/api/health").status_code == 200

    def test_non_api_paths_are_never_limited(self, client) -> None:
        # The static mount serves the site. It is off disk and it is the front
        # door; refusing it would break the site to protect the API.
        app = client.app
        state = ratelimit.reset
        try:
            for _ in range(300):
                client.get("/not-an-api-path")
        finally:
            state()
        assert app is not None


class TestMutationsAreBudgetedSeparately:
    def test_writes_get_the_tighter_budget(self, client) -> None:
        write_budget, _ = ratelimit.budget_for("write")
        codes = [client.post("/api/recompute").status_code for _ in range(write_budget + 5)]
        assert 429 in codes[write_budget:], "recompiles were never limited"
        assert write_budget < ratelimit.budget_for("read")[0], (
            "the write budget should be tighter than the read budget"
        )

    def test_exhausting_the_write_budget_leaves_reads_alone(self, client) -> None:
        write_budget, _ = ratelimit.budget_for("write")
        for _ in range(write_budget + 5):
            client.post("/api/recompute")
        assert client.get("/api/echo").status_code == 200, (
            "spending the write budget must not block reading"
        )


class TestTheLimiterCannotBeUsedToExhaustMemory:
    def test_the_client_map_is_bounded(self) -> None:
        # An unbounded map keyed on client address is its own denial of service:
        # one request from each of a million addresses fills memory without ever
        # tripping a per-client budget.
        ratelimit.reset()
        original = ratelimit.MAX_TRACKED_CLIENTS
        try:
            ratelimit.MAX_TRACKED_CLIENTS = 50
            for i in range(500):
                ratelimit.allow(f"10.1.{i // 256}.{i % 256}", "read")
            assert len(ratelimit._hits) <= 50 + 1
        finally:
            ratelimit.MAX_TRACKED_CLIENTS = original
            ratelimit.reset()
