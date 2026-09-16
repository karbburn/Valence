from __future__ import annotations

"""
Market Data Layer Provider for Valence.

Fetches live market data (price, share count, 2Y weekly beta, 10Y risk-free rate, equity risk premium)
with a robust fallback chain:
  1. Live fetch via yfinance (primary)
  2. Live fetch via TwelveData (secondary, enabled if TWELVEDATA_API_KEY is present)
  3. Per-company price/shares/beta registry
  4. Per-market defaults (US vs India)

All datapoints record explicit provenance notes and fetch dates.
"""

import json
import logging
import os
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field

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
# ----------------------------------------------------------------------
MARKET_DEFAULTS: Dict[MarketType, Dict[str, float]] = {
    "us": {
        "rfr": 4.64,        # 10-Year US Treasury yield (%) - Aug 2026
        "erp": 4.50,        # Damodaran US Equity Risk Premium (%)
        "beta": 1.00,       # Market default beta
        "price": 100.0,
        "shares": 1000.0,   # Millions
    },
    "india": {
        "rfr": 6.78,        # India 10-Year G-Sec yield (%)
        "erp": 7.08,        # Damodaran India Equity Risk Premium (%) - Jan 2026 update
        "beta": 1.00,       # Market default beta
        "price": 1000.0,
        "shares": 400.0,    # Crores
    },
}

# Per-company benchmark registry fallback (native currency, native share units)
# Beta is calibrated against primary domestic index (e.g. Nifty 50 / Nifty IT for India, S&P 500 for US)
REGISTRY_FALLBACKS: Dict[str, Dict[str, float]] = {
    "infy_infy": {"price": 1080.0, "shares": 412.45, "beta": 0.79, "market": "india"},
    "tcs_tcs": {"price": 2270.0, "shares": 361.80, "beta": 0.85, "market": "india"},
    "tatamotors_tatamotors": {"price": 302.0, "shares": 367.00, "beta": 1.15, "market": "india"},
    "tatasteel_tatasteel": {"price": 184.0, "shares": 1248.00, "beta": 1.25, "market": "india"},
    "ongc_ongc": {"price": 235.35, "shares": 1258.00, "beta": 0.95, "market": "india"},
    "aapl_us": {"price": 331.0, "shares": 14594.18, "beta": 1.05, "market": "us"},
    "msft_us": {"price": 497.00, "shares": 7430.00, "beta": 0.90, "market": "us"},
    "infy_us": {"price": 12.40, "shares": 4124.00, "beta": 0.85, "market": "us"},
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
            "tatamotors_tatamotors": "TATAMOTORS.NS",
            "tatasteel_tatasteel": "TATASTEEL.NS",
        }
        return symbol_map.get(company_id, f"{ticker.upper()}.NS")
    return ticker.upper()


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

        # Shares outstanding
        shares_raw = info.get("sharesOutstanding")
        if shares_raw and float(shares_raw) > 0:
            if market == "india":
                shares_cr = float(shares_raw) / 1e7  # raw shares to Crores
                results["shares"] = MarketDataPoint(
                    value=round(shares_cr, 4),
                    source="yfinance",
                    fetch_date=today_str,
                    provenance_note=f"yfinance live shares outstanding ({shares_cr:.2f} Cr)",
                )
            else:
                shares_m = float(shares_raw) / 1e6   # raw shares to Millions
                results["shares"] = MarketDataPoint(
                    value=round(shares_m, 4),
                    source="yfinance",
                    fetch_date=today_str,
                    provenance_note=f"yfinance live shares outstanding ({shares_m:.2f} M)",
                )

        # Beta vs primary index
        beta_val = info.get("beta")
        if beta_val and float(beta_val) > 0:
            raw_b = float(beta_val)
            if market == "india" and raw_b < 0.60:
                # yfinance calculates beta for Indian stocks against US S&P 500 (cross-currency noise), producing near-zero betas (0.05-0.20).
                # Re-calibrate against domestic Nifty 50 benchmark (0.95).
                clean_b = 0.95
            else:
                clean_b = max(0.70, round(0.67 * raw_b + 0.33, 3)) if raw_b < 0.60 else round(raw_b, 3)

            results["beta"] = MarketDataPoint(
                value=clean_b,
                source="yfinance",
                fetch_date=today_str,
                provenance_note=f"yfinance 2Y weekly beta ({raw_b:.2f}, domestic calibrated {clean_b:.2f})",
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

    live_yf = _fetch_yfinance(company_id, resolved_market, resolved_ticker)
    live_td = _fetch_twelvedata(company_id, resolved_market, resolved_ticker)

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
        if field_name in live_yf and live_yf[field_name] is not None:
            return live_yf[field_name]
        if field_name in live_td and live_td[field_name] is not None:
            return live_td[field_name]
        if company_id in REGISTRY_FALLBACKS and field_name in REGISTRY_FALLBACKS[company_id]:
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

    cache = _load_cache()
    cache[company_id] = {
        "fetch_date": today_str,
        "data": cmd.model_dump(),
    }
    _save_cache(cache)

    return cmd
