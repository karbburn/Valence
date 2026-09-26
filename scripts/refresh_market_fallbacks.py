"""Refresh structural market-data fallbacks (shares outstanding only) from live data.

Reads REGISTRY_FALLBACKS in backend/data/providers/market_data.py, fetches
live shares outstanding per company via yfinance, and rewrites the registry
`shares` values in place when the live figure passes sanity bounds.

Deliberately conservative by design:
  - Only `shares` is touched. Price is NEVER stored in the registry — it is a
    daily quote fetched live every day (see scripts/refresh_market_data.py).
    Beta / RFR / ERP require analyst calibration (domestic-index beta,
    Damodaran ERP) and are NEVER auto-edited. Live reference values for those
    are printed for manual review instead.
  - A live shares figure outside [0.5x, 2x] of the current fallback is
    rejected as a probable bad tick / split event.
  - Dry-run by default; pass --apply to write the file.
  - Exit code is 0 unless --strict is given, so scheduled CI never goes red
    just because a quote feed hiccuped. Use the printed report instead.

Usage:
    python scripts/refresh_market_fallbacks.py           # dry run (report only)
    python scripts/refresh_market_fallbacks.py --apply   # rewrite registry
    python scripts/refresh_market_fallbacks.py --apply --strict
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

TARGET_FILE = REPO_ROOT / "backend" / "data" / "providers" / "market_data.py"

SHARES_BOUNDS = (0.5, 2.0)

ENTRY_RE = re.compile(
    r'(?P<indent>\s*)"(?P<cid>[a-z0-9_]+)":\s*\{\s*"shares":\s*(?P<shares>[0-9.]+),\s*'
    r'"beta":\s*(?P<beta>[0-9.]+),\s*'
    r'"market":\s*"(?P<market>[a-z]+)"\s*\},?'
)
STAMP_RE = re.compile(r"# Last refreshed: \d{4}-\d{2}-\d{2}.*")


def fetch_live(company_id: str, market: str, ticker: str) -> dict:
    """Return live shares/beta/rfr reference values (missing keys on failure).

    NOTE: price is intentionally NOT fetched here — the registry stores no
    price (daily closes come from scripts/refresh_market_data.py instead).
    """
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed"}
    from backend.data.providers.market_data import _yf_ticker_for

    out: dict = {}
    try:
        symbol = _yf_ticker_for(company_id, market, ticker)  # type: ignore[arg-type]
        info = yf.Ticker(symbol).info or {}
        shares_raw = info.get("sharesOutstanding")
        if shares_raw and float(shares_raw) > 0:
            divisor = 1e7 if market == "india" else 1e6
            out["shares"] = round(float(shares_raw) / divisor, 2)
        beta = info.get("beta")
        if beta and float(beta) > 0:
            out["beta_ref"] = round(float(beta), 3)
        if market == "us":
            tnx = (yf.Ticker("^TNX").info or {})
            rfr = tnx.get("regularMarketPrice") or tnx.get("previousClose")
            if rfr and float(rfr) > 0:
                out["rfr_ref"] = round(float(rfr), 2)
    except Exception as exc:  # feed hiccup: report, don't crash
        out["error"] = str(exc)[:160]
    return out


def within_bounds(new: float, old: float, bounds: tuple[float, float]) -> bool:
    lo, hi = bounds
    return old * lo <= new <= old * hi


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="Rewrite the registry file.")
    ap.add_argument("--strict", action="store_true", help="Exit non-zero on any fetch/bounds failure.")
    args = ap.parse_args()

    from backend.data.providers.market_data import REGISTRY_FALLBACKS

    text = TARGET_FILE.read_text(encoding="utf-8")
    failures: list[str] = []
    updates: list[str] = []
    report_lines: list[str] = ["| company | field | old | live | action |",
                               "|---|---|---|---|---|"]

    def replace_entry(m: re.Match) -> str:
        cid = m.group("cid")
        if cid not in REGISTRY_FALLBACKS:
            return m.group(0)
        old_shares = float(m.group("shares"))
        market = m.group("market")
        ticker = cid.split("_")[0].upper()
        live = fetch_live(cid, market, ticker)

        new_shares = old_shares
        actions: list[str] = []
        if "shares" in live:
            if within_bounds(live["shares"], old_shares, SHARES_BOUNDS):
                new_shares = live["shares"]
                actions.append("shares updated")
            else:
                failures.append(f"{cid}: shares {live['shares']} outside bounds of {old_shares}")
                actions.append("shares REJECTED (bounds)")
        else:
            failures.append(f"{cid}: no live shares ({live.get('error', 'n/a')})")
            actions.append("shares unavailable")

        ref = ", ".join(f"{k}={v}" for k, v in live.items()
                        if k.endswith("_ref")) or "—"
        action = "; ".join(actions)
        if new_shares != old_shares:
            updates.append(cid)
        report_lines.append(f"| {cid} | shares | {old_shares} "
                            f"| {live.get('shares', '—')} "
                            f"| {action} | refs: {ref} |")
        return (f'{m.group("indent")}"{cid}": {{"shares": {new_shares}, '
                f'"beta": {m.group("beta")}, '
                f'"market": "{market}"}},')

    new_text, n = ENTRY_RE.subn(replace_entry, text)
    today = date.today().isoformat()
    if STAMP_RE.search(new_text):
        new_text = STAMP_RE.sub(f"# Last refreshed: {today} (automated refresh_market_fallbacks.py)", new_text)
    else:
        new_text = new_text.replace(
            "# Per-company benchmark registry fallback (native currency, native share units)",
            "# Per-company benchmark registry fallback (native currency, native share units)\n"
            f"# Last refreshed: {today} (automated refresh_market_fallbacks.py)",
            1,
        )

    print(f"Checked {n} registry entries; {len(updates)} would change: {updates or 'none'}")
    if failures:
        print("Warnings:")
        for f in failures:
            print(f"  - {f}")
    print("\n".join(report_lines))

    if args.apply:
        if updates:
            TARGET_FILE.write_text(new_text, encoding="utf-8")
            print(f"\nWrote {TARGET_FILE}")
        else:
            print("\nNo changes to write.")
    else:
        print("\nDry run — rerun with --apply to write.")

    if args.strict and failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
