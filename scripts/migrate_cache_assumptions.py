"""Migrate committed precomputed caches to current engine logic without re-ingestion.

Rewrites ONLY the assumptions / valuation / QA sections of each
backend/data/cache/*.json, preserving historicals and forecast drivers
exactly as committed. Used when engine code changes (e.g. CAPM default,
currency-aware reverse-DCF notes) but the underlying ingested financials
are still fresh — a full re-ingestion would regress them to older fixtures.

For each cache file:
  1. Load the ModelSpecification.
  2. Replace every wacc.cost_of_equity assumption with the live CAPM default.
  3. De-duplicate assumptions (repairs the duplicate-append race).
  4. Re-run valuation (currency notes, market price dates) + QA.
  5. Write back only if something changed.

Usage:
    python scripts/migrate_cache_assumptions.py            # dry run
    python scripts/migrate_cache_assumptions.py --apply    # write files
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

CACHE_DIR = REPO_ROOT / "backend" / "data" / "cache"


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate cached specs to current engine logic.")
    ap.add_argument("--apply", action="store_true", help="Write migrated files.")
    ap.add_argument("--company", default=None, help="Only migrate one company_id.")
    args = ap.parse_args()

    from backend.api.routes import _normalize_assumptions
    from backend.forecast.assumptions import capm_default_for
    from backend.models.spec.model_specification import ModelSpecification
    from backend.validation.pipeline import run_qa
    from backend.valuation.pipeline import run_valuation

    files = sorted(CACHE_DIR.glob("*.json"))
    files = [f for f in files if f.name != "market_data_cache.json"]
    if args.company:
        files = [f for f in files if f.stem == args.company]
    changed: list[str] = []
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            spec = ModelSpecification(**raw["model"])
        except Exception as exc:
            print(f"SKIP {path.name}: cannot parse ({exc})")
            continue
        cid = spec.metadata.company_id
        ke, source = capm_default_for(cid, spec.metadata.market)
        touched = False
        for a in spec.assumptions:
            if a.driver_key == "wacc.cost_of_equity" and a.type == "model_generated":
                if a.value != ke:
                    a.value = ke
                    a.source = source
                    touched = True
        before = len(spec.assumptions)
        spec.assumptions = _normalize_assumptions(spec.assumptions)
        if len(spec.assumptions) != before:
            touched = True
        spec = run_valuation(spec)
        spec = run_qa(spec)
        new_text = spec.serialize()
        old_text = json.dumps(raw, separators=(",", ":"))  # rough compare guard below
        _ = old_text
        # Compare semantic payloads instead of raw text (key order may differ).
        old_model = raw["model"]
        new_model = json.loads(new_text)
        if json.dumps(old_model, sort_keys=True) != json.dumps(new_model, sort_keys=True):
            touched = True
        print(f"{'UPDATE' if touched else 'ok-noop'} {cid}: Ke={ke} "
              f"mkt={spec.valuation[0].reverse_dcf.market_price} "
              f"qa={spec.qa.summary_label}")
        if touched:
            changed.append(cid)
            if args.apply:
                path.write_text(new_text, encoding="utf-8")
    print(f"\n{len(changed)} file(s) would change: {changed or 'none'}")
    if not args.apply:
        print("Dry run — rerun with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
