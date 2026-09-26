from __future__ import annotations

"""
Market Data Layer Provider for Valence.

Fetches market data (price, share count, 2Y weekly beta, 10Y risk-free rate, ERP)
with a fallback chain. Price is NEVER hardcoded — it always comes from a free
quote source and is refreshed daily (see scripts/refresh_market_data.py):

  1. yfinance daily history close (primary — a real exchange close, and the
     engine's valuation basis is the previous close anyway)
  2. Yahoo chart API via plain HTTP (independent code path, works when the
     yfinance wrapper is rate-limited; yfinance .info returning {} is exactly
     how NVDA once fell through to the $100 placeholder)
  3. yfinance .info quote (intraday/last-trade; used only if 1 and 2 fail)
  4. TwelveData (secondary, enabled if TWELVEDATA_API_KEY is present)
  5. Last-known-good stale cache — original quote date preserved and source
     prefixed stale_cache: — the UI labels it "Stale" in amber
  6. Per-market generic placeholder ($100 / Rs.1000), last resort, never
     cached, UI labels it "Benchmark"

Quote dates matter as much as values: a price datapoint carries the trading
date of the bar it came from, NOT the date we fetched it. Otherwise a weekend
request shows "As of <today>" for a Friday close, which is a quiet lie (and
is what made a stale ₹1080 look like a live quote).

The per-company registry below holds ONLY slow-moving structural data
(shares outstanding, calibrated beta). It deliberately carries NO price —
a hardcoded price rots the next trading day.

All datapoints record explicit provenance notes and dates.
"""

import json
import logging
import os
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from backend.data.providers.share_count import resolve_share_count

# Suppress urllib3/requests dependency warnings if present at import time
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        import yfinance as yf
    except ImportError:
        yf = None

    try:
        import requests
    except ImportError:
        requests = None

logger = logging.getLogger(__name__)


# Load local .env file if present
def _load_env_file() -> None:
    for search_dir in [Path.cwd(), Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[2]]:
        env_path = search_dir / ".env"
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k:
                                os.environ[k] = v
            except Exception:
                pass
            break

_load_env_file()

MarketType = Literal["india", "us"]

# Local cache directory setup
PROVIDERS_DIR = Path(__file__).resolve().parent
CACHE_FILE = PROVIDERS_DIR.parent / "cache" / "market_data_cache.json"


class MarketDataPoint(BaseModel):
    value: float
    source: str
    fetch_date: str = Field(default_factory=lambda: date.today().isoformat())
    provenance_note: str


class CompanyMarketData(BaseModel):
    company_id: str
    ticker: str
    market: MarketType
    price: MarketDataPoint
    shares_outstanding: MarketDataPoint  # Crores for India, Millions for US
    beta: MarketDataPoint
    risk_free_rate: MarketDataPoint
    equity_risk_premium: MarketDataPoint
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ----------------------------------------------------------------------
# Registry & Per-Market Defaults
#
# REGISTRY holds ONLY structural, slow-moving data (shares, beta).
# NEVER add "price" here — price is a daily quote and must come from live
# free sources (yfinance history close / Stooq / TwelveData) or stale cache.
# A hardcoded price is stale the next trading day.
# ----------------------------------------------------------------------
MARKET_DEFAULTS: Dict[MarketType, Dict[str, float]] = {
    "us": {
        "rfr": 4.64,        # 10-Year US Treasury yield (%) - Aug 2026
        "erp": 4.50,        # Damodaran US Equity Risk Premium (%)
        "beta": 1.00,       # Market default beta
        "price": 100.0,     # LAST-RESORT placeholder only: served only when every
        "shares": 1000.0,   # Millions     live source AND stale cache miss; never cached,
    },                                  # UI labels it "Benchmark", not live.
    "india": {
        "rfr": 6.78,        # India 10-Year G-Sec yield (%)
        "erp": 7.08,        # Damodaran India Equity Risk Premium (%) - Jan 2026 update
        "beta": 1.00,       # Market default beta
        "price": 1000.0,    # LAST-RESORT placeholder only (see above)
        "shares": 400.0,    # Crores
    },
}

