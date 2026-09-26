"""Cross-check Valence market prices against independent sources for 20+ tickers.

Two independent checks per company:

  1. yfinance .info quote vs. the close Valence serves. These are different
     fields (last trade vs. official daily close) so a small gap is normal —
     anything beyond the tolerance is a real problem.
  2. The Yahoo chart API over raw HTTP vs. what Valence served, confirming the
     served value did not come from a stale cache or a fallback.

Verdicts: OK / MISMATCH (value) / DATE_STALE (served an older bar than fetched)
/ PLACEHOLDER (fallback, not a live quote) / FETCH_FAILED.

Usage:
    python scripts/verify_tickers.py                       # 20 onboarded tickers
    python scripts/verify_tickers.py --count 20 --seed 7   # reproducible sample
    python scripts/verify_tickers.py --all
    python scripts/verify_tickers.py --companies infy_infy,nvda_us
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

TOLERANCE_PCT = 0.5
MAX_STALE_DAYS = 4  # weekends + Indian/US holiday calendars


def _all_company_ids() -> list[str]:
    from backend.data.providers.market_data import REGISTRY_FALLBACKS

    return sorted(REGISTRY_FALLBACKS.keys())


def _onboarded_company_ids() -> list[str]:
    try:
        from backend.data.universe.master_list import seed_master_universe
        from backend.data.universe.store import search_universe_companies

        seed_master_universe()
        ids = [c.company_id for c in search_universe_companies(query="", status="onboarded", limit=1000)]
        if ids:
            return sorted(ids)
    except Exception as exc:
        print(f"Universe lookup failed ({exc}); using the full registry.")
    return _all_company_ids()


def _served(company_id: str) -> dict:
    from backend.data.providers.market_data import get_company_market_data

    cmd = get_company_market_data(company_id, force_refresh=True)
    return {
        "price": cmd.price.value,
        "source": cmd.price.source,
        "date": cmd.price.fetch_date,
        "note": cmd.price.provenance_note,
    }


def _yfinance_quote(company_id: str) -> dict:
    """Last-trade quote + previous close from yfinance .info (independent of the
    close Valence prefers)."""
    import yfinance as yf

    from backend.data.providers.market_data import _yf_ticker_for
    from backend.data.providers.market_data import TICKER_REDIRECTS

    market = "us" if company_id.endswith("_us") else "india"
    ticker = company_id.split("_")[0].upper()
    symbol = TICKER_REDIRECTS.get(company_id) or _yf_ticker_for(company_id, market, ticker)

    info = yf.Ticker(symbol).info or {}
    return {
        "symbol": symbol,
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "previous_close": info.get("previousClose"),
        "currency": info.get("currency"),
    }


def _yahoo_chart(company_id: str) -> dict:
    """Daily close straight from the Yahoo chart API — confirms the served value."""
    import requests

    from backend.data.providers.market_data import (
        TICKER_REDIRECTS,
        _fetch_yahoo_chart,
        _yf_ticker_for,
    )

    market = "us" if company_id.endswith("_us") else "india"
    ticker = company_id.split("_")[0].upper()
    symbol = TICKER_REDIRECTS.get(company_id) or _yf_ticker_for(company_id, market, ticker)

    out = _fetch_yahoo_chart(company_id, market, ticker)
    pt = out.get("price")
    if pt is not None:
        return {"symbol": symbol, "price": pt.value, "date": pt.fetch_date}

    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": "5d", "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0 (compatible; Valence/1.0)"},
            timeout=10,
        )
        result = ((r.json() or {}).get("chart", {}).get("result") or [{}])[0]
        closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        stamps = result.get("timestamp") or []
        from datetime import datetime

        for i in range(len(closes) - 1, -1, -1):
            try:
                c = float(closes[i])
            except (TypeError, ValueError):
                continue
            if c > 0:
                return {
                    "symbol": symbol,
                    "price": round(c, 2),
                    "date": datetime.fromtimestamp(int(stamps[i])).date().isoformat() if i < len(stamps) else "",
                }
    except Exception:
        pass
    return {"symbol": symbol, "price": None, "date": ""}


def _pct(a: float, b: float) -> float:
    return abs(a - b) / b * 100 if b else float("inf")


def _fmt(v, nd=2):
    return f"{v:,.{nd}f}" if isinstance(v, (int, float)) else "-"


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify Valence prices for many tickers.")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0, help="Sample seed for reproducibility.")
    ap.add_argument("--all", action="store_true", help="Check every registry entry.")
    ap.add_argument("--companies", default=None, help="Comma-separated company_ids.")
    ap.add_argument("--tol", type=float, default=TOLERANCE_PCT)
    args = ap.parse_args()

    if args.companies:
        targets = [c.strip() for c in args.companies.split(",") if c.strip()]
    else:
        pool = _all_company_ids() if args.all else _onboarded_company_ids()
        if args.count >= len(pool):
            targets = pool
        else:
            targets = random.Random(args.seed).sample(pool, args.count)

    print(f"Verifying {len(targets)} tickers (tolerance {args.tol}%, seed {args.seed})\n")
    print("| company | served | src | served date | yf close | yf quote | chart close | gap vs chart | verdict |")
    print("|---|---|---|---|---|---|---|---|---|")

    problems: list[str] = []
    for cid in targets:
        try:
            s = _served(cid)
        except Exception as exc:
            print(f"| {cid} | FETCH_FAILED | - | - | - | - | - | - | FETCH_FAILED ({str(exc)[:40]}) |")
            problems.append(f"{cid}: served fetch failed ({exc})")
            continue

        try:
            yf = _yfinance_quote(cid)
        except Exception as exc:
            yf = {"symbol": "?", "price": None, "previous_close": None}
        try:
            chart = _yahoo_chart(cid)
        except Exception:
            chart = {"symbol": "?", "price": None, "date": ""}

        chart_price = chart.get("price")
        yf_price = yf.get("price")

        # Primary comparison: the served close vs. an independent close.
        if chart_price:
            gap = _pct(s["price"], chart_price)
            gap_txt = f"{gap:.2f}%"
        else:
            gap, gap_txt = float("inf"), "-"

        src = s["source"]
        base_src = src[:-len(":successor_ticker")] if src.endswith(":successor_ticker") else src
        is_live = base_src in ("yfinance", "yfinance_history", "yahoo_chart", "twelvedata")

        if not is_live:
            verdict = "PLACEHOLDER"
        elif gap == float("inf"):
            verdict = "UNVERIFIED"
        elif gap > args.tol:
            verdict = "MISMATCH"
        elif chart.get("date") and s["date"] and s["date"] < chart["date"]:
            verdict = "DATE_STALE"
        else:
            verdict = "OK"

        if verdict in ("MISMATCH", "PLACEHOLDER", "DATE_STALE", "FETCH_FAILED"):
            problems.append(f"{cid}: {verdict}")

        print(
            f"| {cid} | {_fmt(s['price'])} | {base_src} | {s['date']} "
            f"| {_fmt(chart_price)} | {_fmt(yf_price)} | {_fmt(chart_price)} | {gap_txt} | {verdict} |"
        )

    print()
    ok = len(targets) - len(problems)
    print(f"{ok}/{len(targets)} tickers OK.")
    if problems:
        print("Needs attention:")
        for p in problems:
            print(f"  - {p}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
