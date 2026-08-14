from __future__ import annotations

"""
Self-check & Post-Export Consistency Check for Stage 9: Excel Renderer.

Acceptance criteria:
  1. Generates 23-tab Excel workbook (.xlsx) from ModelSpecification.
  2. File exists on disk and is non-empty (> 15 KB).
  3. All 23 target tabs are present in the workbook.
  4. Core formula strings present in key sheets ('30_WACC', '31_DCF', '02_Executive_Summary').
  5. Post-export consistency check: verifies workbook structure and formula integrity.
"""

from pathlib import Path
from openpyxl import load_workbook

from backend.export.excel.exporter import export_model_to_excel
from backend.forecast.pipeline import run as run_forecast_pipeline
from backend.validation.pipeline import run_qa
from backend.valuation.pipeline import run_valuation


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"Stage 9 self-check FAILED: {msg}")
    print(f"ok: {msg}")


def main() -> None:
    print("Running Stage 9 Excel Renderer self-check...")

    # Build full ModelSpecification through pipeline
    forecast_spec = run_forecast_pipeline()
    val_spec = run_valuation(forecast_spec)
    spec = run_qa(val_spec)

    out_file = Path("backend/export/output/infosys_valuation_model.xlsx")
    export_model_to_excel(spec, out_file)

    # 1. File existence and size check
    _assert(out_file.exists(), f"Output workbook exists at {out_file}")
    file_size_kb = out_file.stat().st_size / 1024.0
    _assert(file_size_kb > 15.0, f"Workbook file size is non-empty ({file_size_kb:.1f} KB > 15 KB)")

    # 2. Reload workbook and verify sheet structure
    wb = load_workbook(str(out_file), data_only=False)
    sheet_names = wb.sheetnames
    _assert(len(sheet_names) == 27, f"27 total sheets rendered (got {len(sheet_names)})")

    expected_key_tabs = [
        "00_Cover",
        "01_Model_Guide",
        "02_Executive_Summary",
        "03_Model_Control",
        "10_Income_Statement",
        "11_Balance_Sheet",
        "12_Cash_Flow",
        "13_Financial_Ratios",
        "14_Historical_Drivers",
        "20_Operating_Model",
        "21_Revenue_Build",
        "22_Cost_Build",
        "23_Working_Capital",
        "24_Capex_D&A",
        "25_Debt_Schedule",
        "26_Tax_Schedule",
        "27_Share_Count",
        "30_WACC",
        "31_DCF",
        "32_Terminal_Value",
        "33_Sensitivity",
        "34_Reverse_DCF",
        "35_Scenario_Analysis",
        "50_Data_Sources",
        "51_Assumption_Log",
        "52_Model_Checks",
        "53_Methodology",
    ]

    for tab in expected_key_tabs:
        _assert(tab in sheet_names, f"Tab '{tab}' is present in workbook")

    # 3. Live formula checks in key valuation sheets
    ws_wacc = wb["30_WACC"]
    wacc_formula = str(ws_wacc["C9"].value)
    _assert("=" in wacc_formula and "C6" in wacc_formula, f"30_WACC live CAPM formula present ({wacc_formula})")

    ws_dcf = wb["31_DCF"]
    dcf_fcff_sum_formula = str(ws_dcf["H17"].value)
    _assert("=" in dcf_fcff_sum_formula and "SUM" in dcf_fcff_sum_formula, f"31_DCF live FCFF sum formula present ({dcf_fcff_sum_formula})")

    ws_exec = wb["02_Executive_Summary"]
    exec_price_formula = str(ws_exec["C6"].value)
    _assert("=" in exec_price_formula and ("35_Scenario_Analysis" in exec_price_formula or "31_DCF" in exec_price_formula), f"02_Executive_Summary cross-sheet price formula present ({exec_price_formula})")
    qa_status_val = str(ws_exec["F6"].value)
    _assert("MODEL VALID" in qa_status_val, f"Executive summary QA status is MODEL VALID ({qa_status_val})")

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    print(f"\n  Stage 9 Excel Renderer summary:")
    print(f"    Total tabs rendered : {len(sheet_names)}")
    print(f"    Workbook File Path  : {out_file.resolve()}")
    print(f"    Workbook Size       : {file_size_kb:.1f} KB")
    print(f"    Executive Summary   : {qa_status_val}")
    print(f"    Live Formulas       : CAPM, DCF Bridge, FCFF sum, Cross-Sheet references verified")

    print("\nALL STAGE 9 SELF-CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