# Structural fallback registry: shares (M for US, Cr for India) + calibrated
# beta vs the primary domestic index. NO PRICE — see module docstring.
# Shares/beta move slowly; refresh via scripts/refresh_market_fallbacks.py.
REGISTRY_FALLBACKS: Dict[str, Dict[str, float]] = {
    "infy_infy": {"shares": 412.45, "beta": 0.79, "market": "india"},
    "tcs_tcs": {"shares": 361.80, "beta": 0.85, "market": "india"},
    "tatamotors_tatamotors": {"shares": 367.00, "beta": 1.15, "market": "india"},
    "tatasteel_tatasteel": {"shares": 1248.00, "beta": 1.25, "market": "india"},
    "ongc_ongc": {"shares": 1258.00, "beta": 0.95, "market": "india"},
    "aapl_us": {"shares": 14594.18, "beta": 1.05, "market": "us"},
    "msft_us": {"shares": 7430.00, "beta": 0.90, "market": "us"},
    "infy_us": {"shares": 4124.00, "beta": 0.85, "market": "us"},
    "nvda_us": {"shares": 24147.00, "beta": 1.67, "market": "us"},
    "googl_us": {"shares": 5867.16, "beta": 1.04, "market": "us"},
    "amzn_us": {"shares": 10786.31, "beta": 1.15, "market": "us"},
    "tsm_us": {"shares": 5186.47, "beta": 1.10, "market": "us"},
}


def _yf_ticker_for(company_id: str, market: MarketType, ticker: str) -> str:
    """Map company identifier to yfinance ticker symbol."""
    if market == "us":
        return ticker.upper()
    if market == "india":
        if ticker.upper().endswith(".NS") or ticker.upper().endswith(".BO"):
            return ticker.upper()
        symbol_map = {
            "infy_infy": "INFY.NS",
            "tcs_tcs": "TCS.NS",
            "tatasteel_tatasteel": "TATASTEEL.NS",
        }
        return symbol_map.get(company_id, f"{ticker.upper()}.NS")
    return ticker.upper()


# Corporate actions retire tickers. When the primary symbol stops resolving, try
# these before giving up: a demerger/restructuring renames the listed entity but
# leaves the company_id (and the cached financials) pointing at the old symbol,
# which would otherwise pin the model to a stale price indefinitely.
# Tata Motors demerged; the listed passenger-vehicle entity now trades as TMPV.
TICKER_REDIRECTS: Dict[str, str] = {
    "tatamotors_tatamotors": "TMPV.NS",
}


def _shares_from_balance_sheet(ticker_obj, market: str) -> tuple[Optional[float], str]:
    """Ordinary shares outstanding from the filed balance sheet, in model units.

    Returns (value_in_model_units, period_label). The quarterly statement is
    preferred because it is the most recently filed one; the annual is the
    fallback.
    """
    divisor = 1e7 if market == "india" else 1e6
    labels = ("Ordinary Shares Number", "Share Issued", "Common Stock Shares Outstanding")
    for attr in ("quarterly_balance_sheet", "balance_sheet"):
        try:
            frame = getattr(ticker_obj, attr, None)
        except Exception:
            continue
        if frame is None or len(getattr(frame, "columns", [])) == 0:
            continue
        column = frame.columns[0]
        for label in labels:
            if label not in frame.index:
                continue
            try:
                value = float(frame.loc[label, column])
            except Exception:
                continue
            if value != value or value <= 0:
                continue
            period = str(column)[:10]
            return value / divisor, f"{label} at {period}"
    return None, ""


