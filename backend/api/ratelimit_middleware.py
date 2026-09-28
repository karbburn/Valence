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

# Off unless a proxy is known to be in front. This is the reverse of the obvious
# default and the reason is in `_client_key`: the header is only worth reading
# when something upstream rewrites it, and trusting it when nothing does means
# trusting the client. Deployment sets it in render.yaml alongside the service
# definition, so the setting lives with the deployment rather than in code.
_TRUSTS_PROXY = os.getenv("VALENCE_TRUST_PROXY", "0") not in ("0", "false", "False")

# A build is not a client.
#
# The frontend proxies every API call through the Next server, so the backend
# sees one address for the entire internet and, separately, one address for the
# build. Two consequences, both measured:
#
# The build prerenders up to PRERENDER_LIMIT tickers, and each one makes
# several calls. Against a per-client read budget that is 20 of 175 pages served
# and the rest refused, and because every server-side fetch degrades to null
# rather than throwing, the build exits zero and ships the rest as empty shells
# marked noindex. A silent, near-total prerender failure is worse than a loud
# one.
#
# A per-client write budget is site-wide for the same reason. Releasing one
# slider fires a POST, so twelve a minute across the whole site is a shared
# allowance that any two users can exhaust between them.
#
# Neither is a client to limit. The build is identified by a header the caller
# sets deliberately, and the proxy is by the address it connects from.
_TRUSTED_HOPS = frozenset(
    h.strip() for h in os.getenv("VALENCE_TRUSTED_PROXY_IPS", "").split(",") if h.strip()
)


def _client_key(request: Request) -> str:
    """Identify the caller, or admit that it cannot be done.

    This went wrong twice before it was right, and both failures are worth
    recording because both looked like working code.

    The first version read `X-Forwarded-For` and took the leftmost entry. That
    is the entry the caller controls most directly, so a crawler could send a
    different value per request and buy an unlimited budget while one honest
    visitor was cut off at the limit.

    The second read the rightmost entry, which is correct for a single trusted
    proxy, and then fell back to the peer address for anything else. That looked
    safer, and was not: the server runs under uvicorn, whose `proxy_headers` is
    on by default and rewrites the peer from that same header. Measured on this
    deployment, a request carrying `X-Forwarded-For: 9.9.9.9` arrived with
    `request.client.host == "9.9.9.9"`, and the identical request without the
    header arrived as `127.0.0.1`. So the fallback was reading the spoofable
    value with extra steps, and 500 rotating header values still all passed.

    The honest conclusion is that the peer address cannot be trusted here at
    all, and neither can the header, so neither is used unless a deployment
    explicitly asserts that something in front rewrites them. Absent that
    assertion every caller shares one key, which makes the budget site-wide.

    A site-wide budget is still the right thing to have. It is blunt, and it
    cannot tell a crawler from a visitor, but it bounds the thing that actually
    runs out, which is the instance's hours. What it must not be is advertised
    as per-client when it is not, so the comment here and the test names say
    site-wide.
    """
    if _TRUSTS_PROXY:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Rightmost: the last hop our own proxy saw. Anything to the left of
            # it was written by the caller.
            candidate = forwarded.rsplit(",", 1)[-1].strip()
            if candidate:
                return f"xff:{candidate}"
    peer = request.client.host if request.client else None
    if peer:
        return f"peer:{peer}"
    # Unidentifiable. One shared key rather than no limit at all.
    return "unidentified"


def _is_build(request: Request) -> bool:
    """Whether this caller is the site's own build.

    Identified by an explicit header rather than by address, so it cannot be
    turned on by a visitor: the same origin that serves the site is the origin
    that runs the build, and the build is a process the operator controls.
    """
    return request.headers.get("x-valence-build", "") == "1"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if not path.startswith("/api") or any(path.startswith(p) for p in _ALWAYS_ALLOWED):
            return await call_next(request)

        # The build and the frontend proxy are not clients. See the note on
        # _TRUSTED_HOPS for what limiting them costs.
        if _is_build(request) or (request.client and request.client.host in _TRUSTED_HOPS):
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
