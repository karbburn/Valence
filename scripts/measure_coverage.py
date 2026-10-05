"""How much of the reachable universe can Valence actually answer for?

Run deliberately, not in CI: every sample ticker is ingested, built and QA'd against the live
SEC and NSE indexes, which takes 5-10 minutes and depends on two third parties being up.

    python scripts/measure_coverage.py --sample 30
    python scripts/measure_coverage.py --sample 10 --market india

The number it produces answers the launch question honestly, because it applies the site's OWN
publication verdict rather than a proxy. That distinction is the whole point, and it is large:

Measured 2026-10-05, 30 US tickers sampled with a stride across the index:

    publish rate                     6 of 30 = 20%
    built a model at all            27 of 30
    no model could be built          3

    withheld for valuation_is_meaningful   11
                inputs_trace_to_a_filing   10
                equity_value_positive      10
                bridge_inputs_plausible     7
                debt_is_actually_sourced    5
                income_statement_is_coherent 3
                year_one_growth_is_plausible 1

An earlier probe asked a weaker question -- whether SEC's companyfacts carries all three annual
statements -- and answered 46%. That is a NECESSARY CONDITION, not the verdict, and the gap is
the point: IPSC, KMFG, MYND and WMK each obtained 98-100% filing-sourced historicals and are all
still withheld, because the gate also demands a meaningful valuation, a coherent income
statement, sourced debt and a bridge whose inputs survive a plausibility test. Quoting the 46%
would overstate coverage by more than double.

India, 20 NSE tickers sampled the same way:

    publish rate                     0 of 20 = 0%
    obtained ANY filing-sourced historicals   0 of 20
    read entirely from a market feed         20 of 20

Every one of them fails on `inputs_trace_to_a_filing`, because no filing reached the parser at
all. So the 0 of 12 that publish among the shipped India models is not a selection effect: it is
India.

What this means for the "13,000+" framing. The reachable universe is 10,440 SEC tickers plus
2,593 NSE entries = 13,033. Of those, on this measurement, roughly 2,100 would publish a
valuation -- all of them in the US -- and the rest are correctly withheld rather than wrong. A
withheld model is the product working: it declines to present a number it cannot support. But a
site that withholds 80% of the index and 100% of India is not a site that is ready for 13,000
companies, and the honest public claim is the coverage, not the reachability.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.api.routes import _spec_payload  # noqa: E402
from backend.data.batch import ensure_company_ingested  # noqa: E402
from backend.forecast.pipeline import run as run_forecast_pipeline  # noqa: E402
from backend.models.statements.pipeline import run as run_historical  # noqa: E402
from backend.validation.pipeline import run_qa  # noqa: E402
from backend.valuation.pipeline import run_valuation  # noqa: E402

SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
INDIA_CACHE = Path("backend/data/cache/ticker_index/india.json")
SEC_UA = {"User-Agent": "Valence coverage measurement (contact: karbburn@gmail.com)"}


def universe(market: str) -> tuple[list[str], int]:
    """(company ids, reachable count) for the market."""
    if market == "us":
        req = urllib.request.Request(SEC_TICKERS, headers=SEC_UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            entries = json.loads(r.read().decode("utf-8")).values()
        tickers = sorted({str(e["ticker"]).strip() for e in entries})
        return [f"{t.lower()}_us" for t in tickers], len(tickers)

    raw = json.loads(INDIA_CACHE.read_text(encoding="utf-8"))
    records = (raw.get("entries") or raw) if isinstance(raw, dict) else raw
    values = list(records.values()) if isinstance(records, dict) else list(records)
    tickers = sorted({
        str(v.get("ticker") or v.get("symbol")).strip()
        for v in values if isinstance(v, dict) and (v.get("ticker") or v.get("symbol"))
    })
    return [f"{t.lower()}_{t.lower()}" for t in tickers], len(tickers)


def measure_one(company_id: str) -> dict:
    """Build the model the on-demand request would build, and read the verdict it would serve.

    **`historical_model` is deliberately NOT passed**, and that is load-bearing rather than an
    omission. `run_precompute` calls `run_valuation(forecast_spec)` with no historical model, so
    the reverse DCF's bisection solve never runs in production and `implied_revenue_cagr` is null
    on every shipped model. Passing it here would build a model the site never builds, and the
    coverage figure would then describe a configuration nobody is served.

    `backend/tests/test_the_second_solve_is_wired.py` asserts exactly this, by scanning tracked
    files for any caller that supplies it, and it caught this script on its first run in CI. The
    tripwire was right: a coverage number is only worth quoting if it was measured on the shipped
    path.

    The solve's output is also not yet trustworthy. Substituting a solved rate back into the base
    scenario and re-running returns exactly the model's own price, so the figure cannot be shown
    to reproduce the market price it claims to explain, which is why it stays off.
    """
    ensure_company_ingested(company_id)
    hist = run_historical(target_periods=["FY24", "FY25", "FY26"], company_id=company_id)
    spec = run_qa(run_valuation(run_forecast_pipeline(hist)))
    payload = _spec_payload(spec)
    pub = payload.get("publication") or {}
    sources = (payload.get("metadata") or {}).get("data_sources") or {}
    filing = sum(v for k, v in sources.items() if k in ("sec_edgar", "nse_filing"))
    total = sum(sources.values())
    return {
        "publishable": bool(pub.get("publishable")),
        "reasons": pub.get("reasons") or [],
        "filing_pct": (filing / total * 100) if total else 0.0,
        "rows": total,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--market", choices=("us", "india", "both"), default="both")
    args = ap.parse_args()

    markets = ("us", "india") if args.market == "both" else (args.market,)
    overall_fail = False

    for market in markets:
        ids, reachable = universe(market)
        step = max(1, len(ids) // args.sample)
        sample = ids[::step][: args.sample]

        print()
        print("=" * 92)
        print(f"{market.upper()}: {reachable:,} reachable, sampling {len(sample)} "
              f"with a stride of {step}")
        print("=" * 92)

        publishing = withheld = unbuildable = 0
        any_filing = 0
        reasons: Counter = Counter()

        for i, cid in enumerate(sample, 1):
            t0 = time.time()
            try:
                out = measure_one(cid)
            except Exception as exc:
                unbuildable += 1
                print(f"  {i:>2}/{len(sample)}  {cid:<22s} NO MODEL   {type(exc).__name__}")
                continue
            if out["filing_pct"] > 0:
                any_filing += 1
            if out["publishable"]:
                publishing += 1
                flag = "PUBLISHES"
            else:
                withheld += 1
                flag = "withheld"
                for r in out["reasons"] or ["(none recorded)"]:
                    reasons[r.split(":")[0]] += 1
            print(f"  {i:>2}/{len(sample)}  {cid:<22s} {flag:<10s} "
                  f"filing {out['filing_pct']:>5.1f}%  rows {out['rows']:>4d}  "
                  f"{time.time() - t0:>5.1f}s")

        print()
        print(f"  sampled                        {len(sample)}")
        print(f"  built a model at all           {len(sample) - unbuildable}")
        print(f"    of which PUBLISH a price     {publishing}")
        print(f"    of which withheld            {withheld}")
        print(f"  no model could be built        {unbuildable}")
        print(f"  obtained any filing history    {any_filing}")
        if len(sample) == args.sample:
            rate = publishing / len(sample) * 100
            print()
            print(f"  PUBLISH RATE {publishing}/{len(sample)} = {rate:.0f}%   "
                  f"-> about {round(rate / 100 * reachable):,} of {reachable:,}")
            print("  That projection is an EXTRAPOLATION from a sample, not a count. The index")
            print("  includes OTC issuers whose filings are shells, so coverage is not uniform.")
        if reasons:
            print()
            print("  withheld because:")
            for reason, n in reasons.most_common():
                print(f"    {n:>3d}  {reason}")
        if market == "india" and any_filing == 0 and len(sample):
            print()
            print("  Every sampled India name read entirely from a market feed, so the gate")
            print("  withholds all of them on `inputs_trace_to_a_filing`. That is not a")
            print("  selection effect in the shipped set: no filing is reaching the parser.")

    return 1 if overall_fail else 0


if __name__ == "__main__":
    sys.exit(main())