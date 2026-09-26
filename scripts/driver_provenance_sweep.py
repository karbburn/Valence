"""Per-company report on the drivers that were previously invented or mis-derived.

Everything here is a figure the model publishes, or a number it uses to build
one. The point of the sweep is that each row must be traceable: a driver either
comes from the company's own filings, or it is marked unresolved. Nothing may
be a silent constant.

    python scripts/driver_provenance_sweep.py
    python scripts/driver_provenance_sweep.py --verbose
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.models.spec.forecast import FORECAST_PERIODS  # noqa: E402
from backend.models.spec.historicals import REPORTED_STATUSES  # noqa: E402
from backend.models.spec.model_specification import ModelSpecification  # noqa: E402

CACHE = REPO_ROOT / "backend" / "data" / "cache"

LAST = FORECAST_PERIODS[-1]

DRIVERS = (
    "revenue_growth",
    "ebit_margin",
    "da_pct_revenue",
    "tax_rate",
    "dso_days",
    "dio_days",
    "dpo_days",
    "capex_pct_revenue",
    "terminal_growth_rate",
)


def _driver(spec, key, period=LAST, scenario="base"):
    hit = None
    for a in spec.assumptions:
        if a.driver_key == key and a.scenario == scenario:
            if a.period == period:
                return a.value, a.source
            if hit is None:
                hit = (a.value, a.source)
    return hit if hit else (None, "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    companies = sorted(p.stem for p in CACHE.glob("*.json") if p.name != "market_data_cache.json")
    print(f"{len(companies)} companies\n")

    unresolved_total = 0
    unreported_total = 0
    for cid in companies:
        spec = ModelSpecification.deserialize((CACHE / f"{cid}.json").read_text(encoding="utf-8"))
        base = spec.get_valuation("base")

        hist_periods = spec.historicals.periods or []
        reported = {
            li.period_label
            for li in spec.historicals.line_items
            if li.status in REPORTED_STATUSES
        }
        unreported = [p for p in hist_periods if p not in reported]
        unreported_total += 1 if unreported else 0

        share_src = ""
        if spec.share_count and spec.share_count.schedule:
            last_sched = [p for p in spec.share_count.schedule if p.period == hist_periods[-1]]
            if last_sched:
                share_src = last_sched[0].source
        shares = spec.share_count.get_diluted(hist_periods[-1]) if hist_periods else None

        interest = ""
        for ds in spec.debt_schedule:
            if ds.scenario == "base":
                interest = f"{ds.interest_rate:.2f}%"
                break

        print(f"=== {cid}  ({spec.metadata.ticker} · {spec.metadata.currency} · FY end {spec.metadata.fiscal_year_end})")
        print(f"    market {base.reverse_dcf.market_price:>12,.2f}   implied {base.dcf_bridge.implied_share_price:>12,.2f}"
              f"   WACC {base.wacc.wacc:>6.2f}%   beta {base.wacc.beta}")
        print(f"    shares {shares if shares is not None else 0:>12,.2f}   carrying rate {interest:>7}   "
              f"hist reported {len(reported)}/{len(hist_periods)}")
        if unreported:
            print(f"    !! historical periods NOT from a filing: {', '.join(unreported)}")

        unresolved = []
        for key in DRIVERS:
            value, source = _driver(spec, key)
            flag = ""
            if "unresolved" in (source or "").lower() or "default" in (source or "").lower() or "placeholder" in (source or "").lower():
                flag = "  <-- not the company's own figure"
                unresolved.append(key)
            print(f"      {key:22} {value if value is not None else float('nan'):>10.3f}   {source}{flag}")
        unresolved_total += len(unresolved)

        if args.verbose and share_src:
            print(f"      share count source: {share_src}")
        print()

    print("=" * 78)
    print(f"  {unresolved_total} driver instance(s) across the universe are not the company's own figure")
    print(f"  {unreported_total} of {len(companies)} companies serve at least one historical year that is not a filing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
