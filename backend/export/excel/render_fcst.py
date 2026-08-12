from __future__ import annotations

"""
Forecast & Supporting Schedules Tabs Renderer.

Renders:
- 20_Operating_Model: Combined 3-statement forecast model (FY27-FY31) with live formulas
- 21_Revenue_Build: Segment revenue forecast & growth
- 22_Cost_Build: Cost structure & EBITDA forecast
- 23_Working_Capital: Receivables & payables forecast (DSO/DPO)
- 24_Capex_D&A: Capex % revenue & D&A schedule
- 25_Debt_Schedule: Generic debt schedule (thin for zero debt)
- 26_Tax_Schedule: Effective tax rate forecast
- 27_Share_Count: Diluted share count schedule
"""

from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from backend.export.excel.builder import apply_tab_defaults, set_col_widths, write_table_header
from backend.export.excel.styles import (
    ALIGN_LEFT,
    ALIGN_RIGHT,
    BORDER_BOX,
    BORDER_TOTAL,
    FMT_AMOUNT,
    FMT_DAYS,
    FMT_PERCENT,
    FMT_PRICE,
    FONT_FORMULA,
    FONT_HEADER,
    FONT_INPUT,
    FONT_SECTION,
    FONT_SUBHEADER,
    FONT_TITLE,
    FONT_TOTAL,
)
from backend.models.spec.forecast import FORECAST_PERIODS
from backend.models.spec.model_specification import ModelSpecification


def get_assumption_value(spec: ModelSpecification, driver_key: str, period: str, scenario: str = "base") -> float:
    for a in spec.assumptions:
        if a.driver_key == driver_key and a.scenario == scenario and (a.period == period or a.period == "all"):
            return a.value
    return 0.0


def render_operating_model(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="20_Operating_Model")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 38, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18})

    ws["B2"] = f"{spec.metadata.name.upper()} — FORECAST OPERATING MODEL"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = f"Scenario: Base Case | Reporting Currency: {spec.metadata.currency} | Units: {spec.metadata.units}"
    ws["B3"].font = FONT_SECTION

    headers = ["Line Item"] + FORECAST_PERIODS
    write_table_header(ws, 5, headers, start_col=2)

    fcst_items = [
        ("canonical.is.revenue", "Revenue from Operations", True, FMT_AMOUNT),
        ("canonical.is.cost_of_sales", "Cost of Sales", False, FMT_AMOUNT),
        ("canonical.is.gross_profit", "Gross Profit", True, FMT_AMOUNT),
        ("canonical.is.ebitda", "EBITDA", True, FMT_AMOUNT),
        ("canonical.is.depreciation_amortization", "Depreciation & Amortization", False, FMT_AMOUNT),
        ("canonical.is.operating_profit", "Operating Profit (EBIT)", True, FMT_AMOUNT),
        ("canonical.is.other_income", "Other Income", False, FMT_AMOUNT),
        ("canonical.is.finance_cost", "Finance Cost", False, FMT_AMOUNT),
        ("canonical.is.pbt", "Profit Before Tax (PBT)", True, FMT_AMOUNT),
        ("canonical.is.tax", "Tax Expense", False, FMT_AMOUNT),
        ("canonical.is.net_profit", "Net Profit After Tax", True, FMT_AMOUNT),
        ("canonical.bs.trade_receivables", "Trade Receivables", False, FMT_AMOUNT),
        ("canonical.bs.trade_payables", "Trade Payables", False, FMT_AMOUNT),
        ("canonical.bs.cash_and_bank", "Cash & Cash Equivalents", False, FMT_AMOUNT),
        ("canonical.bs.total_assets", "Total Assets", True, FMT_AMOUNT),
        ("canonical.bs.total_equity", "Total Equity", True, FMT_AMOUNT),
        ("canonical.bs.total_liabilities_and_equity", "Total Liabilities & Equity", True, FMT_AMOUNT),
        ("canonical.cf.operating_activities", "Operating Cash Flow", True, FMT_AMOUNT),
        ("canonical.cf.investing_activities", "Investing Cash Flow (Capex)", True, FMT_AMOUNT),
    ]

    for idx, (ckey, label, is_tot, fmt) in enumerate(fcst_items):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_TOTAL if is_tot else FONT_SUBHEADER

        for p_idx, p in enumerate(FORECAST_PERIODS):
            c = 3 + p_idx
            val = spec.forecast.get_value(ckey, p, "base")
            cell = ws.cell(row=r, column=c, value=round(val, 2) if val is not None else "-")
            cell.font = FONT_TOTAL if is_tot else FONT_FORMULA
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_TOTAL if is_tot else BORDER_BOX

    return ws


