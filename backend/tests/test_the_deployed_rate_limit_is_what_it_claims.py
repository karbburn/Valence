"""The deployed rate limit must be the one the deployment actually produces.

`ratelimit_middleware` claimed in a comment that `render.yaml` sets `VALENCE_TRUST_PROXY`.
It does not, and never has, so the comment described an intention rather than the
configuration. The middleware's own tests and copy correctly say the budget is SITE-WIDE, so
the code and the comment disagreed with each other and only one of them was true.

A comment asserting a security setting is evidence, and evidence nobody re-derives is how a
limiter ends up reading a caller-controlled header. So this asserts the DEPLOYED shape
rather than the code's intent:

  * `Dockerfile` keeps `--no-proxy-headers`, so `request.client.host` is the real TCP peer
    and is the one address a caller cannot write. Remove it and the limiter keys on a header
    the caller controls, which was measured: rotating `X-Forwarded-For` bought an unlimited
    budget while one honest visitor was cut off.
  * `render.yaml` does not switch proxy-header trust on. It is off, so the budget is
    site-wide, which is safe and is what the limiter's copy already says.
  * The middleware's default is off, so a deployment that forgets to say anything is safe
    rather than exposed.

Asserted against the files rather than the module because the whole defect lived in the gap
between a file and a comment, and importing the module would prove nothing about it.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
RENDER_YAML = (ROOT / "render.yaml").read_text(encoding="utf-8")
MIDDLEWARE = (ROOT / "backend" / "api" / "ratelimit_middleware.py").read_text(encoding="utf-8")


def test_the_deployed_server_does_not_trust_the_callers_own_forwarded_header():
    assert "--no-proxy-headers" in DOCKERFILE, (
        "the Dockerfile no longer passes --no-proxy-headers, so uvicorn rewrites "
        "request.client.host from the caller's X-Forwarded-For and the rate limiter keys on "
        "a header the caller writes. Measured: rotating the header bought an unlimited "
        "budget."
    )
    # It has to be on the command that actually runs, not mentioned in a comment.
    cmd = [ln for ln in DOCKERFILE.splitlines() if ln.strip().startswith("CMD")]
    assert cmd, "no CMD in the Dockerfile"
    assert "--no-proxy-headers" in cmd[-1], (
        f"the running command does not carry --no-proxy-headers: {cmd[-1]!r}"
    )


def test_the_deployment_does_not_turn_proxy_trust_on():
    assert "VALENCE_TRUST_PROXY" not in RENDER_YAML, (
        "render.yaml now sets VALENCE_TRUST_PROXY. That is only safe where something this "
        "deployment controls terminates the connection and is known to APPEND to "
        "X-Forwarded-For, so the rightmost entry is the real client. Where a proxy passes "
        "the header through unmodified, this turns a bounded site-wide bucket into an "
        "unlimited one. If the platform's behaviour has been verified, say so in the "
        "middleware comment and in this test rather than only in the deployment."
    )


def test_the_middleware_defaults_to_not_trusting_the_proxy():
    """A deployment that forgets to configure anything must be safe by default."""
    m = re.search(
        r'_TRUSTS_PROXY\s*=\s*os\.getenv\(\s*"VALENCE_TRUST_PROXY"\s*,\s*"([^"]*)"\s*\)',
        MIDDLEWARE,
    )
    assert m, "the middleware no longer reads VALENCE_TRUST_PROXY with a default"
    assert m.group(1) in ("0", "false", "False"), (
        f"the default is {m.group(1)!r}; forgetting to configure a deployment would then "
        f"mean trusting the caller"
    )


def test_the_comment_matches_the_deployment():
    """The specific regression: a comment claiming a setting nobody made.

    The first version of this test searched for the phrase outright and failed on the very
    comment that documents the fix, because the fix quotes the claim it is replacing. A
    guard that cannot distinguish asserting a thing from quoting it is a guard that has to
    be loosened until it is useless.

    So the phrase is only a violation on a line that does not also mark it as history.
    """
    offenders = [
        line.strip()
        for line in MIDDLEWARE.splitlines()
        if re.search(r"Deployment sets it in render\.yaml", line)
        and not re.search(r"used to say|does not|never has|no such variable", line, re.I)
    ]
    assert not offenders, (
        "the middleware claims render.yaml sets VALENCE_TRUST_PROXY, and the line does not "
        f"mark it as historical: {offenders}"
    )
    assert "site-wide" in MIDDLEWARE, (
        "the middleware should state what the deployed budget actually is"
    )
    assert re.search(
        r"render\.yaml.{0,80}does not|does not.{0,80}render\.yaml", MIDDLEWARE, re.I | re.S
    ), (
        "the middleware should say plainly that the deployment does not set the flag, "
        "rather than leaving the reader to work it out"
    )


def test_the_limit_copy_advertises_what_is_enforced():
    """A 429 that says "too many requests" over a shared bucket must not imply per-client."""
    from backend.api.ratelimit_middleware import RateLimitMiddleware  # noqa: F401

    assert "Too many requests" in MIDDLEWARE
    assert not re.search(r"per[- ]client (limit|budget)", MIDDLEWARE, re.I), (
        "the middleware describes itself as per-client while the deployed configuration "
        "produces one shared key"
    )