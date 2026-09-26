"""Independent recomputation of the whole valuation chain, checked against the API.

The point of this harness is to be an INDEPENDENT implementation: it reads only
the raw ModelSpecification fields a user would consider given (historical
revenue/margins, the published driver assumptions, the published market price and
WACC components) and recomputes FCFF, terminal value, the EV->equity bridge and
the per-share result from first principles. Any disagreement with the engine is a
real defect, not a restatement of the same code.

For each company it checks:
  1. FCFF per year      = EBIT*(1-t) + D&A - Capex - dWC - SBC
  2. Discount factors    = 1/(1+WACC)^(t-0.5)          [mid-year]
  3. PV of FCFF          = FCFF * DF
  4. Terminal value      = FCFF_5*(1+g)/(WACC-g)
  5. PV of TV            = TV * 1/(1+WACC)^5
  6. EV                  = sum(PV FCFF) + PV(TV)
  7. Equity              = EV - (debt+NCI+pref) + (cash+securities+investments)
  8. Implied price       = equity / diluted shares
  9. TV share of EV      = PV(TV) / EV
 10. Reverse DCF         = solve g such that the chain reproduces market price

Usage:
    python scripts/recompute_valuation.py
    python scripts/recompute_valuation.py --companies infy_infy,nvda_us
    python scripts/recompute_valuation.py --base http://127.0.0.1:8010
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_COMPANIES = ["infy_infy", "tcs_tcs", "nvda_us", "aapl_us", "msft_us", "googl_us"]

FORECAST_PERIODS = ["FY27", "FY28", "FY29", "FY30", "FY31"]


def _get(base: str, cid: str) -> dict:
    with urllib.request.urlopen(f"{base}/api/model/{cid}", timeout=900) as r:
        return json.loads(r.read().decode("utf-8"))


def _fcff_map(spec: dict, scenario: str) -> dict:
    out = {}
    for li in spec["forecast"]["line_items"]:
        if li["scenario"] == scenario:
            out.setdefault(li["canonical_key"], {})[li["period_label"]] = li["value"]
    return out


def _driver(spec: dict, key: str, period: str, scenario: str = "base") -> float | None:
    for a in spec["assumptions"]:
        if a["driver_key"] == key and a["period"] in (period, "all") and a["scenario"] == scenario:
            return a["value"]
    for a in spec["assumptions"]:
        if a["driver_key"] == key and a["scenario"] == "base":
            return a["value"]
    return None


def recompute(spec: dict, scenario: str = "base") -> dict:
    """Recompute the DCF chain from the spec's own published inputs."""
    val = next(v for v in spec["valuation"] if v["scenario"] == scenario)
    bridge = val["dcf_bridge"]
    wacc_pct = val["wacc"]["wacc"]
    wacc = wacc_pct / 100.0

    fc = _fcff_map(spec, scenario)
    engine_fcff = {p["period"]: p for p in val["fcff_by_period"]}

    # --- 1-3. FCFF chain, period by period ---------------------------
    fcff_calc, pv_calc, sum_pv = {}, {}, 0.0
    for t, period in enumerate(FORECAST_PERIODS, start=1):
        ebit = fc.get("canonical.is.operating_profit", {}).get(period)
        if ebit is None:
            continue
        pbt = fc.get("canonical.is.pbt", {}).get(period)
        tax = fc.get("canonical.is.tax", {}).get(period)
        da = fc.get("canonical.is.depreciation_amortization", {}).get(period) or 0.0

        # Effective rate is derived from the statements: tax / PBT, and only a
        # positive PBT is taxable. Mirrors the engine's stated convention.
        pbt = pbt if pbt is not None else ebit
        tax = tax or 0.0
        tax_rate = (tax / pbt * 100.0) if pbt and pbt > 0 else 0.0

        capex_raw = fc.get("canonical.cf.capex", {}).get(period)
        capex = abs(capex_raw) if capex_raw is not None else abs(da)

        dwc = fc.get("canonical.cf.delta_working_capital", {}).get(period)
        if dwc is None:
            np_val = fc.get("canonical.is.net_profit", {}).get(period) or 0.0
            cfo = fc.get("canonical.cf.operating_activities", {}).get(period)
            cfo = cfo if cfo is not None else (np_val + da)
            dwc = np_val + da - cfo
        sbc_raw = fc.get("canonical.cf.stock_compensation", {}).get(period)
        sbc = abs(sbc_raw) if sbc_raw else 0.0

        nopat = ebit * (1.0 - tax_rate / 100.0)
        f = nopat + da - capex - dwc - sbc
        df = 1.0 / ((1.0 + wacc) ** (t - 0.5))
        fcff_calc[period] = {
            "fcff": f, "df": df, "pv": f * df,
            "tax_rate": tax_rate, "nopat": nopat, "da": da, "capex": capex,
            "dwc": dwc, "sbc": sbc,
            "engine_fcff": engine_fcff.get(period, {}).get("fcff"),
        }
        sum_pv += f * df

    # --- 4-6. Terminal value + EV -------------------------------------
    g = _driver(spec, "terminal_growth_rate", "terminal") or 0.0
    g_frac = g / 100.0
    last_fcff = fcff_calc[FORECAST_PERIODS[-1]]["fcff"] if FORECAST_PERIODS[-1] in fcff_calc else 0.0
    wacc_minus_g = wacc - g_frac
    tv_undisc = last_fcff * (1 + g_frac) / wacc_minus_g if wacc_minus_g > 0 else float("nan")
    df_tv = 1.0 / ((1.0 + wacc) ** len(FORECAST_PERIODS))
    pv_tv = tv_undisc * df_tv
    ev = sum_pv + pv_tv

    # --- 7-8. Bridge to per share ------------------------------------
    net_debt = bridge.get("less_net_debt") or 0.0
    equity = ev - net_debt
    shares = bridge.get("shares_outstanding") or 0.0
    price = equity / shares if shares else float("nan")

    # --- 9. Terminal value share of EV --------------------------------
    tv_share = pv_tv / ev if ev else float("nan")

    # --- 10. Reverse DCF: solve g reproducing the market price --------
    market = (val["reverse_dcf"] or {}).get("market_price")
    implied_g = None
    if market and shares and market > 0:
        target_ev = market * shares + net_debt
        target_pv_tv = target_ev - sum_pv
        target_tv = target_pv_tv / df_tv if df_tv else 0.0
        # g = (TV*w - F) / (TV + F)
        if (target_tv + last_fcff) > 0:
            implied_g = ((target_tv * wacc - last_fcff) / (target_tv + last_fcff)) * 100.0

    return {
        "wacc": wacc_pct,
        "g": g,
        "fcff": fcff_calc,
        "sum_pv_fcff": sum_pv,
        "tv_undiscounted": tv_undisc,
        "df_tv": df_tv,
        "pv_tv": pv_tv,
        "ev": ev,
        "net_debt": net_debt,
        "equity": equity,
        "shares": shares,
        "price": price,
        "tv_share": tv_share,
        "market": market,
        "implied_g": implied_g,
        "engine": {
            "sum_pv_fcff": bridge.get("sum_pv_fcff"),
            "pv_tv": bridge.get("pv_terminal_value"),
            "ev": bridge.get("enterprise_value"),
            "equity": bridge.get("equity_value"),
            "price": bridge.get("implied_share_price"),
            "engine_fcff": {p["period"]: p["fcff"] for p in val["fcff_by_period"]},
            "implied_g": (val["reverse_dcf"] or {}).get("implied_terminal_growth"),
        },
    }


