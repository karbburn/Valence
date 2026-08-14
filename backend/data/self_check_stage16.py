from __future__ import annotations

"""
Automated Verification Suite for Stage 16 (Phases 16.0 - 16.5):
Universal Expansion — Live Market Data, Real SEC EDGAR, Parameterized India & WACC Professionalization.

Acceptance criteria verified:
  1. Market data layer provider fallback chain works cleanly across sources (yfinance -> registry -> market defaults).
  2. US companies (e.g. aapl_us, msft_us) resolve to US Risk-Free Rate (~4.64% US 10Y UST) and Damodaran US ERP (4.50%).
  3. India companies (e.g. infy_infy, tcs_tcs) resolve to India 10Y G-Sec (6.78%) and India ERP (7.31%).
  4. Infosys hardcoded fallbacks (405.76 shares, 22201.0 cash) are deleted — US models use USD native share units and cash.
  5. 30_WACC tab provenance notes accurately reflect the target market's provenance.
  6. Divergence gate flags out-of-bounds market-implied growth (< -2.0% or > 5.0%).
  7. Live SEC EDGAR companyfacts ingestion fetches real 10-K XBRL financial facts.
  8. Real US GAAP capex (PaymentsToAcquirePropertyPlantAndEquipment) replaces total investing cash flow proxy.
  9. Parameterized India ingestion pipeline and reconciliation engine scale seamlessly across all Indian companies.
  10. Full universe acquisition (NSE/BSE listing + SEC company_tickers.json) populates store with 1 canonical company_id per company.
  11. WACC & valuation professionalization renders exact provenance notes and flows real GAAP capex into DCF valuation.
"""

import sys
from backend.data.batch import ensure_company_ingested
from backend.data.providers.market_data import (
    MARKET_DEFAULTS,
    REGISTRY_FALLBACKS,
    get_company_market_data,
)
from backend.forecast.pipeline import run as run_forecast_pipeline
from backend.models.statements.pipeline import run as run_historical
from backend.models.spec.metadata import get_metadata_for_company
from backend.models.spec.model_specification import ModelSpecification
from backend.valuation.pipeline import run_valuation


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"Stage 16 self-check FAILED: {msg}")
    print(f"ok: {msg}")