def _fetch_yfinance(company_id: str, market: MarketType, ticker: str) -> Dict[str, Optional[MarketDataPoint]]:
    """Fetch live data from yfinance."""
    if yf is None:
        return {}

    yf_symbol = _yf_ticker_for(company_id, market, ticker)
    today_str = date.today().isoformat()
    results: Dict[str, Optional[MarketDataPoint]] = {}

    try:
        t = yf.Ticker(yf_symbol)
        info = t.info or {}

        # Price
        price_val = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        if price_val and float(price_val) > 0:
            results["price"] = MarketDataPoint(
                value=float(price_val),
                source="yfinance",
                fetch_date=today_str,
                provenance_note=f"yfinance live price for {yf_symbol}",
            )

        # Shares outstanding.
        #
        # Two published counts routinely disagree, and for opposite reasons: a
        # multi-class issuer's provider summary reports ONE class, while a
        # depositary listing's filed count is in ORDINARY shares against a price
        # quoted per RECEIPT. Adjudicating those needs the shape of the
        # disagreement, not a fixed preference, so it is done in one place —
        # `resolve_share_count` — which the peer path also uses, so the two
        # cannot drift apart again.
        shares_from_bs, shares_basis = _shares_from_balance_sheet(t, market)
        shares_provider = None
        try:
            raw = info.get("sharesOutstanding")
            if raw and float(raw) > 0:
                shares_provider = float(raw) / (1e7 if market == "india" else 1e6)
        except (TypeError, ValueError):
            shares_provider = None

        chosen, note = resolve_share_count(
            shares_from_bs,
            shares_provider,
            filed_basis=shares_basis,
            provider_basis="provider shares outstanding",
        )

        if chosen and chosen > 0:
            unit = "Cr" if market == "india" else "M"
            results["shares"] = MarketDataPoint(
                value=round(chosen, 4),
                source="yfinance",
                fetch_date=today_str,
                provenance_note=f"{note} = {chosen:,.2f} {unit}",
            )

        # Beta vs primary index
        #
        # The RAW provider beta is published here, unadjusted. Blume adjustment
        # (0.67·b + 0.33) is applied exactly once, in the valuation engine
        # (backend/valuation/wacc.py). Applying it in both places composes to
        # 0.4489·b + 0.5511 — an over-shrink that inflates cost of equity and
        # understates the implied share price. The only transformation that
        # belongs here is the India cross-currency recalibration below, because
        # that repairs a *wrong* beta rather than shrinking a good one.
        beta_val = info.get("beta")
        if beta_val and float(beta_val) > 0:
            raw_b = float(beta_val)
            if market == "india" and raw_b < 0.60:
                # yfinance calculates beta for Indian stocks against US S&P 500 (cross-currency noise), producing near-zero betas (0.05-0.20).
                # Re-calibrate against domestic Nifty 50 benchmark (0.95).
                clean_b = 0.95
                basis = "domestic Nifty 50 recalibration"
            else:
                clean_b = round(raw_b, 3)
                basis = "raw provider beta"

            results["beta"] = MarketDataPoint(
                value=clean_b,
                source="yfinance",
                fetch_date=today_str,
                provenance_note=f"yfinance 2Y weekly beta ({raw_b:.2f}, {basis} {clean_b:.2f})",
            )

        # US 10Y Risk-Free Rate via ^TNX
        if market == "us":
            try:
                tnx = yf.Ticker("^TNX")
                rfr_val = tnx.info.get("regularMarketPrice") or tnx.info.get("previousClose")
                if rfr_val and float(rfr_val) > 0:
                    results["rfr"] = MarketDataPoint(
                        value=round(float(rfr_val), 4),
                        source="yfinance",
                        fetch_date=today_str,
                        provenance_note=f"yfinance live 10-Year US Treasury yield ^TNX ({rfr_val:.2f}%)",
                    )
            except Exception as e:
                logger.debug("Failed to fetch ^TNX: %s", e)

    except Exception as e:
        logger.warning("yfinance fetch failed for %s (%s): %s", company_id, yf_symbol, e)

    return results


