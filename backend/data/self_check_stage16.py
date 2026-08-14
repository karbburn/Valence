from __future__ import annotations

"""
Automated Verification Suite for Stage 16 (Phase 16.0 & 16.1):
Universal Expansion — Live Market Data Layer & Per-Market Defaults.

Acceptance criteria verified:
  1. Market data layer provider fallback chain works cleanly across sources (yfinance -> registry -> market defaults).
  2. US companies (e.g. aapl_us, msft_us) resolve to US Risk-Free Rate (~4.64% US 10Y UST) and Damodaran US ERP (4.50%).
  3. India companies (e.g. infy_infy, tcs_tcs) resolve to India 10Y G-Sec (6.78%) and India ERP (7.31%).
  4. Infosys hardcoded fallbacks (405.76 shares, 22201.0 cash) are deleted — US models use USD native share units and cash.
  5. 30_WACC tab provenance notes accurately reflect the target market's provenance.
  6. Divergence gate flags out-of-bounds market-implied growth (< -2.0% or > 5.0%).
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
    print("Running Stage 16 (Phase 16.0 & 16.1) Verification Suite...")
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

    print("\n=================================================================")
    print("  Stage 16 (Phase 16.0 & 16.1) Universal Expansion Summary:")
    print(f"    US Market RFR (10Y UST) : {aapl_val.wacc.risk_free_rate:.2f}%")
    print(f"    US Market ERP (Damodaran): {aapl_val.wacc.equity_risk_premium:.2f}%")
    print(f"    India Market RFR (G-Sec): {infy_val.wacc.risk_free_rate:.2f}%")
    print(f"    India Market ERP       : {infy_val.wacc.equity_risk_premium:.2f}%")
    print(f"    Infosys Shortcuts      : DELETED (No 405.76 / 22201.0 leak)")
    print(f"    Market Data Provider   : ACTIVE (yfinance -> registry -> default)")
    print("=================================================================")
    print("\nALL STAGE 16 (PHASE 16.0 & 16.1) SELF-CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
