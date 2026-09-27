"""A peer must not depend on the one market-data call that a host can be refused.

The provider's quote-summary call needs a session crumb, and crumbs are
rate-limited per requesting address. A shared host address is refused regularly —
the deployed log reads "Crumb fetch rate-limited (HTTP 429), continuing without
crumb" — while the statement endpoints, which need no crumb, carry on working.

The peer path read its price only from that call. On such a host every peer was
dropped and the comparables tab shipped empty, with the honest but useless
explanation "only 0 of 5 peers could be sourced". A third of the valuation was
absent from the document a user downloads.

These tests exercise the deployed condition directly: a ticker whose quote
summary raises, as it does when the crumb is refused.
"""

from __future__ import annotations

import pytest

from backend.valuation import peer_multiples as pm


class _RefusedSummary:
    """A ticker whose quote summary the host is not allowed to fetch."""

    def __init__(self, inner):
        self._inner = inner

    @property
    def info(self):
        raise RuntimeError("Crumb fetch rate-limited (HTTP 429), continuing without crumb")

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture
def refused_quote_summary(monkeypatch):
    """Make every ticker behave as it does on a rate-limited host."""
    real = pm.yf.Ticker
    monkeypatch.setattr(pm.yf, "Ticker", lambda symbol: _RefusedSummary(real(symbol)))


def test_a_price_is_still_resolved_when_the_quote_summary_raises(refused_quote_summary):
    """The daily price history needs no crumb and is the better price anyway."""
    price, as_of, source = pm._peer_price(
        pm.yf.Ticker("MSFT"), "MSFT", {}
    )

    assert price is not None, (
        "no price could be resolved once the quote summary was refused; the peer "
        "path is depending on the one call a host can be rate-limited out of"
    )
    assert price > 0
    assert source, "the price source must be recorded so a reader can see it"
    assert as_of, "a price must carry the date it was struck on"


def test_the_quote_summary_is_the_last_resort_not_the_first(refused_quote_summary):
    """A crumb-dependent call may be consulted, but never relied upon."""
    # With no crumb available the chain still produced a price, and it came from
    # a crumb-free source.
    _, _, source = pm._peer_price(pm.yf.Ticker("AAPL"), "AAPL", {})

    assert "quote summary" not in source.lower(), (
        f"the price came from the crumb-dependent call ({source}); the daily "
        "close must be preferred"
    )


def test_the_daily_close_is_preferred_over_the_quote_summary_print():
    """A daily exchange close beats a last-trade print for a market cap.

    The quote summary reports an intraday or last-trade figure, which is a
    different number for the same day. The main price chain already ranks the
    daily close first for this reason.
    """
    handle = pm.yf.Ticker("NVDA")
    info = {"currentPrice": 999.0, "regularMarketTime": 1_700_000_000}

    price, _, source = pm._peer_price(handle, "NVDA", info)

    assert source.startswith("daily close"), source
    assert price != 999.0, (
        "the quote summary's price was used even though a daily close was "
        "available; the two are different numbers for the same day"
    )


def test_a_peer_is_still_sourced_end_to_end_without_a_quote_summary(refused_quote_summary):
    """The whole comparables analysis must survive the deployed condition."""
    from backend.valuation.comps import compute_trading_comps

    result = compute_trading_comps(
        target_ticker="NVDA",
        target_sector="Technology",
        target_revenue_fy27=406_546.0,
        target_ebitda_fy27=245_000.0,
        target_net_profit_fy27=190_000.0,
        net_debt=-24_118.0,
        shares_outstanding=24_147.0,
    )

    assert result.peers, (
        "no peers could be sourced once the quote summary was refused, so the "
        "comparables tab would ship empty"
    )
    assert result.benchmarks, (
        f"peers were sourced ({len(result.peers)}) but no benchmark was "
        f"published; reason given: {result.unavailable_reason}"
    )
    assert result.implied_valuations, "no implied valuation was produced"


def test_a_peer_records_where_its_price_came_from(refused_quote_summary):
    """A reader must be able to see which source priced a peer."""
    peer = pm.compute_peer_multiples("MSFT", "Microsoft Corp", "US")

    assert peer is not None
    assert peer.price_source, "a peer does not record its price source"
    assert peer.price_as_of, "a peer does not record the date of its price"