def _last_close_point(yf_symbol: str, closes: List, stamps: List) -> Optional[MarketDataPoint]:
    """Build a price datapoint from the last usable close, stamped with ITS bar date.

    The datapoint date is the trading date of the bar, not the request date, so
    a Saturday request shows Friday's close — never a fabricated "today".
    """
    for i in range(len(closes) - 1, -1, -1):
        raw = closes[i]
        try:
            close = float(raw)
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        bar_date = None
        if i < len(stamps) and stamps[i]:
            bar_date = datetime.fromtimestamp(int(stamps[i])).date().isoformat()
        return MarketDataPoint(
            value=round(close, 2),
            source="yfinance_history",
            fetch_date=bar_date or date.today().isoformat(),
            provenance_note=f"yfinance daily close for {yf_symbol} ({bar_date or 'latest'})",
        )
    return None


def _fetch_yfinance_history(company_id: str, market: MarketType, ticker: str) -> Dict[str, Optional[MarketDataPoint]]:
    """Daily-close price via yfinance history — free, no key, more reliable than .info.

    .info is frequently rate-limited / empty on cloud hosts (the original cause
    of the NVDA $100 bug: .info returned nothing, the chain fell to the $100
    default). history(period="5d") hits a different Yahoo endpoint and usually
    succeeds when .info fails, and it returns a real exchange close — which is
    the engine's valuation basis (previous close), not an intraday print.
    """
    if yf is None:
        return {}
    yf_symbol = _yf_ticker_for(company_id, market, ticker)
    try:
        hist = yf.Ticker(yf_symbol).history(period="5d", auto_adjust=False)
        if hist is None or len(hist) == 0:
            return {}
        close_col = "Close" if "Close" in hist.columns else None
        if close_col is None:
            return {}
        pt = _last_close_point(
            yf_symbol,
            list(hist[close_col].values),
            list(hist.index.map(lambda ts: ts.timestamp()).values),
        )
        return {"price": pt} if pt is not None else {}
    except Exception as e:
        logger.debug("yfinance history fetch failed for %s (%s): %s", company_id, yf_symbol, e)
    return {}


def _fetch_yahoo_chart(company_id: str, market: MarketType, ticker: str) -> Dict[str, Optional[MarketDataPoint]]:
    """Daily-close price straight from the Yahoo chart API over plain HTTP.

    Independent code path from the yfinance wrapper, so one being
    rate-limited or broken does not take the price down with it. Free, no key.
    """
    if requests is None:
        return {}
    symbol = _yf_ticker_for(company_id, market, ticker)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Valence/1.0)"}
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            resp = requests.get(
                f"https://{host}/v8/finance/chart/{symbol}",
                params={"range": "5d", "interval": "1d"},
                headers=headers,
                timeout=8,
            )
            if resp.status_code != 200:
                continue
            payload = (resp.json() or {}).get("chart", {}).get("result") or []
            if not payload:
                continue
            result = payload[0]
            closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            pt = _last_close_point(symbol, list(closes), list(result.get("timestamp") or []))
            if pt is not None:
                pt.source = "yahoo_chart"
                pt.provenance_note = f"Yahoo chart API daily close for {symbol} ({pt.fetch_date})"
                return {"price": pt}
        except Exception as e:
            logger.debug("Yahoo chart fetch failed for %s (%s): %s", company_id, symbol, e)
    return {}