def render_revenue_build(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="21_Revenue_Build")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18})

    ws["B2"] = "REVENUE BUILD & YoY GROWTH FORECAST"
    ws["B2"].font = FONT_TITLE

    headers = ["Segment / Driver"] + FORECAST_PERIODS
    write_table_header(ws, 5, headers, start_col=2)

    rev_rows = [
        ("Assumed Revenue Growth Rate %", FMT_PERCENT, True, [get_assumption_value(spec, "revenue_growth", p) / 100.0 for p in FORECAST_PERIODS]),
        ("Consolidated Revenue (INR Cr)", FMT_AMOUNT, False, ["='20_Operating_Model'!C6", "='20_Operating_Model'!D6", "='20_Operating_Model'!E6", "='20_Operating_Model'!F6", "='20_Operating_Model'!G6"]),
    ]

    for idx, (label, fmt, is_inp, vals) in enumerate(rev_rows):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_SUBHEADER
        for p_idx, val in enumerate(vals):
            c = 3 + p_idx
            cell = ws.cell(row=r, column=c, value=val)
            cell.font = FONT_INPUT if is_inp else FONT_FORMULA
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_BOX

    return ws


def render_cost_build(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="22_Cost_Build")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18})

    ws["B2"] = "COST BUILD & MARGIN FORECAST"
    ws["B2"].font = FONT_TITLE

    headers = ["Cost Component"] + FORECAST_PERIODS
    write_table_header(ws, 5, headers, start_col=2)

    cost_rows = [
        ("EBITDA Margin %", FMT_PERCENT, True, [get_assumption_value(spec, "ebitda_margin", p) / 100.0 for p in FORECAST_PERIODS]),
        ("EBITDA (INR Cr)", FMT_AMOUNT, False, ["='20_Operating_Model'!C9", "='20_Operating_Model'!D9", "='20_Operating_Model'!E9", "='20_Operating_Model'!F9", "='20_Operating_Model'!G9"]),
        ("Operating Profit Margin %", FMT_PERCENT, True, [get_assumption_value(spec, "ebit_margin", p) / 100.0 for p in FORECAST_PERIODS]),
        ("Operating Profit (INR Cr)", FMT_AMOUNT, False, ["='20_Operating_Model'!C11", "='20_Operating_Model'!D11", "='20_Operating_Model'!E11", "='20_Operating_Model'!F11", "='20_Operating_Model'!G11"]),
    ]

    for idx, (label, fmt, is_inp, vals) in enumerate(cost_rows):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_SUBHEADER
        for p_idx, val in enumerate(vals):
            c = 3 + p_idx
            cell = ws.cell(row=r, column=c, value=val)
            cell.font = FONT_INPUT if is_inp else FONT_FORMULA
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_BOX

    return ws


def render_working_capital(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="23_Working_Capital")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18})

    ws["B2"] = "WORKING CAPITAL FORECAST (DSO / DPO)"
    ws["B2"].font = FONT_TITLE

    headers = ["Working Capital Driver"] + FORECAST_PERIODS
    write_table_header(ws, 5, headers, start_col=2)

    wc_rows = [
        ("Days Sales Outstanding (DSO)", FMT_DAYS, True, [get_assumption_value(spec, "dso_days", p) for p in FORECAST_PERIODS]),
        ("Trade Receivables (INR Cr)", FMT_AMOUNT, False, ["='20_Operating_Model'!C17", "='20_Operating_Model'!D17", "='20_Operating_Model'!E17", "='20_Operating_Model'!F17", "='20_Operating_Model'!G17"]),
        ("Days Payables Outstanding (DPO)", FMT_DAYS, True, [get_assumption_value(spec, "dpo_days", p) for p in FORECAST_PERIODS]),
        ("Trade Payables (INR Cr)", FMT_AMOUNT, False, ["='20_Operating_Model'!C18", "='20_Operating_Model'!D18", "='20_Operating_Model'!E18", "='20_Operating_Model'!F18", "='20_Operating_Model'!G18"]),
    ]

    for idx, (label, fmt, is_inp, vals) in enumerate(wc_rows):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_SUBHEADER
        for p_idx, val in enumerate(vals):
            c = 3 + p_idx
            cell = ws.cell(row=r, column=c, value=val)
            cell.font = FONT_INPUT if is_inp else FONT_FORMULA
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_BOX

    return ws


def render_capex_da(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="24_Capex_D&A")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18})

    ws["B2"] = "CAPEX & DEPRECIATION SCHEDULE"
    ws["B2"].font = FONT_TITLE

    headers = ["Capex & D&A Component"] + FORECAST_PERIODS
    write_table_header(ws, 5, headers, start_col=2)

    rows = [
        ("Capex % Revenue", FMT_PERCENT, True, [get_assumption_value(spec, "capex_pct_revenue", p) / 100.0 for p in FORECAST_PERIODS]),
        ("Capex Outflow (INR Cr)", FMT_AMOUNT, False, ["='20_Operating_Model'!C24", "='20_Operating_Model'!D24", "='20_Operating_Model'!E24", "='20_Operating_Model'!F24", "='20_Operating_Model'!G24"]),
        ("D&A % Revenue", FMT_PERCENT, True, [get_assumption_value(spec, "da_pct_revenue", p) / 100.0 for p in FORECAST_PERIODS]),
        ("D&A Expense (INR Cr)", FMT_AMOUNT, False, ["='20_Operating_Model'!C10", "='20_Operating_Model'!D10", "='20_Operating_Model'!E10", "='20_Operating_Model'!F10", "='20_Operating_Model'!G10"]),
    ]

    for idx, (label, fmt, is_inp, vals) in enumerate(rows):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_SUBHEADER
        for p_idx, val in enumerate(vals):
            c = 3 + p_idx
            cell = ws.cell(row=r, column=c, value=val)
            cell.font = FONT_INPUT if is_inp else FONT_FORMULA
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_BOX

    return ws


