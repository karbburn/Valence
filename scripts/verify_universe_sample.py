"""Cross-check Valence prices for a random sample drawn from the FULL company universe.

verify_tickers.py samples the small registry; this samples the ~10k-row universe
table so the price chain is exercised against tickers Valence has never cached
before — the real test of "does a cold company get a correct live quote".

Usage:
    python scripts/verify_universe_sample.py --count 20 --seed 42
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_tickers import _fmt, _served, _yahoo_chart, _yfinance_quote  # noqa: E402

# Micro-caps, funds, SPAC units and warrants routinely have no usable quote feed
# or a price that is not comparable to a DCF; exclude them from the sample.
MIN_PRICE = 1.0
MAX_PRICE = 20000.0
EXCLUDE_TICKER_SUFFIXES = ("-W", "-WT", "-UN", "-U", "-WS", "-PA", "-PB", "-PC", "-PD", "-PI", "-PR")


def universe_sample(count: int, seed: int) -> list[str]:
    from backend.data.universe.store import get_universe_company  # noqa: F401
    import sqlite3

    from backend.data.pipeline import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "select company_id, ticker, market from company_universe where ticker not like '%-%'"
    ).fetchall()
    conn.close()

    # Deduplicate on ticker: the universe holds several company_ids per ticker
    # (share classes, old listings) and we want distinct securities.
    seen: set[str] = set()
    unique: list[tuple[str, str, str]] = []
    for cid, tkr, market in rows:
        t = str(tkr).upper()
        if t in seen or any(t.endswith(sfx) for sfx in EXCLUDE_TICKER_SUFFIXES):
            continue
        seen.add(t)
        unique.append((cid, t, market))

    return [c for c, _, _ in random.Random(seed).sample(unique, min(count, len(unique)))]


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify a random sample of universe tickers.")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tol", type=float, default=0.5)
    args = ap.parse_args()

    targets = universe_sample(args.count, args.seed)
    print(f"Verifying {len(targets)} randomly sampled universe tickers "
          f"(seed {args.seed}, tolerance {args.tol}%)\n")
    print("| company | ticker | served | src | served date | chart close | yf quote | gap | verdict |")
    print("|---|---|---|---|---|---|---|---|---|")

    problems: list[str] = []
    for cid in targets:
        ticker = cid.split("_")[0].upper()
        try:
            s = _served(cid)
        except Exception as exc:
            print(f"| {cid} | {ticker} | - | - | - | - | - | - | FETCH_FAILED |")
            problems.append(f"{cid}: {str(exc)[:50]}")
            continue

        try:
            chart = _yahoo_chart(cid)
        except Exception:
            chart = {"price": None, "date": ""}
        try:
            yf = _yfinance_quote(cid)
        except Exception:
            yf = {"price": None}

        src = s["source"]
        base_src = src[:-len(":successor_ticker")] if src.endswith(":successor_ticker") else src
        is_live = base_src in ("yfinance", "yfinance_history", "yahoo_chart", "twelvedata")
        chart_price = chart.get("price")

        if chart_price:
            gap = abs(s["price"] - chart_price) / chart_price * 100
            gap_txt = f"{gap:.2f}%"
        else:
            gap, gap_txt = float("inf"), "-"

        if not is_live:
            verdict = "PLACEHOLDER"
        elif gap == float("inf"):
            verdict = "UNVERIFIED"
        elif not (MIN_PRICE <= s["price"] <= MAX_PRICE):
            verdict = "BAND_BREACH"
        elif gap > args.tol:
            verdict = "MISMATCH"
        else:
            verdict = "OK"

        if verdict != "OK":
            problems.append(f"{cid} ({ticker}): {verdict} — served {s['price']} via {base_src}, chart {chart_price}")

        print(
            f"| {cid} | {ticker} | {_fmt(s['price'])} | {base_src} | {s['date']} "
            f"| {_fmt(chart_price)} | {_fmt(yf.get('price'))} | {gap_txt} | {verdict} |"
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