def _fetch_twelvedata(company_id: str, market: MarketType, ticker: str) -> Dict[str, Optional[MarketDataPoint]]:
    """Secondary live fetch via TwelveData if API key is present."""
    api_key = os.getenv("TWELVEDATA_API_KEY")
    if not api_key or requests is None:
        return {}

    today_str = date.today().isoformat()
    results: Dict[str, Optional[MarketDataPoint]] = {}
    symbol = ticker.upper()

    try:
        url = f"https://api.twelvedata.com/quote?symbol={symbol}&apikey={api_key}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            price_val = data.get("close") or data.get("price")
            if price_val:
                results["price"] = MarketDataPoint(
                    value=float(price_val),
                    source="twelvedata",
                    fetch_date=today_str,
                    provenance_note=f"TwelveData API price for {symbol}",
                )
    except Exception as e:
        logger.debug("TwelveData fetch failed for %s: %s", company_id, e)

    return results


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(cache_data: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        logger.warning("Failed to save market data cache: %s", e)


def get_company_market_data(
    company_id: str,
    ticker: Optional[str] = None,
    market: Optional[MarketType] = None,
    force_refresh: bool = False,
) -> CompanyMarketData:
    """Retrieve market data for company_id following the full fallback chain."""
    reg_entry = REGISTRY_FALLBACKS.get(company_id, {})
    resolved_market: MarketType = market or reg_entry.get("market") or ("us" if company_id.endswith("_us") else "india")
    resolved_ticker: str = ticker or company_id.split("_")[0].upper()

    today_str = date.today().isoformat()

    if not force_refresh:
        cache = _load_cache()
        cached = cache.get(company_id)
        if cached and cached.get("fetch_date") == today_str:
            try:
                return CompanyMarketData(**cached["data"])
            except Exception:
                pass

    def _live_price(*sources: Dict[str, Optional[MarketDataPoint]]) -> Optional[MarketDataPoint]:
        for src in sources:
            pt = src.get("price")
            if pt is not None and pt.value and float(pt.value) > 0:
                return pt
        return None

    live_td = _fetch_twelvedata(company_id, resolved_market, resolved_ticker)

    def _price_attempts(tkr: str) -> tuple:
        """Fetch every price source for a symbol, in chain order."""
        hist = _fetch_yfinance_history(company_id, resolved_market, tkr)
        chart = _fetch_yahoo_chart(company_id, resolved_market, tkr)
        quote = _fetch_yfinance(company_id, resolved_market, tkr)
        # Daily exchange close first (.info is an intraday/last-trade print and
        # is the least reliable field in the chain), then the HTTP path.
        point = _live_price(hist, chart, live_td, quote)
        return point, (hist, chart, quote)

    live_price_pt, (live_yf_hist, live_yahoo, live_yf) = _price_attempts(resolved_ticker)

    if live_price_pt is None:
        # The listed symbol may have been retired by a corporate action. Try the
        # known successor before falling back to a stale cache, otherwise a
        # demerger leaves the model pinned to a months-old price forever.
        redirect = TICKER_REDIRECTS.get(company_id)
        if redirect and redirect.upper() != resolved_ticker.upper():
            redirected, _ = _price_attempts(redirect)
            if redirected is not None:
                logger.warning(
                    "Primary ticker for %s no longer resolves; using successor %s",
                    company_id, redirect,
                )
                # A successor ticker is NOT the same company as the cached
                # financials (a demerger splits one issuer into several). Flag it
                # so the UI can warn that the vs-market % compares a successor
                # price against pre-action financials, rather than quietly
                # printing a nonsense upside.
                redirected = redirected.model_copy(update={
                    "source": f"{redirected.source}:successor_ticker",
                    "provenance_note": (
                        f"{redirected.provenance_note} — CAUTION: {resolved_ticker} was retired by a "
                        f"corporate action; this is the successor entity {redirect.split('.')[0]}, so the "
                        "quote may not be comparable with this model's historical financials"
                    ),
                })
                live_price_pt = redirected
                resolved_ticker = redirect.split(".")[0]

    live_price_ok = live_price_pt is not None
    if not live_price_ok:
        # Live quote failed (yfinance blocked/rate-limited, no TwelveData key).
        # Prefer the last-known-good cached quote — even if stale — over the
        # registry benchmark, and never silently serve the $100/$1000 market
        # default stamped with today's date. Preserve the original fetch_date
        # so the UI can show "As of <stale date> · Stale" honestly.
        try:
            stale_cache = _load_cache()
            stale_entry = stale_cache.get(company_id)
            if stale_entry and isinstance(stale_entry.get("data"), dict):
                stale_data = dict(stale_entry["data"])
                stale_price = (stale_data.get("price") or {}).get("value")
                if stale_price and float(stale_price) > 0:
                    try:
                        stale_cmd = CompanyMarketData(**stale_data)
                        orig_date = stale_entry.get("fetch_date") or stale_cmd.price.fetch_date
                        stale_cmd.price.provenance_note = (
                            f"{stale_cmd.price.provenance_note} (stale — live fetch failed, last close {orig_date})"
                        )
                        stale_cmd.price.source = f"stale_cache:{stale_cmd.price.source}"
                        logger.warning(
                            "Live price fetch failed for %s; serving stale cached price %.2f from %s",
                            company_id, float(stale_price), orig_date,
                        )
                        return stale_cmd
                    except Exception:
                        pass
        except Exception:
            pass

    def resolve_field(field_name: str, default_val: float, unit_note: str) -> MarketDataPoint:
        # Domestic market beta calibration vs local index takes priority over cross-border yfinance beta
        if field_name == "beta" and company_id in REGISTRY_FALLBACKS and "beta" in REGISTRY_FALLBACKS[company_id]:
            val = REGISTRY_FALLBACKS[company_id]["beta"]
            return MarketDataPoint(
                value=val,
                source="registry",
                fetch_date=today_str,
                provenance_note=f"Per-company registry benchmark beta vs primary index ({val})",
            )
        # PRICE: free quote sources only (yfinance daily close -> Yahoo chart
        # API -> TwelveData -> yfinance .info last). No registry price, ever.
        if field_name == "price":
            if live_price_pt is not None:
                return live_price_pt
        else:
            if field_name in live_yf and live_yf[field_name] is not None:
                return live_yf[field_name]
            if field_name in live_td and live_td[field_name] is not None:
                return live_td[field_name]
        if field_name != "price" and company_id in REGISTRY_FALLBACKS and field_name in REGISTRY_FALLBACKS[company_id]:
            val = REGISTRY_FALLBACKS[company_id][field_name]
            return MarketDataPoint(
                value=val,
                source="registry",
                fetch_date=today_str,
                provenance_note=f"Per-company registry benchmark for {company_id} ({unit_note})",
            )
        market_def = MARKET_DEFAULTS[resolved_market]
        val = market_def.get(field_name, default_val)
        return MarketDataPoint(
            value=val,
            source="market_default",
            fetch_date=today_str,
            provenance_note=f"{resolved_market.upper()} market default for {field_name} ({unit_note})",
        )

    p_dp = resolve_field("price", MARKET_DEFAULTS[resolved_market]["price"], f"{'USD' if resolved_market == 'us' else 'INR'}/share")
    s_dp = resolve_field("shares", MARKET_DEFAULTS[resolved_market]["shares"], f"{'M' if resolved_market == 'us' else 'Cr'} shares")
    b_dp = resolve_field("beta", MARKET_DEFAULTS[resolved_market]["beta"], "beta vs index")
    rfr_dp = resolve_field("rfr", MARKET_DEFAULTS[resolved_market]["rfr"], "10Y sovereign yield %")
    erp_dp = resolve_field("erp", MARKET_DEFAULTS[resolved_market]["erp"], "Equity Risk Premium %")

    cmd = CompanyMarketData(
        company_id=company_id,
        ticker=resolved_ticker,
        market=resolved_market,
        price=p_dp,
        shares_outstanding=s_dp,
        beta=b_dp,
        risk_free_rate=rfr_dp,
        equity_risk_premium=erp_dp,
    )

    if p_dp.source == "market_default":
        # Never persist the generic $100/$1000 placeholder over a good cached
        # quote — that is how a one-off outage permanently poisons the price.
        logger.warning(
            "No live/registry/cached price for %s; serving %s market default %.2f (not cached)",
            company_id, resolved_market, p_dp.value,
        )
        return cmd

    cache = _load_cache()
    cache[company_id] = {
        "fetch_date": today_str,
        "data": cmd.model_dump(),
    }
    _save_cache(cache)

    return cmd
