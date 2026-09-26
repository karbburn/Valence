"""Re-ingest every onboarded company and rebuild its precomputed snapshot.

Run after any change to the ingestion maps, the taxonomy registry, the
statement assembly or the forecast engine. Existing snapshots are invalidated by
the contract check in `api/routes.py`, but that only helps a running server;
this rewrites the files on disk so a fresh deployment starts from data the
current code actually produces.

    python scripts/refresh_all_models.py
    python scripts/refresh_all_models.py --companies infy_infy,nvda_us
    python scripts/refresh_all_models.py --no-ingest
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.data.batch import ensure_company_ingested  # noqa: E402
from backend.data.pipeline import DB_PATH  # noqa: E402
from backend.data.precompute import run_precompute  # noqa: E402
from backend.data.universe.store import list_all_universe_companies  # noqa: E402

CACHE_DIR = REPO_ROOT / "backend" / "data" / "cache"


def onboarded() -> list[str]:
    """Every company the universe marks as having a model built."""
    try:
        ids = {
            c.canonical_id
            for c in list_all_universe_companies()
            if getattr(c, "canonical_id", None)
            and (getattr(c, "onboarding_status", "") or "").lower() in ("onboarded", "complete", "completed")
        }
        if ids:
            return sorted(ids)
    except Exception as exc:  # pragma: no cover - fall back to the cache dir
        print(f"  (universe query unavailable: {exc})")
    return sorted(p.stem for p in CACHE_DIR.glob("*.json") if p.name != "market_data_cache.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--companies", default="")
    ap.add_argument(
        "--no-ingest",
        action="store_true",
        help="Rebuild snapshots from the existing database instead of re-fetching.",
    )
    ap.add_argument(
        "--force-ingest",
        action="store_true",
        help=(
            "Re-run the source maps even for companies that already have canonical "
            "rows. Required after changing an ingestion map, a source label, or the "
            "taxonomy registry — otherwise the corrected mapping never reaches the "
            "database and the stored provenance stays whatever the first parse wrote."
        ),
    )
    args = ap.parse_args()

    companies = (
        [c.strip() for c in args.companies.split(",") if c.strip()]
        if args.companies
        else onboarded()
    )
    print(f"Refreshing {len(companies)} company model(s)")
    print("=" * 78)

    ok, failed, skipped = [], [], []
    for cid in companies:
        try:
            if not args.no_ingest:
                ensure_company_ingested(cid, force=args.force_ingest)
            run_precompute(company_id=cid)
            path = CACHE_DIR / f"{cid}.json"
            size = path.stat().st_size if path.exists() else 0
            print(f"  OK    {cid:28} {size / 1024:8.1f} KB")
            ok.append(cid)
        except Exception as exc:
            print(f"  FAIL  {cid:28} {type(exc).__name__}: {str(exc)[:90]}")
            failed.append((cid, f"{type(exc).__name__}: {exc}"))
            if "-v" in sys.argv:
                traceback.print_exc()

    print("=" * 78)
    print(f"  {len(ok)} rebuilt, {len(failed)} failed")
    for cid, err in failed:
        print(f"    FAILED {cid}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