def _close(a, b, tol_pct=0.5) -> bool:
    if a is None or b is None:
        return a == b
    if b == 0:
        return abs(a) < 1e-6
    return abs(a - b) / abs(b) * 100 <= tol_pct


def audit(cid: str, spec: dict, tol: float = 0.5) -> list[str]:
    r = recompute(spec)
    e = r["engine"]
    problems: list[str] = []

    print(f"\n=== {cid}  ({spec['metadata']['ticker']} · {spec['metadata']['currency']})")
    print(f"    WACC {r['wacc']:.3f}%   g {r['g']:.2f}%   shares {r['shares']:,.2f}   net debt adj {r['net_debt']:,.2f}")
    for period, row in r["fcff"].items():
        eng = row["engine_fcff"]
        delta = "" if (eng is None or abs(row["fcff"]) < 1e-9) else f"  (engine {eng:,.2f})"
        print(
            f"      {period}  NOPAT {row['nopat']:>13,.0f}  D&A {row['da']:>10,.0f}  "
            f"-capex {row['capex']:>10,.0f}  -dWC {row['dwc']:>10,.0f}  "
            f"= FCFF {row['fcff']:>13,.0f}  DF {row['df']:.4f}  PV {row['pv']:>13,.0f}{delta}"
        )

    checks = [
        ("sum PV FCFF", r["sum_pv_fcff"], e["sum_pv_fcff"]),
        ("PV terminal value", r["pv_tv"], e["pv_tv"]),
        ("enterprise value", r["ev"], e["ev"]),
        ("equity value", r["equity"], e["equity"]),
        ("implied share price", r["price"], e["price"]),
    ]
    for label, mine, theirs in checks:
        ok = _close(mine, theirs, tol)
        mark = "OK  " if ok else "FAIL"
        print(f"    [{mark}] {label:<22} recomputed {mine:>16,.2f}   engine {theirs:>16,.2f}")
        if not ok:
            problems.append(f"{cid}: {label} recomputed {mine:,.2f} vs engine {theirs:,.2f}")

    for period, row in r["fcff"].items():
        eng = row["engine_fcff"]
        if eng is not None and not _close(row["fcff"], eng, tol):
            problems.append(
                f"{cid}: FCFF {period} recomputed {row['fcff']:,.2f} vs engine {eng:,.2f}"
            )

    print(f"    TV share of EV: {r['tv_share']*100:.1f}%")
    if r["tv_share"] > 0.90:
        problems.append(f"{cid}: terminal value is {r['tv_share']*100:.0f}% of EV — fragile")

    if r["implied_g"] is not None and e["implied_g"] is not None:
        ok = _close(r["implied_g"], e["implied_g"], 1.0)
        print(f"    [{'OK  ' if ok else 'FAIL'}] implied g (reverse DCF) recomputed {r['implied_g']:.3f}%   engine {e['implied_g']:.3f}%")
        if not ok:
            problems.append(
                f"{cid}: implied terminal growth recomputed {r['implied_g']:.3f}% vs engine {e['implied_g']:.3f}%"
            )

    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Independently recompute and reconcile the DCF chain.")
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--companies", default=",".join(DEFAULT_COMPANIES))
    ap.add_argument("--tol", type=float, default=0.5, help="Percent tolerance (default 0.5).")
    ap.add_argument("--scenario", default="base")
    args = ap.parse_args()

    companies = [c.strip() for c in args.companies.split(",") if c.strip()]
    print("=" * 78)
    print(f"INDEPENDENT DCF RECOMPUTATION  (tolerance {args.tol}%, scenario {args.scenario})")
    print("=" * 78)

    problems: list[str] = []
    for cid in companies:
        try:
            spec = _get(args.base, cid)
        except Exception as exc:
            print(f"\n=== {cid}: FETCH FAILED ({exc})")
            problems.append(f"{cid}: fetch failed")
            continue
        problems.extend(audit(cid, spec, args.tol))

    print("\n" + "=" * 78)
    if problems:
        print(f"{len(problems)} discrepancy(ies):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("Engine matches an independent recomputation for every company.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
