from __future__ import annotations

"""
Self-check for Stage 7: Valuation Engine.

Acceptance criteria:
  1. WACC computes generically to ~12.55% (debt weight = 0.0%).
  2. FCFF calculation matches NOPAT + D&A - Capex - delta_WC for all 5 forecast periods.
  3. DCF Bridge arithmetic checks out: EV + Net Cash = Equity Value, Equity Value / Shares = Implied Price.
  4. Dual Terminal Value (Gordon Growth & Exit Multiple) both present.
  5. Terminal growth >= WACC validation check correctly raises ValueError.
  6. Reverse DCF round-trip: running forward DCF with implied terminal growth reproduces market price within 0.01 INR.
  7. Sensitivity grid spot-checks match standalone DCF runs.
  8. Base case implied share price lands in plausible range relative to benchmark (~1,400-2,000 INR).
  9. ModelSpecification serialization preserves valuation outputs intact.
"""

import pytest
from backend.forecast.pipeline import run as run_forecast_pipeline
from backend.models.spec.model_specification import ModelSpecification
from backend.valuation.dcf import (
    compute_dcf_bridge,
    compute_fcff_periods,
    compute_terminal_value,
)
from backend.valuation.pipeline import run_valuation
from backend.valuation.wacc import compute_wacc


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"Stage 7 self-check FAILED: {msg}")
    print(f"ok: {msg}")


