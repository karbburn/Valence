"""Live trading-multiple inputs for a peer.

A comps multiple is (market capitalisation + net debt) over a reported
financial figure. All three inputs have to be real, current, and on a
consistent basis, or the multiple is not comparable to anything — including the
multiple a reader is checking it against.

Every input here comes from the same machinery the rest of the platform uses:
the live price chain, the diluted share count, the trailing twelve months of
reported results, and the most recent reported balance sheet for net debt. A
peer that cannot be sourced on all four is returned as None rather than filled
with a placeholder.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from backend.data.providers.run_rate import (
    sum_four_quarters,
    trailing_twelve_months,
)
from backend.data.providers.share_count import resolve_share_count
from backend.forecast.debt import OPENING_BALANCE_KEYS

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import yfinance as yf

logger = logging.getLogger(__name__)

# Feed rows for each income-statement figure, in preference order.
_REVENUE_ROWS = ("Total Revenue", "Operating Revenue", "Gross Revenue")
_EBITDA_ROWS = ("EBITDA", "Normalized EBITDA")
_EBIT_ROWS = ("Operating Income", "EBIT", "Operating Income Loss")
_DA_ROWS = (
    "Reconciled Depreciation",
    "Depreciation And Amortization In Income Statement",
    "Depreciation Amortization Depletion",
)
_NET_INCOME_ROWS = (
    "Net Income Common Stockholders",
    "Net Income",
    "Net Income From Continuing Operation Net Minority Interest",
)
_CFO_ROWS = ("Operating Cash Flow", "Cash Flowsfromusedin Operating Activities")
_CAPEX_ROWS = ("Capital Expenditure", "Purchase Of PPE", "PaymentsToAcquirePropertyPlantAndEquipment")
_EQUITY_ROWS = ("Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity")
_ASSET_ROWS = ("Total Assets",)
_TAX_ROWS = ("Tax Provision", "Income Tax Expense")

# Ticker suffix by exchange code used in the peer roster.
_EXCHANGE_SUFFIX = {
    "US": "",
    "NS": ".NS",
    "BO": ".BO",
    "L": ".L",
    "HK": ".HK",
    "KR": ".KS",
    "JP": ".T",
    "DE": ".DE",
}

# PLAUSIBILITY BOUNDS for a published multiple.
#
# These are not valuation opinions. They are the point beyond which a number
# cannot be a real trading multiple and must instead be a unit error, a sign
# error or a mapping to the wrong row. Every bound is wide enough that a real
# company sits comfortably inside it, including asset-light software at 40x
# EBITDA, a bank-like utility at 6x, and a pre-profit growth name whose
# multiple is large but finite.
PLAUSIBLE_EV_REVENUE = (0.05, 80.0)
PLAUSIBLE_EV_EBITDA = (1.0, 120.0)
PLAUSIBLE_ROIC = (-25.0, 150.0)
PLAUSIBLE_EBITDA_MARGIN = (-0.50, 0.95)
# Revenue to market capitalisation. A listed company with revenue below a
# twentieth of its own market value, or above a hundred times it, is almost
# always a statement feed in the wrong unit.
PLAUSIBLE_REVENUE_TO_MARKET_CAP = (0.02, 100.0)
# Invested capital below this share of ANNUAL REVENUE makes a return on invested
# capital uninformative: a denominator far below the business it is measuring
# produces a percentage that is arithmetically valid and economically
# meaningless, and belongs on no peer table.
#
# This is measured against revenue, not against market capitalisation. A
# company that has repurchased its shares for decades carries a book equity far
# below its market value while operating an entirely ordinary capital base —
# one large-cap returns over 100% on book invested capital and buys back
# billions a year, which is a real and well-known characteristic rather than a
# data error. Measuring against market value silently deleted that company's
# return and published 0.0% in its place, which reads as "earns nothing" rather
# than "not measurable". A business whose invested capital is genuinely
# negligible next to its own sales still fails this bound.
PLAUSIBLE_INVESTED_CAPITAL_FLOOR = 0.02


@dataclass
class PeerMultiples:
    """Live multiples for one peer, all struck on the same basis."""

    ticker: str
    company_name: str
    market: str
    share_price: float
    shares_outstanding: float
    market_cap: float
    net_debt: float
    enterprise_value: float
    revenue_ttm: float
    ebitda_ttm: float
    net_income_ttm: float
    ev_revenue: float
    ev_ebitda: float
    pe_ratio: float
    fcf_yield_pct: float
    roic_pct: float
    financials_period: str
    balance_sheet_as_of: str
    price_as_of: str
    shares_basis: str = ""
    price_source: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _symbol(ticker: str, exchange: str) -> str:
    return f"{ticker}{_EXCHANGE_SUFFIX.get(exchange, '')}"


def _row(frame, rows: tuple[str, ...], column, default: Optional[float] = None) -> Optional[float]:
    if frame is None or column is None:
        return default
    for label in rows:
        if label in frame.index:
            try:
                value = frame.loc[label, column]
            except Exception:
                continue
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number != number:  # NaN
                continue
            return number
    return default


def _column_dates(frame) -> list:
    """Column keys of a statement, oldest to newest."""
    return list(frame.columns)


def _sum_last_four_quarters(frame, rows: tuple[str, ...]) -> Optional[float]:
    """Trailing twelve months from four consecutive quarters.

    Delegates to the shared implementation. The forecast anchor reads the same
    construction, and the two had separate copies: a fix applied here left the
    other computing a different denominator for the same company, which is the
    kind of drift that makes two published numbers about one business
    irreconcilable.
    """
    return sum_four_quarters(frame, rows)


def _ttl(frame, rows: tuple[str, ...], quarterly) -> Optional[float]:
    """Trailing twelve months for a peer's statement line.

    Four consecutive quarters are summed where the feed carries them; failing
    that the latest annual figure is rolled forward by every quarter reported
    since its year end. Both constructions are the shared ones, so a peer and the
    forecast for the target it is compared against are denominated identically.

    Falling back to the un-rolled annual is a real possibility and is why this
    returns the annual at all: a multiple on a two-year-old denominator is better
    than no multiple, provided the reader can see how old it is. The
    inancials_period field carries that date.
    """
    return trailing_twelve_months(frame, rows, quarterly)


def _safe_ratio(numerator: float, denominator: Optional[float]) -> Optional[float]:
    if denominator is None or abs(denominator) < 1e-9:
        return None
    value = numerator / denominator
    if value != value:
        return None
    return value


# Rows that state the ordinary share count, in order of preference. The filed
# balance sheet and the provider's summary field are both read, and the choice
# between them is made by `resolve_share_count`, which knows that a round ratio
# means a depositary receipt and a ragged one means share classes.
_SHARE_ROWS = (
    "Ordinary Shares Number",
    "Share Issued",
    "Common Stock Shares Outstanding",
)


def _peer_price(handle, symbol: str, info: dict) -> tuple[Optional[float], str, str]:
    """A peer's share price, from whichever source answers.

    Order matters and `.info` is LAST. The provider's quote-summary call needs a
    session crumb, and crumbs are rate-limited per requesting address; a shared
    host address is refused regularly, returning no summary at all. When the peer
    path read its price only from that call, every peer was dropped on such a host
    and the comparables tab shipped empty — with the reason "only 0 of 5 peers
    could be sourced", which is true and tells a reader nothing about why.

    The daily price history and the chart endpoint need no crumb, and a daily
    exchange close is the better price anyway: the quote summary reports a
    last-trade print, which is a different number for the same day.

    Returns (price, as_of, source).
    """
    # 1. Daily close from the price history. Newest session last, and the
    #    history is what a market capitalisation is conventionally struck on.
    try:
        history = handle.history(period="5d", auto_adjust=False)
        if history is not None and len(history) > 0:
            closes = [c for c in history["Close"].tolist() if c == c and c and float(c) > 0]
            if closes:
                stamps = history.index
                as_of = ""
                for stamp in reversed(list(stamps)):
                    try:
                        as_of = stamp.date().isoformat()
                        break
                    except Exception:
                        continue
                return float(closes[-1]), as_of, "daily close (price history)"
    except Exception as exc:
        logger.info("Peer %s: price history unavailable (%s)", symbol, exc)

    # 2. The chart endpoint directly, which is a different call path from the
    #    quote summary and carries no crumb requirement.
    try:
        import requests

        response = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": "5d", "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        payload = response.json() if response.status_code == 200 else None
        result = ((payload or {}).get("chart") or {}).get("result") or []
        if result:
            closes = [c for c in result[0]["indicators"]["quote"][0]["close"] if c]
            if closes:
                stamps = result[0].get("timestamp") or []
                as_of = ""
                if stamps:
                    as_of = datetime.utcfromtimestamp(stamps[-1]).date().isoformat()
                return float(closes[-1]), as_of, "daily close (chart endpoint)"
    except Exception as exc:
        logger.info("Peer %s: chart endpoint unavailable (%s)", symbol, exc)

    # 3. Last, the quote summary, for the crumb-dependent case only.
    for key in ("currentPrice", "regularMarketPrice", "previousClose"):
        value = info.get(key) if isinstance(info, dict) else None
        if value and isinstance(value, (int, float)) and float(value) > 0:
            as_of = ""
            raw = info.get("regularMarketTime") if isinstance(info, dict) else None
            if isinstance(raw, (int, float)):
                as_of = datetime.utcfromtimestamp(float(raw)).date().isoformat()
            return float(value), as_of, f"quote summary ({key})"

    return None, "", ""


def _resolve_peer_shares(
    handle, info: dict, symbol: str
) -> tuple[Optional[float], str]:
    """Ordinary shares outstanding for a peer, in the feed's own units.

    Prefers the most recently filed balance sheet over the provider's summary
    field, and says which was used. The quarterly statement is preferred because
    it is the most recent filing; the annual is the fallback.

    Returns (shares, basis). `shares` is None when neither source has a usable
    figure, in which case the peer is dropped rather than priced on a guess.
    """
    filed: Optional[float] = None
    filed_basis = ""

    for attr in ("quarterly_balance_sheet", "balance_sheet"):
        try:
            frame = getattr(handle, attr, None)
        except Exception:
            continue
        if frame is None or len(getattr(frame, "columns", [])) == 0:
            continue
        column = frame.columns[0]
        for label in _SHARE_ROWS:
            if label not in frame.index:
                continue
            try:
                value = float(frame.loc[label, column])
            except Exception:
                continue
            if value != value or value <= 0:
                continue
            filed = value
            filed_basis = f"{label} at {str(column)[:10]}"
            break
        if filed is not None:
            break

    provider: Optional[float] = None
    try:
        raw = info.get("sharesOutstanding")
        if raw and float(raw) > 0:
            provider = float(raw)
    except (TypeError, ValueError):
        provider = None

    return resolve_share_count(
        filed,
        provider,
        filed_basis=filed_basis,
        provider_basis="provider shares outstanding",
    )


def compute_peer_multiples(
    ticker: str,
    company_name: str,
    exchange: str,
) -> Optional[PeerMultiples]:
    """Live multiples for one peer, or None when it cannot be sourced.

    Returns None rather than a partial row. A comps table with invented
    numbers in it is worse than a shorter table, because every number in it
    looks equally trustworthy.
    """
    symbol = _symbol(ticker, exchange)
    try:
        handle = yf.Ticker(symbol)
    except Exception as exc:
        logger.info("Peer %s unavailable: %s", symbol, exc)
        return None

    try:
        info = handle.info or {}
    except Exception:
        # `.info` is the one call that needs a session crumb, and a crumb fetch
        # is rate-limited per address. A shared host address therefore loses
        # `.info` routinely while the statement endpoints, which need no crumb,
        # carry on working. It must not be load-bearing.
        info = {}

    price, price_as_of, price_source = _peer_price(handle, symbol, info)
    if not price:
        logger.info("Peer %s: no price from any source", symbol)
        return None

    annual = getattr(handle, "income_stmt", None)
    quarterly = getattr(handle, "quarterly_income_stmt", None)
    if annual is None or len(getattr(annual, "columns", [])) == 0:
        logger.info("Peer %s: no income statement", symbol)
        return None

    revenue = _ttl(annual, _REVENUE_ROWS, quarterly)
    net_income = _ttl(annual, _NET_INCOME_ROWS, quarterly)
    ebit = _ttl(annual, _EBIT_ROWS, quarterly)
    da = _ttl(annual, _DA_ROWS, quarterly)
    # EBITDA is always DERIVED as operating profit plus depreciation and
    # amortisation. A feed's own EBITDA row is not reliable across listings:
    # it produced a 68% EBITDA margin at one large-cap and an eleventh of the
    # real figure at another, both of which would have published a multiple
    # several times out. Operating profit and D&A are the two most consistently
    # reported rows there are.
    ebitda = (ebit + da) if (ebit is not None and da is not None) else None

    if revenue is None or revenue <= 0:
        logger.info("Peer %s: no usable revenue", symbol)
        return None

    cash_flow = getattr(handle, "cashflow", None)
    quarterly_cash_flow = getattr(handle, "quarterly_cashflow", None)
    cfo = _ttl(cash_flow, _CFO_ROWS, quarterly_cash_flow)
    capex = _ttl(cash_flow, _CAPEX_ROWS, quarterly_cash_flow)
    free_cash_flow = None
    if cfo is not None and capex is not None:
        free_cash_flow = cfo - abs(capex)

    # Equity and assets come from the QUARTERLY balance sheet when it is
    # available, matching the net debt taken from the same most-recent-reported
    # snapshot. Reading them off the annual statement instead mixed a
    # nine-month-old capital base with a current one, and since return on
    # invested capital divides by that base it understated the return by
    # whatever the company earned in the intervening quarters.
    quarterly_balance = getattr(handle, "quarterly_balance_sheet", None)
    balance = quarterly_balance
    if balance is None or len(getattr(balance, "columns", [])) == 0:
        balance = getattr(handle, "balance_sheet", None)
    equity = _row(balance, _EQUITY_ROWS, balance.columns[0]) if balance is not None and len(balance.columns) else None
    assets = _row(balance, _ASSET_ROWS, balance.columns[0]) if balance is not None and len(balance.columns) else None
    tax = _ttl(annual, _TAX_ROWS, quarterly)

    # Net debt and share count are taken the same way the valuation bridge takes
    # them, so a peer is measured on the basis the target is measured on.
    #
    # On the SAME basis means the whole bridge, not just its debt and cash legs.
    # This used to take debt less liquid assets and stop there, leaving out the
    # minority interests and preferred stock that enterprise value also carries.
    # At one Indian conglomerate those holdings are worth more than its entire
    # gross debt, so the omission moved its enterprise value by roughly a fifth
    # and its EV/EBITDA by the same proportion — a peer that is not comparable
    # to the target it is being compared against.
    # Net debt.
    #
    # `None` until it is actually established. A peer whose balance sheet cannot
    # be resolved is dropped rather than published at zero: a net debt of 0.0
    # reads as "carries no debt" and flows straight into an enterprise value and
    # a multiple, so an unsourced peer presented as a debt-free one is worse than
    # an absent peer.
    net_debt: Optional[float] = None
    balance_as_of = ""
    company_id = _company_id_for(symbol)

    # The peer's FILED balance sheet first, on the same definition the target is
    # valued on.
    #
    # This has to lead. The valuation bridge stopped taking net debt from a market
    # feed's quarterly statement, because that statement's period end was a
    # synthetic calendar date rather than the day the quarter closed and its debt
    # total capitalised every operating lease it could find. A benchmark whose
    # median is a mix of filed and feed net debt is a median of two conventions,
    # and it moves as peers happen to be sourced rather than as they are valued.
    # So a peer the platform has a filed statement for is measured exactly as the
    # target is, and only a peer with no filed statement falls back to the feed.
    filed = _filed_net_debt(company_id) if company_id else None
    if filed is not None:
        net_debt, balance_as_of = filed
    elif not company_id:
        logger.info(
            "Peer %s: listed in a market the platform does not onboard, so its "
            "balance sheet cannot be resolved — dropped rather than published "
            "with no debt",
            symbol,
        )
        return None
    else:
        try:
            from backend.data.bridge_inputs import fetch_bridge_snapshot

            # Absolute currency, because the market capitalisation below is price
            # times shares and is therefore in rupees or dollars. The snapshot's
            # default crores/millions scaling is for the model, and adding it to an
            # absolute market capitalisation understates net debt ten-millionfold.
            snapshot = fetch_bridge_snapshot(company_id, in_model_units=False)
            if snapshot is not None and snapshot.as_of:
                claims = (snapshot.terms.get("minority_interest") or 0.0) + (
                    snapshot.terms.get("preferred_stock") or 0.0
                )
                net_debt = snapshot.total_debt + claims - snapshot.total_liquid_assets
                balance_as_of = snapshot.as_of
        except Exception as exc:
            logger.info("Peer %s: balance sheet snapshot unavailable (%s)", symbol, exc)

    if net_debt is None:
        logger.info("Peer %s: no balance sheet, so no net debt — dropped", symbol)
        return None

    # Share count: the FILED total, not the provider's summary field.
    #
    # A multi-class issuer's summary field reports one class. For one large-cap
    # it returned 5.87bn against a filed 12.23bn, which halved the market
    # capitalisation, doubled every per-share figure, and made the peer's
    # EV/Revenue read 5.0x against a market 9.2x — a real company made to look
    # cheap because of a share-class convention. The same rejection rule the
    # valuation bridge already applies is applied here, so a peer and the target
    # are measured on the same basis.
    shares, shares_basis = _resolve_peer_shares(handle, info, symbol)
    if not shares or shares <= 0:
        logger.info("Peer %s: no share count", symbol)
        return None

    market_cap = price * shares
    enterprise_value = market_cap + net_debt

    ev_revenue = _safe_ratio(enterprise_value, revenue)
    ev_ebitda = _safe_ratio(enterprise_value, ebitda) if ebitda else None
    pe = _safe_ratio(market_cap, net_income) if (net_income and net_income > 0) else None
    fcf_yield = _safe_ratio(free_cash_flow * 100.0, market_cap) if free_cash_flow is not None else None

    # PLAUSIBILITY GATE.
    #
    # Statement feeds report in inconsistent units across listings — one large
    # Indian listing came through in a unit a hundredfold away from its own
    # annual accounts, which turned a 3x multiple into a 790x one. A multiple
    # that fails these bounds is not a real valuation, it is a unit or a mapping
    # error, and printing it in a peer table lends it the same credibility as
    # its neighbours. Such a peer is dropped, and the reason recorded.
    if ev_revenue is not None and not (PLAUSIBLE_EV_REVENUE[0] <= ev_revenue <= PLAUSIBLE_EV_REVENUE[1]):
        logger.info("Peer %s: EV/Revenue %.1fx outside a plausible band — dropped", symbol, ev_revenue)
        return None
    if ev_ebitda is not None and not (PLAUSIBLE_EV_EBITDA[0] <= ev_ebitda <= PLAUSIBLE_EV_EBITDA[1]):
        logger.info("Peer %s: EV/EBITDA %.1fx outside a plausible band — dropped", symbol, ev_ebitda)
        return None
    if ev_revenue is not None and market_cap > 0:
        revenue_to_market_cap = revenue / market_cap
        if not (PLAUSIBLE_REVENUE_TO_MARKET_CAP[0] <= revenue_to_market_cap <= PLAUSIBLE_REVENUE_TO_MARKET_CAP[1]):
            logger.info(
                "Peer %s: revenue is %.3fx market capitalisation — statement units "
                "disagree with the share count, dropped",
                symbol,
                revenue_to_market_cap,
            )
            return None
    if ebitda is not None and revenue > 0:
        margin = ebitda / revenue
        if not (PLAUSIBLE_EBITDA_MARGIN[0] <= margin <= PLAUSIBLE_EBITDA_MARGIN[1]):
            logger.info("Peer %s: EBITDA margin %.0f%% is not a business margin — dropped", symbol, margin * 100)
            return None

    roic = None
    # Return on invested capital needs a capital base that is real relative to
    # the business it measures, so the floor is set against annual revenue. A
    # company that has repurchased its shares for years carries a small book
    # equity next to a large market value, which is an ordinary situation and not
    # a reason to withhold the figure.
    invested = None
    if equity is not None and revenue > 0:
        invested = equity + max(net_debt, 0.0)
    if (
        ebit
        and tax is not None
        and invested
        and invested > revenue * PLAUSIBLE_INVESTED_CAPITAL_FLOOR
    ):
        effective_tax = min(max(tax / ebit, 0.0), 0.6) if ebit else 0.0
        nopat = ebit * (1.0 - effective_tax)
        roic = _safe_ratio(nopat * 100.0, invested)
    if roic is not None and not (PLAUSIBLE_ROIC[0] <= roic <= PLAUSIBLE_ROIC[1]):
        roic = None

    if ev_revenue is None:
        logger.info("Peer %s: enterprise value not computable", symbol)
        return None

    return PeerMultiples(
        ticker=ticker,
        company_name=company_name,
        market=exchange,
        share_price=round(float(price), 4),
        shares_outstanding=round(float(shares), 2),
        market_cap=round(market_cap, 2),
        net_debt=round(net_debt, 2),
        enterprise_value=round(enterprise_value, 2),
        revenue_ttm=round(float(revenue), 2),
        # `is None` rather than truthiness. A falsy test is false for a
        # LEGITIMATELY NEGATIVE figure as well as for a missing one, so a peer
        # with negative trailing earnings was published as 0.0 — a different
        # company from the one that was measured. For return on invested capital
        # this published 0.0% where the real figure is negative, which reads as
        # "earns nothing" instead of "loses money", and is the very confusion
        # the invested-capital floor exists to avoid.
        ebitda_ttm=round(float(ebitda), 2) if ebitda is not None else 0.0,
        net_income_ttm=round(float(net_income), 2) if net_income is not None else 0.0,
        ev_revenue=round(ev_revenue, 4),
        ev_ebitda=round(ev_ebitda, 4) if ev_ebitda is not None else 0.0,
        pe_ratio=round(pe, 4) if pe is not None else 0.0,
        fcf_yield_pct=round(fcf_yield, 4) if fcf_yield is not None else 0.0,
        roic_pct=round(roic, 4) if roic is not None else 0.0,
        financials_period=str(annual.columns[0])[:10],
        balance_sheet_as_of=balance_as_of,
        price_as_of=price_as_of,
        price_source=price_source,
        shares_basis=shares_basis,
    )


def _filed_net_debt(company_id: str) -> Optional[tuple]:
    """Net debt for a peer from its own filed balance sheet, in absolute currency.

    Returns (net_debt, period_end_iso) or None when the peer has no filed
    statement, in which case the caller falls back to the market feed.

    The valuation bridge computes the target's net debt from the filed statement
    on a stated definition: the interest-bearing components listed in
    OPENING_BALANCE_KEYS, less cash and short-term investments, plus the minority
    interests and preferred stock that enterprise value also carries. A peer
    measured any other way is not comparable to it, and a median built from a mix
    of conventions is not a peer median.

    The absolute currency matters and is easy to get wrong. A market
    capitalisation is price times shares and is therefore in rupees or dollars,
    while the filed statements are held in the reporting units the model uses —
    crores for an Indian filer, millions for a US one. Adding one to the other
    without converting understates net debt ten-millionfold, which is the reason
    the resolver below scales back out before returning.

    Read from the compiled snapshot first, because that is what a fresh deploy
    with no database serves, and from the database second.
    """
    import json
    from pathlib import Path

    items: list = []
    as_of = ""

    cache_dir = Path(__file__).resolve().parents[1] / "data" / "cache"
    snapshot_path = cache_dir / f"{company_id}.json"
    if snapshot_path.exists():
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            historicals = (payload.get("model") or payload).get("historicals") or {}
            periods = [str(p) for p in (historicals.get("periods") or [])]
            if periods:
                latest = max(periods, key=lambda x: (len(x), x))
                for item in historicals.get("line_items") or []:
                    if str(item.get("period_label")) == latest:
                        items.append(item)
                counts: dict = {}
                for item in items:
                    stamp = item.get("period_end_date")
                    if stamp:
                        counts[str(stamp)] = counts.get(str(stamp), 0) + 1
                if counts:
                    as_of = max(counts, key=counts.get)
        except Exception as exc:
            logger.info("Peer %s: compiled snapshot unreadable (%s)", company_id, exc)
            items = []

    if not items:
        try:
            from backend.api.routes import _get_hist_model
            from backend.models.spec.historicals import modal_period_end

            model = _get_hist_model(company_id)
            if model is None or not model.periods:
                return None
            latest = model.periods[-1]
            for item in model.balance_sheet.line_items:
                value = item.values_by_period.get(latest)
                if value is not None:
                    items.append(
                        {
                            "canonical_key": item.canonical_key,
                            "value": value,
                            "period_end_date": item.period_end_dates_by_period.get(latest),
                        }
                    )
            filed = modal_period_end(
                i["period_end_date"]
                for i in items
                if isinstance(i.get("period_end_date"), date)
            )
            if filed:
                as_of = filed.isoformat()
        except Exception as exc:
            # Logged rather than swallowed: an unreadable statement silently
            # downgrades a peer to the feed's convention, so the benchmark becomes
            # a median of two bases and nothing says which peers moved.
            logger.info(
                "Peer %s: filed statement unreadable (%s) — falling back to the "
                "market feed, which is a different convention",
                company_id,
                exc,
            )
            return None

    if not items:
        return None

    balances: dict = {}
    for item in items:
        balances.setdefault(
            str(item.get("canonical_key")), float(item.get("value") or 0.0)
        )

    debt = sum(balances.get(key, 0.0) for key in OPENING_BALANCE_KEYS)
    # Every asset the target's bridge nets, and no more. Leaving non-current
    # investments out netted 22,251 of NVIDIA's away from a peer figure it applies
    # in full to the target, which is the same inconsistency in the other
    # direction: a benchmark that flatters one side of the comparison.
    liquid = (
        balances.get("canonical.bs.cash_and_bank", 0.0)
        + balances.get("canonical.bs.current_investments", 0.0)
        + balances.get("canonical.bs.non_current_investments", 0.0)
    )
    claims = (
        balances.get("canonical.bs.minority_interest", 0.0)
        + balances.get("canonical.bs.preferred_stock", 0.0)
    )
    if not debt and not liquid:
        return None
    from backend.data.bridge_inputs import UNIT_DIVISORS
    from backend.models.spec.metadata import get_metadata_for_company

    try:
        meta = get_metadata_for_company(company_id)
        divisor = UNIT_DIVISORS.get((meta.currency, meta.units))
    except Exception:
        return None
    if not divisor:
        return None

    return (debt + claims - liquid) * divisor, as_of


def _company_id_for(symbol: str) -> str:
    """Map a market symbol back to a company id for the balance-sheet snapshot.

    The snapshot resolver works from a company id, so the roster symbol is
    converted to the `{ticker}_{exchange}` form the rest of the platform uses.

    Only the two markets the platform actually onboards are mapped. Every other
    suffix used to fall through to `_us`, so a peer listed in London, Tokyo,
    Hong Kong or Frankfurt resolved to a company id that does not exist, the
    snapshot came back empty, and the peer's net debt was published as exactly
    0.0 — a figure that reads as "carries no debt" rather than "could not be
    sourced", and one that then flows into an enterprise value and a multiple.

    An unmappable market returns an empty string, and the caller treats that as
    unavailable rather than as zero.
    """
    base = symbol.split(".")[0].upper()
    suffix = symbol[len(base):] if symbol.startswith(base) else ""
    if suffix == ".NS":
        return f"{base.lower()}_{base.lower()}"
    if suffix == "":
        return f"{base.lower()}_us"
    return ""
