FROM python:3.12-slim

WORKDIR /app

# Copy source tree before install so `pip install .` can resolve the backend package
# (see [tool.setuptools.packages.find] include = ["backend*"] in pyproject.toml)
COPY pyproject.toml .
COPY backend ./backend

RUN pip install --no-cache-dir .

# Run as a non-root user; give the app full ownership of its workdir so it can
# write runtime artifacts (model caches, Excel export output, static assets).
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

# Render's Docker runtime routes traffic to the $PORT env var (default 10000).
# Bind to it explicitly (falling back to 8000 for local `docker run`) so the
# platform's health check and load balancer can actually reach the server.
# Hardcoding 8000 here previously caused `hibernate-wake-error` 503s because
# Render expected the app on $PORT (10000) and the health check could not connect.
EXPOSE 10000

HEALTHCHECK CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health')"]

# --no-proxy-headers is load-bearing, not a preference.
#
# uvicorn rewrites the peer address from the caller's own X-Forwarded-For by
# default. The rate limiter keys on that peer, so leaving it on means a client
# chooses its own identity: rotating the header bought an unlimited budget in
# testing while one honest visitor was cut off. With it off the peer is the real
# TCP peer, which is the only address the caller cannot write.
#
# Behind the platform's router every caller then shares the router's address, so
# the request budget is site-wide rather than per-client. That is the honest
# reading of what this deployment can see, and the limiter documents it as such
# rather than claiming a separation it does not have.
CMD ["sh", "-c", "uvicorn backend.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-proxy-headers"]