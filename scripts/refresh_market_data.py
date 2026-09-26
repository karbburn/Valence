"""Daily market-quote refresh — fetches the latest daily close for every company.

Price is NEVER hardcoded in this repo (see backend/data/providers/market_data.py).
This script pulls the live daily close from free sources (yfinance history close
-> Stooq free CSV -> TwelveData when keyed) and writes backend/data/cache/
market_data_cache.json, stamped with today's date.

Run it once a day (after US close works well — ~9pm ET / ~6:30am IST):

  cron:        30 2 * * *  cd /path/to/Valence && python scripts/refresh_market_data.py
  locally:     python scripts/refresh_market_data.py
  single name: python scripts/refresh_market_data.py --company nvda_us
  dry run:     python scripts/refresh_market_data.py --dry-run

The API also self-heals: get_company_market_data() re-fetches whenever the
cached fetch_date != today, so even without cron the first request of the day
pulls a fresh close. This script just warms the cache ahead of users (and is
what Render's cron job should call) so nobody ever waits on — or sees a
stale/missing quote from — a cold fetch.

Exit code is 0 even if individual tickers fail; failures are reported, and a
failed ticker keeps its last-known-good stale quote rather than a placeholder.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _onboarded_company_ids() -> list[str]:
    try:
        from backend.data.universe.master_list import seed_master_universe  # noqa: F401
        from backend.data.universe.store import search_universe_companies

        seed_master_universe()
        companies = search_universe_companies(query="", status="onboarded", limit=1000)
        ids = [c.company_id for c in companies]
        if ids:
            return ids
    except Exception as exc:
        print(f"Universe lookup failed ({exc}); falling back to registry list.")
    from backend.data.providers.market_data import REGISTRY_FALLBACKS

    return sorted(REGISTRY_FALLBACKS.keys())


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh daily market closes for all companies.")
    ap.add_argument("--company", default=None, help="Refresh a single company_id (e.g. nvda_us).")
    ap.add_argument("--dry-run", action="store_true", help="Fetch but do not write the cache.")
    args = ap.parse_args()

    from backend.data.providers import market_data as md

    targets = [args.company] if args.company else _onboarded_company_ids()
    print(f"Refreshing {len(targets)} companies: {', '.join(targets)}")

    ok, stale, failed = [], [], []
    for cid in targets:
        try:
            if args.dry_run:
                # Force a live fetch without persisting: call the source
                # fetchers directly so the on-disk cache is untouched.
                from backend.data.providers.market_data import (
                    _fetch_stooq,
                    _fetch_yfinance_history,
                    get_company_market_data,
                )

                reg = md.REGISTRY_FALLBACKS.get(cid, {})
                market = reg.get("market") or ("us" if cid.endswith("_us") else "india")  # type: ignore[assignment]
                ticker = cid.split("_")[0].upper()
                pt = (_fetch_yfinance_history(cid, market, ticker).get("price")
                      or _fetch_stooq(cid, market, ticker).get("price"))
                if pt is not None:
                    print(f"  {cid}: dry-run close {pt.value} ({pt.source})")
                    ok.append(cid)
                else:
                    # Fall back to reporting whatever the served path returns.
                    served = get_company_market_data(cid)
                    print(f"  {cid}: dry-run served {served.price.value} ({served.price.source})")
                    (stale if served.price.source.startswith("stale_cache") else failed).append(cid)
                continue
            cmd = md.get_company_market_data(cid, force_refresh=True)
            src = cmd.price.source
            print(f"  {cid}: {cmd.price.value} ({src}) as of {cmd.price.fetch_date}")
            if src.startswith("stale_cache") or src in ("registry", "market_default"):
                stale.append(cid)
            else:
                ok.append(cid)
        except Exception as exc:
            print(f"  {cid}: FAILED ({exc})")
            failed.append(cid)

    print(f"\nDone: {len(ok)} live, {len(stale)} stale/fallback, {len(failed)} failed.")
    if stale:
        print(f"  stale/fallback: {', '.join(stale)}")
    if failed:
        print(f"  failed: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
