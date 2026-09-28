"""Per-client rate limiting, applied at the edge.

Placed as middleware rather than per-route so a new endpoint is limited by
default. A limit attached to each route individually is one more thing to
remember, and the endpoint someone forgets is the one that gets crawled.

Only the API is limited. The static mount answers a handful of routes and is
served off disk, and the health check has to answer when the box is under load or
it will be restarted by the platform at exactly the moment it is least able to
answer.
"""

from __future__ import annotations

import logging
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api import ratelimit

logger = logging.getLogger("valence.api.ratelimit")

# Paths that stay reachable regardless of budget. The health check is polled by
# the platform, and being rate limited out of it turns load into a restart.
_ALWAYS_ALLOWED = ("/api/health", "/api/docs", "/api/redoc", "/api/openapi.json")

# Mutating verbs get the tighter budget. Reading a ticker page is what the site
# is for; recompiling a model is a deliberate act.
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_TRUSTS_PROXY = os.getenv("VALENCE_TRUST_PROXY", "1") not in ("0", "false", "False")


def _client_key(request: Request) -> str:
    """Identify the caller.

    The connecting peer is only the client when nothing is in front of the app.
    Deployed, the peer is the platform's router, so every request would share one
    identity and a single crawler would exhaust the budget for everyone.

    `X-Forwarded-For` is a client-supplied header, so it is only trusted when the
    peer is a proxy we control. Where it is not trusted the peer address is used
    instead, which is the honest answer: one address, one budget. That is the
    safe direction to be wrong in, since a client that can spoof its identity
    defeats the limit while a client that cannot is merely limited alongside
    whoever shares its address.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _TRUSTS_PROXY:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if not path.startswith("/api") or any(path.startswith(p) for p in _ALWAYS_ALLOWED):
            return await call_next(request)

        kind = "write" if request.method in _MUTATING else "read"
        client = _client_key(request)

        if not ratelimit.allow(client, kind):
            budget, window = ratelimit.budget_for(kind)
            logger.info("rate limit hit: %s %s from %s", request.method, path, client)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        "Too many requests. This runs on a free tier, so the limits "
                        "are deliberately low. Try again shortly."
                    )
                },
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(budget),
                    "X-RateLimit-Window": str(window),
                },
            )

        return await call_next(request)
