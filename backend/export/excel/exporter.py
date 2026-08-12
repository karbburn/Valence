from __future__ import annotations

"""
Top-Level Excel Exporter Module.

Generates a 23-tab financial model workbook (.xlsx) from a ModelSpecification.
Enforces openpyxl live formulas and IB/PE visual formatting standards.
"""

from pathlib import Path
from openpyxl import Workbook

from backend.export.excel.render_fcst import (
    render_capex_da,
    render_cost_build,
    render_debt_schedule,
    render_operating_model,
    render_revenue_build,
    render_share_count_schedule,
    render_tax_schedule,
    render_working_capital,
)
from backend.export.excel.render_front import (
    render_cover,
    render_executive_summary,
    render_model_control,
    render_model_guide,
)
from backend.export.excel.render_hist import (
    render_historical_balance_sheet,
    render_historical_cash_flow,
    render_historical_drivers,
    render_historical_income_statement,
    render_historical_ratios,
)
from backend.export.excel.render_qa import (
    render_assumption_log,
    render_data_sources,
    render_methodology_tab,
    render_model_checks_tab,
)
from backend.export.excel.render_val import (
    render_dcf_tab,
    render_reverse_dcf_tab,
    render_scenario_analysis_tab,
    render_sensitivity_tab,
    render_terminal_value_tab,
    render_wacc_tab,
)
from backend.models.spec.model_specification import ModelSpecification


def export_model_to_excel(
    spec: ModelSpecification,
    output_path: str | Path = "backend/export/output/infosys_valuation_model.xlsx",
) -> Path:
    """Export ModelSpecification to a 23-tab openpyxl live-formula workbook."""
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    # Remove default sheet
    if "Sheet" in wb.sheetnames:
        wb.remove(wb["Sheet"])

    # 1. Front Matter Tabs
    render_cover(wb, spec)
    render_model_guide(wb, spec)
    render_executive_summary(wb, spec)
    render_model_control(wb, spec)

    # 2. Historical Financials Tabs
    render_historical_income_statement(wb, spec)
    render_historical_balance_sheet(wb, spec)
    render_historical_cash_flow(wb, spec)
    render_historical_ratios(wb, spec)
    render_historical_drivers(wb, spec)

    # 3. Forecast & Schedules Tabs
    render_operating_model(wb, spec)
    render_revenue_build(wb, spec)
    render_cost_build(wb, spec)
    render_working_capital(wb, spec)
    render_capex_da(wb, spec)
    render_debt_schedule(wb, spec)
    render_tax_schedule(wb, spec)
    render_share_count_schedule(wb, spec)

    # 4. Valuation Tabs
    render_wacc_tab(wb, spec)
    render_dcf_tab(wb, spec)
    render_terminal_value_tab(wb, spec)
    render_sensitivity_tab(wb, spec)
    render_reverse_dcf_tab(wb, spec)
    render_scenario_analysis_tab(wb, spec)

    # 5. QA & Documentation Tabs
    render_data_sources(wb, spec)
    render_assumption_log(wb, spec)
    render_model_checks_tab(wb, spec)
    render_methodology_tab(wb, spec)

    wb.save(str(out_file))

    print(
        f"Excel Export Complete:\n"
        f"  - Total tabs rendered : {len(wb.sheetnames)}\n"
        f"  - Output file path    : {out_file.resolve()}\n"
        f"  - Primary tabs        : 00_Cover, 02_Executive_Summary, 20_Operating_Model, 31_DCF"
    )

    return out_file
