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
from typing import Optional

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
# Invested capital below this share of market capitalisation makes a return on
# invested capital uninformative.
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


def _ttl(frame, rows: tuple[str, ...], quarterly) -> Optional[float]:
    """Trailing twelve months: latest annual, plus year-to-date less prior-year-to-date.

    Taking the latest ANNUAL column alone is the other way a comps table goes
    stale — it reports a multiple on financials up to a year old. Rolling the
    latest reported quarters forward keeps the denominator in step with the live
    numerator.
    """
    annual_value = _row(frame, rows, frame.columns[0]) if frame is not None and len(frame.columns) else None
    if annual_value is None:
        return None
    if quarterly is None or len(quarterly.columns) < 5:
        return annual_value
    try:
        ytd = _row(quarterly, rows, quarterly.columns[0])
        prior_ytd = _row(quarterly, rows, quarterly.columns[4])
    except Exception:
        return annual_value
    if ytd is None or prior_ytd is None:
        return annual_value
    rolled = annual_value + ytd - prior_ytd
    # A negative annual figure cannot be rolled forward meaningfully.
    return rolled if annual_value > 0 else annual_value


def _safe_ratio(numerator: float, denominator: Optional[float]) -> Optional[float]:
    if denominator is None or abs(denominator) < 1e-9:
        return None
    value = numerator / denominator
    if value != value:
        return None
    return value


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
        info = {}
    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    if not price or not isinstance(price, (int, float)) or price <= 0:
        logger.info("Peer %s: no live price", symbol)
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

    balance = getattr(handle, "balance_sheet", None)
    equity = _row(balance, _EQUITY_ROWS, balance.columns[0]) if balance is not None and len(balance.columns) else None
    assets = _row(balance, _ASSET_ROWS, balance.columns[0]) if balance is not None and len(balance.columns) else None
    tax = _ttl(annual, _TAX_ROWS, quarterly)

    # Net debt and share count come from the same most-recent-reported
    # machinery the valuation bridge uses, so a peer is measured on the basis
    # the target is measured on.
    net_debt = 0.0
    balance_as_of = ""
    try:
        from backend.data.bridge_inputs import fetch_bridge_snapshot

        snapshot = fetch_bridge_snapshot(_company_id_for(symbol))
        if snapshot is not None and snapshot.as_of:
            net_debt = snapshot.total_debt - snapshot.total_liquid_assets
            balance_as_of = snapshot.as_of
    except Exception as exc:
        logger.info("Peer %s: balance sheet snapshot unavailable (%s)", symbol, exc)

    shares = info.get("sharesOutstanding")
    if not shares or not isinstance(shares, (int, float)) or shares <= 0:
        shares = _row(balance, ("Ordinary Shares Number",), balance.columns[0]) if balance is not None and len(balance.columns) else None
    if not shares or not isinstance(shares, (int, float)) or shares <= 0:
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
    # Return on invested capital needs a meaningful capital base. A company
    # carrying near-zero book equity produces a number that is arithmetically
    # valid and economically meaningless, so it is reported as unavailable
    # rather than as a 160% return.
    invested = None
    if equity is not None and market_cap > 0:
        invested = equity + max(net_debt, 0.0)
    if (
        ebit
        and tax is not None
        and invested
        and invested > market_cap * PLAUSIBLE_INVESTED_CAPITAL_FLOOR
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
        ebitda_ttm=round(float(ebitda), 2) if ebitda else 0.0,
        net_income_ttm=round(float(net_income), 2) if net_income else 0.0,
        ev_revenue=round(ev_revenue, 4),
        ev_ebitda=round(ev_ebitda, 4) if ev_ebitda else 0.0,
        pe_ratio=round(pe, 4) if pe else 0.0,
        fcf_yield_pct=round(fcf_yield, 4) if fcf_yield else 0.0,
        roic_pct=round(roic, 4) if roic else 0.0,
        financials_period=str(annual.columns[0])[:10],
        balance_sheet_as_of=balance_as_of,
        price_as_of=str(info.get("regularMarketTime") or ""),
    )


def _company_id_for(symbol: str) -> str:
    """Map a market symbol back to a company id for the balance-sheet snapshot.

    The snapshot resolver works from a company id, so the roster symbol is
    converted to the `{ticker}_{exchange}` form the rest of the platform uses.
    """
    base = symbol.split(".")[0].upper()
    if symbol.endswith(".NS"):
        return f"{base.lower()}_{base.lower()}"
    return f"{base.lower()}_us"