def render_debt_schedule(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="25_Debt_Schedule")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18})

    ws["B2"] = "DEBT & BORROWINGS SCHEDULE (GENERIC)"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "Note: Infosys carries zero long-term/short-term borrowings (thin zero-debt schedule)"
    ws["B3"].font = FONT_SECTION

    headers = ["Debt Component"] + FORECAST_PERIODS
    write_table_header(ws, 5, headers, start_col=2)

    debt_rows = [
        ("Opening Debt Balance (INR Cr)", FMT_AMOUNT, ["=0.0"] * len(FORECAST_PERIODS)),
        ("Debt Drawdowns (INR Cr)", FMT_AMOUNT, ["=0.0"] * len(FORECAST_PERIODS)),
        ("Scheduled Repayments (INR Cr)", FMT_AMOUNT, ["=0.0"] * len(FORECAST_PERIODS)),
        ("Closing Debt Balance (INR Cr)", FMT_AMOUNT, ["=0.0"] * len(FORECAST_PERIODS)),
        ("Interest Expense (INR Cr)", FMT_AMOUNT, ["=0.0"] * len(FORECAST_PERIODS)),
    ]

    for idx, (label, fmt, vals) in enumerate(debt_rows):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_SUBHEADER
        for p_idx, val in enumerate(vals):
            c = 3 + p_idx
            cell = ws.cell(row=r, column=c, value=val)
            cell.font = FONT_FORMULA
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_BOX

    return ws


def render_tax_schedule(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="26_Tax_Schedule")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18})

    ws["B2"] = "EFFECTIVE TAX RATE SCHEDULE"
    ws["B2"].font = FONT_TITLE

    headers = ["Tax Parameter"] + FORECAST_PERIODS
    write_table_header(ws, 5, headers, start_col=2)

    tax_rows = [
        ("Effective Tax Rate %", FMT_PERCENT, True, [get_assumption_value(spec, "tax_rate", p) / 100.0 for p in FORECAST_PERIODS]),
        ("PBT (INR Cr)", FMT_AMOUNT, False, ["='20_Operating_Model'!C14", "='20_Operating_Model'!D14", "='20_Operating_Model'!E14", "='20_Operating_Model'!F14", "='20_Operating_Model'!G14"]),
        ("Tax Expense (INR Cr)", FMT_AMOUNT, False, ["='20_Operating_Model'!C15", "='20_Operating_Model'!D15", "='20_Operating_Model'!E15", "='20_Operating_Model'!F15", "='20_Operating_Model'!G15"]),
    ]

    for idx, (label, fmt, is_inp, vals) in enumerate(tax_rows):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_SUBHEADER
        for p_idx, val in enumerate(vals):
            c = 3 + p_idx
            cell = ws.cell(row=r, column=c, value=val)
            cell.font = FONT_INPUT if is_inp else FONT_FORMULA
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_BOX

    return ws


def render_share_count_schedule(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="27_Share_Count")
    apply_tab_defaults(ws, freeze_cell="C6")
    periods = spec.share_count.periods if spec.share_count else ["FY24", "FY25", "FY26", "FY27", "FY28", "FY29", "FY30", "FY31"]
    set_col_widths(ws, {"A": 5, "B": 35, "C": 15, "D": 15, "E": 15, "F": 15, "G": 15, "H": 15, "I": 15, "J": 15})

    ws["B2"] = "DILUTED SHARE COUNT SCHEDULE"
    ws["B2"].font = FONT_TITLE

    headers = ["Share Count Basis"] + periods
    write_table_header(ws, 5, headers, start_col=2)

    shares_val = spec.share_count.get_diluted("FY26") if spec.share_count else 412.4545

    ws.cell(row=6, column=2, value="Diluted Shares Outstanding (Cr)").font = FONT_SUBHEADER
    for idx, p in enumerate(periods):
        c = 3 + idx
        val = spec.share_count.get_diluted(p) if spec.share_count else shares_val
        cell = ws.cell(row=6, column=c, value=round(val, 4) if val else shares_val)
        cell.font = FONT_INPUT if "FY27" in p or "FY28" in p or "FY29" in p or "FY30" in p or "FY31" in p else FONT_FORMULA
        cell.number_format = FMT_AMOUNT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    return ws
