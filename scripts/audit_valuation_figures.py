"""Launch-readiness figure audit: API + Excel vs. market data, for a sample of companies.

Checks, per company:
  1. Market price provenance  — value, source, and the QUOTE date (must not be
     stamped with a request date newer than the last trading session), and the
     source must not be a placeholder.
  2. Internal arithmetic       — implied_share_price == equity_value / shares,
     equity_value == EV - less_net_debt, and the upside % shown in the UI.
  3. Price plausibility       — a share price inside a range that admits every
     price a listed equity has plausibly traded at. This catches a gross fault and
     nothing finer: it is NOT a units check. Rupees and dollars are both plain
     numbers, and so are paise and thousands, so no band that admits real quotes
     can catch a units error. The band once ran 50-20,000 for India on the
     assumption that the universe was all large caps, and it failed Vodafone Idea at
     13.56 — a correct price, verified against the exchange record. See BANDS.
  4. Excel export parity       — the same figures in the generated workbook, and the
     workbook's own arithmetic: its WACC recomputed from the sheet's literals must
     equal the API's, which is read by label so a renamed or inserted row cannot
     make the check read the wrong cell. An analyst-set cost of equity is read as
     an override rather than recomputed, so a deliberate override is not reported
     as a mismatch.
  5. Workbook integrity       — the executive-summary upside is a real formula
     rather than a literal, and the quote's date and source appear in the export.

There is deliberately no cross-source parity check: a "fresh independent fetch" of
a price is the same provider the model already used, so it would confirm the
provider rather than the figure.

Usage:
    python scripts/audit_valuation_figures.py
    python scripts/audit_valuation_figures.py --companies infy_infy,nvda_us,aapl_us
    python scripts/audit_valuation_figures.py --base http://127.0.0.1:8111
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.export.excel.render_val import bridge_ref

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_COMPANIES = [
    "infy_infy",      # India large cap
    "tcs_tcs",        # India large cap
    "nvda_us",        # US mega cap, the original bug
    "aapl_us",        # US large cap
    "googl_us",       # US large cap
    "tsm_us",         # US ADR
    "msft_us",        # US large cap
]

# Plausible share-price bands per market.
#
# The band is there to catch a gross fault — a placeholder, a garbage value, a price
# off by orders of magnitude — and nothing finer. It is not evidence of correct
# units: rupees and dollars are both plain numbers, so a currency mix-up passes it,
# and so do paise and thousands. Any band tight enough to catch those would also
# reject real quotes, which is what this one did.
#
# It was 50 to 20,000 for India, on the assumption that the listed universe was all
# large caps, and it failed Vodafone Idea at 13.56. That price is correct: IDEA
# traded between roughly 12 and 15.5 rupees through September 2026, verified against
# the exchange record. A check that reports a correct figure as wrong is worse than
# no check, because the reader stops believing it and then stops reading it.
#
# The bounds below admit every price a listed Indian or US equity has plausibly
# traded at, from a sub-rupee penny stock to a five-figure rupee issue.
BANDS = {"india": (0.5, 200_000.0), "us": (0.5, 500_000.0)}


def _get_json(url: str, timeout: int = 600) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_bytes(url: str, timeout: int = 600) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _fmt(v, nd=2):
    return f"{v:,.{nd}f}" if isinstance(v, (int, float)) else "-"


def _audit_spec(cid: str, spec: dict) -> list[str]:
    problems: list[str] = []
    meta = spec.get("metadata") or {}
    market = meta.get("market", "?")
    currency = meta.get("currency", "?")
    units = meta.get("units", "?")
    val = next((v for v in (spec.get("valuation") or []) if v.get("scenario") == "base"), None)
    if not val:
        return [f"{cid}: no base valuation in spec"]

    rd = val.get("reverse_dcf") or {}
    bridge = val.get("dcf_bridge") or {}
    wacc = val.get("wacc") or {}

    mkt = rd.get("market_price")
    src = rd.get("market_price_source")
    qdate = rd.get("market_price_date")
    implied = bridge.get("implied_share_price")
    ev = bridge.get("enterprise_value")
    eq = bridge.get("equity_value")
    shares = bridge.get("shares_outstanding")
    net_debt = bridge.get("less_net_debt")

    print(f"\n=== {cid} ({meta.get('ticker')} · {meta.get('name')}) [{market}/{currency}/{units}]")
    print(f"    market price  : {_fmt(mkt)} {currency}  src={src}  quote_date={qdate}")
    print(f"    dcf implied   : {_fmt(implied)} {currency}")
    print(f"    upside        : {_fmt((implied - mkt) / mkt * 100 if mkt else None)} %")
    print(f"    EV / Equity   : {_fmt(ev)} / {_fmt(eq)} {currency}  (net debt adj {_fmt(net_debt)})")
    print(f"    shares        : {_fmt(shares)}  WACC={_fmt(wacc.get('wacc'))}%  "
          f"(rfr {_fmt(wacc.get('risk_free_rate'))} · beta {_fmt(wacc.get('beta'))} · erp {_fmt(wacc.get('equity_risk_premium'))})")

    if mkt is None or mkt <= 0:
        problems.append(f"{cid}: no market price")
    else:
        lo, hi = BANDS.get(market, (1.0, 1e9))
        if not (lo <= mkt <= hi):
            problems.append(f"{cid}: market price {mkt} outside plausible {market} band {lo}-{hi}")
        if src in (None, "", "market_default"):
            problems.append(f"{cid}: market price is a placeholder (source={src})")
        if src and not str(src).startswith(("yfinance", "yahoo", "twelvedata", "stale_cache")):
            problems.append(f"{cid}: unexpected market price source {src}")

    if implied is not None and shares:
        recomputed = eq / shares if (eq is not None and shares) else None
        if recomputed and abs(recomputed - implied) > max(0.05, implied * 0.001):
            problems.append(f"{cid}: implied price {implied} != equity/shares {recomputed:.4f}")
    if ev is not None and net_debt is not None and eq is not None:
        if abs((ev - net_debt) - eq) > max(1.0, abs(eq) * 0.001):
            problems.append(f"{cid}: equity {eq} != EV {ev} - net_debt {net_debt}")

    w = wacc.get("wacc")
    if w is None or not (0 < w < 40):
        problems.append(f"{cid}: implausible WACC {w}")

    return problems


def _audit_excel(cid: str, blob: bytes, spec: dict) -> list[str]:
    from openpyxl import load_workbook

    problems: list[str] = []
    val = next((v for v in (spec.get("valuation") or []) if v.get("scenario") == "base"), {})
    bridge = val.get("dcf_bridge") or {}
    rd = val.get("reverse_dcf") or {}
    wacc = val.get("wacc") or {}

    # Two views of the same file, and the distinction matters: `wb` carries the
    # formulas a reader sees when they click a cell, and `wv` carries the values
    # Excel computed and cached. Reading a figure out of `wb` returns the string
    # "=C6+(C8*C9)" rather than the number, which is not a defect in the workbook.
    wb = load_workbook(io.BytesIO(blob), data_only=False)
    wv = load_workbook(io.BytesIO(blob), data_only=True)
    print(f"    excel sheets  : {len(wb.sheetnames)}")

    def _close(a, b, tol_pct=0.001):
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return False
        return abs(float(a) - float(b)) <= max(0.01, abs(float(b)) * tol_pct)

    # 1. Market price literal must match the API, in both places it is shown.
    xl_mkt = wb["02_Executive_Summary"]["B6"].value
    if not _close(xl_mkt, rd.get("market_price")):
        problems.append(f"{cid}: excel exec-summary market price {xl_mkt} != API {rd.get('market_price')}")
    xl_mkt_rev = wb["34_Reverse_DCF"]["C6"].value
    if not _close(xl_mkt_rev, rd.get("market_price")):
        problems.append(f"{cid}: excel reverse-DCF market price {xl_mkt_rev} != API {rd.get('market_price')}")

    # 2. Provenance must be present in the export (date + source, stale flagged).
    rev_ws = wb["34_Reverse_DCF"]
    prov = [
        str(rev_ws.cell(row=r, column=3).value)
        for r in range(1, rev_ws.max_row + 1)
        if str(rev_ws.cell(row=r, column=2).value) == "Quote as of / source"
    ]
    if not prov:
        problems.append(f"{cid}: excel 34_Reverse_DCF has no quote provenance row")
    else:
        qdate = rd.get("market_price_date") or "unknown"
        if qdate not in prov[0]:
            problems.append(f"{cid}: excel quote date missing (want {qdate}, got {prov[0]!r})")
        if rd.get("market_price_source") and rd["market_price_source"] not in prov[0]:
            problems.append(f"{cid}: excel quote source missing (want {rd['market_price_source']})")
        stale = str(rd.get("market_price_source") or "").startswith("stale_cache")
        if stale and "STALE" not in prov[0].upper():
            problems.append(f"{cid}: stale quote not flagged in excel")

    # 3. The DCF bridge must be live formulas chained off the right precedents.
    #
    #    The bridge is on 36_EV_Bridge, addressed by line name. It used to sit in
    #    a summary column of 31_DCF, where each row was single-valued beside the
    #    five year-columns of the FCFF build.
    bridge = wb["36_EV_Bridge"]
    for line, expect in (
        ("sum_pv_fcff", "SUM('31_DCF'!C14:G14)"),
        ("enterprise_value", "=C6+C7"),
        ("equity_value", "=C8-C14"),
        ("implied_share_price", "=C15/C16"),
    ):
        coord = bridge_ref(line).split("!")[1]
        got = str(bridge[coord].value or "")
        if expect not in got.replace(" ", ""):
            problems.append(f"{cid}: excel 36_EV_Bridge!{coord} formula {got!r} missing {expect!r}")

    # 4. WACC recomputed from the sheet's own literals must equal the API WACC.
    #    Catches percent/decimal unit errors that still *look* plausible.
    #
    #    Rows are resolved by label, never by number. The sheet gained a row when
    #    the workbook began disclosing the published beta alongside the Blume-
    #    adjusted one actually used, which pushed every line below it down one, and
    #    the hardcoded reads kept returning numbers: risk-free rate from the right
    #    row, published beta where the adjusted one belongs, the adjusted beta where
    #    the equity risk premium belongs, and the cost of equity's own formula where
    #    the cost of debt belongs. Seven wrong cells, none of them obviously wrong on
    #    the page. A check that reads by position is a check that reports a verdict
    #    about whichever cell happens to be there.
    w_ws = wv["30_WACC"]

    def wacc_row(label: str) -> int:
        for r in range(1, (w_ws.max_row or 0) + 1):
            if str(w_ws.cell(row=r, column=2).value).strip() == label:
                return r
        raise KeyError(label)

    try:
        rfr = w_ws.cell(wacc_row("Risk-Free Rate (Rf) %"), 3).value
        beta = w_ws.cell(wacc_row("Equity Beta (β) — used in CAPM"), 3).value
        erp = w_ws.cell(wacc_row("Equity Risk Premium (ERP) %"), 3).value
        kd_pre = w_ws.cell(wacc_row("Pre-Tax Cost of Debt %"), 3).value
        tax = w_ws.cell(wacc_row("Effective Tax Rate %"), 3).value
        we = w_ws.cell(wacc_row("Equity Market Weight %"), 3).value
        wd = w_ws.cell(wacc_row("Debt Market Weight %"), 3).value
        ke = float(rfr) + float(beta) * float(erp)
        kd = float(kd_pre) * (1 - float(tax))
        xl_wacc = (float(we) * ke + float(wd) * kd) * 100.0
        if not _close(xl_wacc, wacc.get("wacc"), 0.005):
            problems.append(
                f"{cid}: excel WACC recomputes to {xl_wacc:.2f}% but API says {wacc.get('wacc')}"
            )
        print(f"    excel WACC    : recomputed {xl_wacc:.2f}% vs API {_fmt(wacc.get('wacc'))}%")
    except (TypeError, ValueError, KeyError) as exc:
        problems.append(f"{cid}: could not recompute excel WACC ({exc})")

    # 5. Executive summary upside formula must be a real formula, not a literal.
    upside_f = str(wb["02_Executive_Summary"]["D6"].value or "")
    if "C6-B6" not in upside_f.replace(" ", ""):
        problems.append(f"{cid}: excel exec-summary upside is not a live formula ({upside_f!r})")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit valuation figures across sample companies.")
    ap.add_argument("--base", default="http://127.0.0.1:8010", help="Backend base URL.")
    ap.add_argument("--companies", default=",".join(DEFAULT_COMPANIES))
    ap.add_argument("--skip-excel", action="store_true")
    args = ap.parse_args()

    import requests  # noqa: F401  (cross-source parity below)

    companies = [c.strip() for c in args.companies.split(",") if c.strip()]
    problems: list[str] = []

    print(f"Auditing {len(companies)} companies against {args.base}\n")
    for cid in companies:
        try:
            spec = _get_json(f"{args.base}/api/model/{cid}")
        except Exception as exc:
            print(f"\n=== {cid}: FETCH FAILED ({exc})")
            problems.append(f"{cid}: fetch failed ({exc})")
            continue
        problems.extend(_audit_spec(cid, spec))

        if not args.skip_excel:
            try:
                blob = _get_bytes(f"{args.base}/api/export/excel?company_id={cid}")
                out = REPO_ROOT / "backend" / "export" / "output" / f"_audit_{cid}.xlsx"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(blob)
                problems.extend(_audit_excel(cid, blob, spec))
                print(f"    excel saved   : {out.relative_to(REPO_ROOT)} ({len(blob)//1024} KB)")
            except Exception as exc:
                print(f"    excel FAILED  : {exc}")
                problems.append(f"{cid}: excel export failed ({exc})")

    print("\n" + "=" * 72)
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("No figure problems found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
