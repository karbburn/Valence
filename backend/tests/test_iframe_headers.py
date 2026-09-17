"""Regression test for the iframe-header middleware crash.

Commit 1d69b53 called response.headers.pop(...), but Starlette's
MutableHeaders has no .pop() — every response (including /api/health)
raised AttributeError, failing Render health checks and timing out deploys.
"""
from fastapi.testclient import TestClient

from backend.api.main import app


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_health_passes_through_middleware():
    resp = _client().get("/api/health")
    assert resp.status_code == 200
    assert "frame-ancestors" in resp.headers.get("content-security-policy", "")
    assert "x-frame-options" not in resp.headers


def test_model_route_passes_through_middleware():
    resp = _client().get("/api/model/infy_infy")
    assert resp.status_code == 200
    assert "frame-ancestors" in resp.headers.get("content-security-policy", "")
    assert "x-frame-options" not in resp.headers
