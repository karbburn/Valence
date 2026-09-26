"""Cross-check Valence's served market prices against independently verified closes.

Valence pulls daily closes from free APIs (yfinance history -> Yahoo chart ->
TwelveData). Those feeds can drift from what a human sees on an exchange or
aggregator page, so this script compares the served price + quote date against
`scripts/price_reference.json` — a small, human-verified record of official
closes captured from public quote pages (Google Finance, StockAnalysis) via a
browser, because those pages render client-side and cannot be scraped over
plain HTTP.

Each reference entry records where the number came from:

    "infy_infy": {
      "price": 998.80,
      "date": "2026-09-25",
      "source": "Google Finance INFY:NSE + StockAnalysis (both 998.80, -1.55%)"
    }

Verdicts:
  OK          served price within tolerance of the verified close
  DATE_STALE  price matches, but the served quote date is older than the
              verified date (feed is not refreshing)
  MISMATCH    price outside tolerance of the verified close
  UNVERIFIED  no independent reference recorded yet

Usage:
    python scripts/verify_market_prices.py
    python scripts/verify_market_prices.py --company infy_infy
    python scripts/verify_market_prices.py --tol 1.0     # 1% tolerance
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

REFERENCE_FILE = Path(__file__).resolve().parent / "price_reference.json"


def load_reference() -> dict:
    if not REFERENCE_FILE.exists():
        return {}
    try:
        with open(REFERENCE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"Could not read {REFERENCE_FILE.name}: {exc}")
        return {}


def served_price(company_id: str, refresh: bool) -> tuple[float | None, str, str]:
    """Return (price, source, quote_date) exactly as the engine would serve it."""
    from backend.data.providers.market_data import get_company_market_data

    try:
        cmd = get_company_market_data(company_id, force_refresh=refresh)
    except Exception as exc:
        return None, f"error: {exc}", ""
    return cmd.price.value, cmd.price.source, cmd.price.fetch_date


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare Valence prices with verified closes.")
    ap.add_argument("--company", default=None, help="Single company_id (default: all registry).")
    ap.add_argument("--tol", type=float, default=0.5, help="Max allowed %% gap (default 0.5).")
    ap.add_argument("--live", action="store_true", help="Bypass the daily cache and re-fetch sources.")
    args = ap.parse_args()

    from backend.data.providers.market_data import REGISTRY_FALLBACKS

    targets = [args.company] if args.company else sorted(REGISTRY_FALLBACKS.keys())
    reference = load_reference()

    print(f"Verifying {len(targets)} companies against {REFERENCE_FILE.name} (tolerance {args.tol}%)\n")
    print("| company | served | source | quote date | verified | verif date | gap | verdict |")
    print("|---|---|---|---|---|---|---|---|")

    problems: list[str] = []
    for cid in targets:
        price, source, quote_date = served_price(cid, refresh=args.live)
        ref = reference.get(cid) or {}
        ref_price = ref.get("price")
        ref_date = ref.get("date", "")

        if price is None:
            gap, verdict = float("inf"), "FETCH_FAILED"
        elif not ref_price:
            gap, verdict = float("nan"), "UNVERIFIED"
        else:
            gap = abs(price - ref_price) / ref_price * 100
            if gap > args.tol:
                verdict = "MISMATCH"
            elif ref_date and quote_date and quote_date < ref_date:
                verdict = "DATE_STALE"
            else:
                verdict = "OK"

        if verdict in ("MISMATCH", "FETCH_FAILED", "DATE_STALE"):
            problems.append(f"{cid}: {verdict}")

        def fmt(v):
            return f"{v:,.2f}" if isinstance(v, (int, float)) else "-"

        print(
            f"| {cid} | {fmt(price)} | {source} | {quote_date or '-'} "
            f"| {fmt(ref_price)} | {ref_date or '-'} "
            f"| {'-' if gap != gap else f'{gap:.2f}%'} | {verdict} |"
        )

    print()
    unverified = [c for c in targets if c not in reference]
    if unverified:
        print(f"No independent reference yet for: {', '.join(unverified)}")
    if problems:
        print("Needs attention:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("All verified companies within tolerance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