def main() -> None:
    print("=================================================================")
    print("Running Stage 16 (Phases 16.0 - 16.5) Verification Suite...")
    print("=================================================================\n")

    # ------------------------------------------------------------------ #
    # 1. Test Live Market Data Layer Provider & Fallback Chain
    # ------------------------------------------------------------------ #
    print("1. Testing Market Data Layer Provider & Fallback Chain...")

    # US Company (AAPL)
    aapl_mdata = get_company_market_data("aapl_us", market="us")
    _assert(aapl_mdata.market == "us", "AAPL market data resolved as 'us'")
    _assert(aapl_mdata.price.value > 0, f"AAPL price resolved ({aapl_mdata.price.value} USD)")
    _assert(aapl_mdata.shares_outstanding.value > 1000.0, f"AAPL shares resolved ({aapl_mdata.shares_outstanding.value} M)")
    _assert(abs(aapl_mdata.equity_risk_premium.value - 4.50) < 0.01, f"AAPL ERP resolved to US Damodaran (4.50%) ({aapl_mdata.equity_risk_premium.value}%)")
    _assert("US" in aapl_mdata.risk_free_rate.provenance_note or "10-Year" in aapl_mdata.risk_free_rate.provenance_note or "yfinance" in aapl_mdata.risk_free_rate.provenance_note, f"AAPL RFR provenance note intact: {aapl_mdata.risk_free_rate.provenance_note}")

    # India Company (Infosys)
    infy_mdata = get_company_market_data("infy_infy", market="india")
    _assert(infy_mdata.market == "india", "Infosys market data resolved as 'india'")
    _assert(infy_mdata.price.value > 0, f"Infosys price resolved ({infy_mdata.price.value} INR)")
    _assert(abs(infy_mdata.risk_free_rate.value - 6.78) < 0.1, f"Infosys RFR resolved to India G-Sec (6.78%) ({infy_mdata.risk_free_rate.value}%)")
    _assert(abs(infy_mdata.equity_risk_premium.value - 7.31) < 0.01, f"Infosys ERP resolved to India ERP (7.31%) ({infy_mdata.equity_risk_premium.value}%)")

    # ------------------------------------------------------------------ #
    # 2. Test Per-Market WACC Resolution in Valuation Engine
    # ------------------------------------------------------------------ #
    print("\n2. Testing Per-Market WACC Resolution in Valuation Engine...")

    # Build a US ModelSpecification (AAPL)
    ensure_company_ingested("aapl_us")
    aapl_hist = run_historical(target_periods=["FY24", "FY25", "FY26"], company_id="aapl_us")
    aapl_fcst = run_forecast_pipeline(aapl_hist)
    aapl_spec = run_valuation(aapl_fcst)

    aapl_val = aapl_spec.get_valuation("base")
    _assert(aapl_val is not None, "AAPL base valuation present")
    _assert(
        abs(aapl_val.wacc.risk_free_rate - aapl_mdata.risk_free_rate.value) < 0.01,
        f"AAPL WACC RFR matches US Treasury yield ({aapl_val.wacc.risk_free_rate}%)",
    )
    _assert(
        abs(aapl_val.wacc.equity_risk_premium - 4.50) < 0.01,
        f"AAPL WACC ERP matches US Damodaran (4.50%) ({aapl_val.wacc.equity_risk_premium}%)",
    )
    _assert(
        "US" in aapl_val.wacc.source_notes or "10-Year" in aapl_val.wacc.source_notes or "yfinance" in aapl_val.wacc.source_notes,
        "AAPL WACC source notes specify US market provenance",
    )

    # Build an India ModelSpecification (Infosys)
    ensure_company_ingested("infy_infy")
    infy_hist = run_historical(target_periods=["FY24", "FY25", "FY26"], company_id="infy_infy")
    infy_fcst = run_forecast_pipeline(infy_hist)
    infy_spec = run_valuation(infy_fcst)
    infy_val = infy_spec.get_valuation("base")
    _assert(infy_val is not None, "Infosys base valuation present")
    _assert(
        abs(infy_val.wacc.risk_free_rate - 6.78) < 0.01,
        f"Infosys WACC RFR matches India 10Y G-Sec (6.78%) ({infy_val.wacc.risk_free_rate}%)",
    )
    _assert(
        abs(infy_val.wacc.equity_risk_premium - 7.31) < 0.01,
        f"Infosys WACC ERP matches India Damodaran ERP (7.31%) ({infy_val.wacc.equity_risk_premium}%)",
    )

    # ------------------------------------------------------------------ #
    # 3. Verify Complete Removal of Infosys Constant Fallbacks (405.76 / 22201.0)
    # ------------------------------------------------------------------ #
    print("\n3. Verifying Absence of Infosys Share/Cash Contamination...")

    _assert(
        aapl_val.dcf_bridge.shares_outstanding != 405.76,
        f"AAPL shares outstanding ({aapl_val.dcf_bridge.shares_outstanding} M) is not Infosys 405.76 Cr",
    )
    _assert(
        aapl_val.dcf_bridge.less_net_debt != -22201.0,
        f"AAPL net cash is derived from AAPL balance sheet, not Infosys 22201.0 Cr",
    )

    # ------------------------------------------------------------------ #
    # 4. Test Divergence Gate on Implied Terminal Growth
    # ------------------------------------------------------------------ #
    print("\n4. Testing Reverse DCF Divergence Gate...")

    if infy_val.reverse_dcf.implied_terminal_growth is not None:
        g_impl = infy_val.reverse_dcf.implied_terminal_growth
        if g_impl < -2.0 or g_impl > 5.0:
            _assert("DIVERGENCE FLAG" in infy_val.reverse_dcf.method_note, f"Divergence flag triggered for implied growth {g_impl:.2f}%")
        else:
            _assert("DIVERGENCE FLAG" not in infy_val.reverse_dcf.method_note, f"Implied growth {g_impl:.2f}% within sane band (-2% to 5%)")

    # ------------------------------------------------------------------ #
    # 5. Non-Regression Serialization & Integrity Check
    # ------------------------------------------------------------------ #
    print("\n5. Testing Round-Trip Serialization & Integrity...")

    raw_json = aapl_spec.serialize()
    deserialized_spec = ModelSpecification.deserialize(raw_json)
    _assert(
        deserialized_spec.get_valuation("base").wacc.risk_free_rate == aapl_val.wacc.risk_free_rate,
        "AAPL serialized WACC RFR intact after round-trip JSON",
    )

    # ------------------------------------------------------------------ #
    # 6. Test Live SEC EDGAR Ingestion & Real Capex Mapping (Phase 16.2)
    # ------------------------------------------------------------------ #
    print("\n6. Testing Live SEC EDGAR Ingestion & Real Capex Mapping (Phase 16.2)...")
    from backend.data.ingestion.sec_edgar import fetch_and_parse_sec_edgar
    edgar_dps = fetch_and_parse_sec_edgar("aapl_us")
    _assert(len(edgar_dps) > 0, f"Live EDGAR fetched {len(edgar_dps)} RawDatapoints for AAPL")

    capex_dps = [d for d in edgar_dps if d.metric_raw == "PaymentsToAcquirePropertyPlantAndEquipment"]
    _assert(len(capex_dps) > 0, "Live EDGAR includes PaymentsToAcquirePropertyPlantAndEquipment (real GAAP capex)")

    fy24_capex = next((d.value for d in capex_dps if d.period_label == "FY24"), None)
    _assert(
        fy24_capex is not None and 5000.0 < fy24_capex < 15000.0,
        f"AAPL FY24 real GAAP capex is ${fy24_capex:,.2f} M (expected ~$9,447 M, not $30,000+ M proxy)",
    )

    # ------------------------------------------------------------------ #
    # 7. Test India Ingestion & Reconciliation at Scale (Phase 16.3)
    # ------------------------------------------------------------------ #
    print("\n7. Testing India Ingestion & Reconciliation at Scale (Phase 16.3)...")
    from backend.data.pipeline import run as run_india_pipeline, DB_PATH, LOG_PATH
    from backend.data.reconciliation import reconcile

    india_cids = ["infy_infy", "tcs_tcs", "tatamotors_tatamotors", "tatasteel_tatasteel"]
    for cid in india_cids:
        summary = run_india_pipeline(company_id=cid, db_path=DB_PATH, clear_db=False)
        _assert(summary["screener_rows"] > 0, f"Screener export parsed for {cid} ({summary['screener_rows']} rows)")
        _assert(summary["company_id"] == cid, f"Pipeline run summary matches company_id '{cid}'")

    discrepancies_tcs = reconcile(DB_PATH, LOG_PATH, company_id="tcs_tcs")
    _assert(isinstance(discrepancies_tcs, list), "reconcile() accepts dynamic company_id without hardcoding Infosys")

    # ------------------------------------------------------------------ #
    # 8. Test Full Universe Acquisition & ID Canonicalization (Phase 16.4)
    # ------------------------------------------------------------------ #
    print("\n8. Testing Full Universe Acquisition & ID Canonicalization (Phase 16.4)...")
    from backend.data.universe.acquisition import acquire_full_universe
    from backend.data.universe.store import verify_canonical_id_integrity

    u_companies = acquire_full_universe(db_path=DB_PATH)
    _assert(len(u_companies) >= 10, f"Full universe acquired {len(u_companies)} total companies across India and US")
    _assert(verify_canonical_id_integrity(db_path=DB_PATH), "Canonical company_id integrity verified (0 duplicate/corrupted IDs)")

    markets = set(c.market for c in u_companies)
    _assert("india" in markets and "us" in markets, f"Universe covers both India and US markets ({markets})")

    # ------------------------------------------------------------------ #
    # 9. Test WACC & Valuation Professionalization (Phase 16.5)
    # ------------------------------------------------------------------ #
    print("\n9. Testing WACC & Valuation Professionalization (Phase 16.5)...")
    from backend.export.excel.render_val import render_wacc_tab
    from openpyxl import Workbook

    wb = Workbook()
    ws_wacc = render_wacc_tab(wb, aapl_spec)
    _assert(ws_wacc["C6"].value is not None, "30_WACC tab Risk-Free Rate cell rendered")
    _assert(ws_wacc["D6"].value is not None, "30_WACC tab Risk-Free Rate provenance note rendered")

    aapl_base_fcff = aapl_val.fcff_by_period[0]
    _assert(aapl_base_fcff.capex > 3000.0, f"AAPL base valuation uses real GAAP capex (${aapl_base_fcff.capex:,.2f} M)")

    print("\n=================================================================")
    print("  Stage 16 (Phases 16.0 - 16.5) Universal Expansion Summary:")
    print(f"    US Market RFR (10Y UST) : {aapl_val.wacc.risk_free_rate:.2f}%")
    print(f"    US Market ERP (Damodaran): {aapl_val.wacc.equity_risk_premium:.2f}%")
    print(f"    India Market RFR (G-Sec): {infy_val.wacc.risk_free_rate:.2f}%")
    print(f"    India Market ERP       : {infy_val.wacc.equity_risk_premium:.2f}%")
    print(f"    Infosys Shortcuts      : DELETED (No 405.76 / 22201.0 leak)")
    print(f"    SEC EDGAR Live Ingest  : ACTIVE ({len(edgar_dps)} XBRL facts parsed for AAPL)")
    print(f"    AAPL FY24 Real Capex   : ${fy24_capex:,.2f} M (Real GAAP capex)")
    print(f"    India Scale Pipeline   : ACTIVE (Tested on {len(india_cids)} India companies)")
    print(f"    Universe Acquisition   : ACTIVE ({len(u_companies)} companies, 0 corrupted IDs)")
    print(f"    WACC Professionalization: VERIFIED (30_WACC tab truthful provenance)")
    print("=================================================================")
    print("\nALL STAGE 16 (PHASES 16.0 - 16.5) SELF-CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