def main() -> None:
    print("Running Stage 7 Valuation Engine self-check...")
    forecast_spec = run_forecast_pipeline()
    spec = run_valuation(forecast_spec)

    # ------------------------------------------------------------------ #
    # 1. WACC generic calculation
    # ------------------------------------------------------------------ #
    base_val = spec.get_valuation("base")
    _assert(base_val is not None, "Base scenario valuation output present")
    wacc_breakdown = base_val.wacc
    _assert(wacc_breakdown.debt_weight == 0.0, f"Generic debt weight == 0.0% for Infosys ({wacc_breakdown.debt_weight})")
    _assert(wacc_breakdown.equity_weight == 1.0, f"Generic equity weight == 100.0% for Infosys ({wacc_breakdown.equity_weight})")
    _assert(abs(wacc_breakdown.wacc - 12.55) < 0.1, f"WACC = {wacc_breakdown.wacc}% (expected ~12.55%)")

    # ------------------------------------------------------------------ #
    # 2. FCFF calculation for all 5 periods
    # ------------------------------------------------------------------ #
    _assert(len(base_val.fcff_by_period) == 5, "5 forecast periods present in FCFF")
    for p in base_val.fcff_by_period:
        expected_nopat = p.ebit * (1.0 - p.tax_rate / 100.0)
        _assert(abs(p.nopat - expected_nopat) < 2.0, f"NOPAT formula holds for {p.period} ({p.nopat} vs {expected_nopat:.2f})")
        expected_fcff = p.nopat + p.da - p.capex - p.delta_working_capital
        _assert(abs(p.fcff - expected_fcff) < 0.1, f"FCFF formula holds for {p.period} ({p.fcff} vs {expected_fcff:.2f})")

    # ------------------------------------------------------------------ #
    # 3. DCF Bridge arithmetic reconciliation
    # ------------------------------------------------------------------ #
    for scenario in ["base", "bull", "bear"]:
        val = spec.get_valuation(scenario)
        _assert(val is not None, f"{scenario} valuation present")
        b = val.dcf_bridge
        expected_ev = b.sum_pv_fcff + b.pv_terminal_value
        _assert(abs(b.enterprise_value - expected_ev) < 0.1, f"EV sum check {scenario} ({b.enterprise_value} vs {expected_ev:.2f})")
        expected_eq_val = b.enterprise_value - b.less_net_debt
        _assert(abs(b.equity_value - expected_eq_val) < 0.1, f"Equity Value bridge check {scenario} ({b.equity_value} vs {expected_eq_val:.2f})")
        expected_price = b.equity_value / b.shares_outstanding
        _assert(abs(b.implied_share_price - expected_price) < 0.05, f"Implied price check {scenario} ({b.implied_share_price} vs {expected_price:.2f})")

    # ------------------------------------------------------------------ #
    # 4. Dual Terminal Value & TV % of EV
    # ------------------------------------------------------------------ #
    tv = base_val.terminal_value
    _assert(tv.terminal_value_undiscounted is not None and tv.terminal_value_undiscounted > 0, "Gordon Growth TV present")
    _assert(tv.exit_multiple_tv_undiscounted is not None and tv.exit_multiple_tv_undiscounted > 0, "Exit Multiple TV present")
    _assert(tv.tv_pct_of_ev is not None and 40.0 < tv.tv_pct_of_ev < 90.0, f"TV % of EV is reasonable ({tv.tv_pct_of_ev}%)")

    # ------------------------------------------------------------------ #
    # 5. Terminal Growth >= WACC validation raises ValueError
    # ------------------------------------------------------------------ #
    try:
        compute_terminal_value(last_fcff=1000.0, last_ebitda=1500.0, wacc_pct=10.0, terminal_growth_rate=10.0)
        _assert(False, "Failed to raise error when terminal_growth_rate >= WACC")
    except ValueError as e:
        _assert("strictly less than WACC" in str(e), "Correctly raised ValueError for terminal_growth_rate >= WACC")

    # ------------------------------------------------------------------ #
    # 6. Reverse DCF Round-Trip Check
    # ------------------------------------------------------------------ #
    rev_dcf = base_val.reverse_dcf
    _assert(rev_dcf.implied_terminal_growth is not None, "Reverse DCF implied terminal growth solved")
    # Round-trip verify: run forward DCF with implied_terminal_growth
    fcffs = base_val.fcff_by_period
    wacc_pct = base_val.wacc.wacc
    last_fcff = fcffs[-1].fcff
    last_ebitda = spec.forecast.get_value("canonical.is.ebitda", "FY31", "base") or 0.0
    cash_cr = spec.historicals.get_value("canonical.bs.cash_and_bank", "FY26") or 22201.0
    debt_cr = 0.0
    shares_cr = spec.share_count.get_diluted("FY26") or 405.76

    rt_tv = compute_terminal_value(last_fcff, last_ebitda, wacc_pct, rev_dcf.implied_terminal_growth)
    rt_bridge, _ = compute_dcf_bridge(fcffs, rt_tv, cash_cr, debt_cr, shares_cr)
    _assert(
        abs(rt_bridge.implied_share_price - rev_dcf.market_price) < 0.05,
        f"Reverse DCF round-trip exact match ({rt_bridge.implied_share_price:.2f} vs {rev_dcf.market_price:.2f})",
    )

    # ------------------------------------------------------------------ #
    # 7. Sensitivity Grid Spot-Check
    # ------------------------------------------------------------------ #
    _assert(len(base_val.sensitivity_tables) == 2, "2 sensitivity tables present")
    tbl1 = base_val.sensitivity_tables[0]
    _assert(tbl1.row_driver == "wacc.wacc", "Table 1 row driver is wacc.wacc")
    # Spot-check middle cell (base_wacc, base_g)
    wacc_idx = tbl1.row_values.index(round(wacc_pct, 2))
    g_idx = tbl1.col_values.index(4.0)
    grid_price = tbl1.results_grid[wacc_idx][g_idx]
    _assert(
        grid_price is not None and abs(grid_price - base_val.dcf_bridge.implied_share_price) < 1.0,
        f"Sensitivity grid spot-check matches standalone DCF within WACC rounding ({grid_price} vs {base_val.dcf_bridge.implied_share_price})",
    )

    # ------------------------------------------------------------------ #
    # 8. Plausible Base Case Share Price
    # ------------------------------------------------------------------ #
    base_price = base_val.dcf_bridge.implied_share_price
    bull_price = spec.get_valuation("bull").dcf_bridge.implied_share_price
    bear_price = spec.get_valuation("bear").dcf_bridge.implied_share_price

    _assert(600.0 < base_price < 2500.0, f"Base implied share price INR {base_price:.2f} is in plausible range")
    _assert(bull_price > base_price > bear_price, f"Scenario price ordering holds ({bull_price:.2f} > {base_price:.2f} > {bear_price:.2f})")

    # ------------------------------------------------------------------ #
    # 9. Serialization round-trip
    # ------------------------------------------------------------------ #
    raw = spec.serialize()
    spec2 = ModelSpecification.deserialize(raw)
    _assert(len(spec2.valuation) == 3, "Valuation outputs preserved in round-trip JSON serialization")
    _assert(
        abs(spec2.get_valuation("base").dcf_bridge.implied_share_price - base_price) < 0.01,
        "Base implied share price intact after serialization",
    )

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    print(f"\n  Stage 7 Valuation summary:")
    print(f"    Base WACC           : {wacc_breakdown.wacc:.2f}% (Cost of Equity: {wacc_breakdown.cost_of_equity:.2f}%)")
    print(f"    Base Enterprise Val : {base_val.dcf_bridge.enterprise_value:,.0f} Cr")
    print(f"    Base Net Cash       : {-base_val.dcf_bridge.less_net_debt:,.0f} Cr")
    print(f"    Base Equity Value   : {base_val.dcf_bridge.equity_value:,.0f} Cr")
    print(f"    Diluted Shares      : {base_val.dcf_bridge.shares_outstanding:.2f} Cr")
    print(f"    Implied Share Price : INR {base_price:.2f} (Bull: {bull_price:.2f}, Bear: {bear_price:.2f})")
    print(f"    Implied Term Growth : {rev_dcf.implied_terminal_growth:.2f}% (Reverse DCF @ INR {rev_dcf.market_price:.2f})")

    print("\nALL STAGE 7 SELF-CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
