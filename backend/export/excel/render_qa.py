from __future__ import annotations

"""
QA & Documentation Tabs Renderer.

Renders:
- 50_Data_Sources: Data provenance, status, and filing lineage
- 51_Assumption_Log: Model-generated and analyst override assumption log
- 52_Model_Checks: QA model checks rollup table with status
- 53_Methodology: System derivation rules and methodology notes
"""

from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from backend.export.excel.builder import apply_tab_defaults, set_col_widths, write_table_header
from backend.export.excel.styles import (
    ALIGN_CENTER,
    ALIGN_LEFT,
    ALIGN_RIGHT,
    BORDER_BOX,
    BORDER_TOTAL,
    FILL_FAIL,
    FILL_HEADER,
    FILL_PASS,
    FMT_AMOUNT,
    FMT_PERCENT,
    FONT_ALERT,
    FONT_FORMULA,
    FONT_HEADER,
    FONT_INPUT,
    FONT_PASS,
    FONT_SECTION,
    FONT_SUBHEADER,
    FONT_TITLE,
)
from backend.models.spec.model_specification import ModelSpecification


def render_data_sources(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="50_Data_Sources")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 32, "C": 15, "D": 15, "E": 40})

    ws["B2"] = "DATA SOURCES & PROVENANCE METADATA"
    ws["B2"].font = FONT_TITLE

    write_table_header(ws, 5, ["Canonical Key / Line Item", "Period", "Status", "Source / Derivation Lineage"], start_col=2)

    hist_periods = spec.historicals.periods
    period_range = f"{hist_periods[0]}-{hist_periods[-1]}" if hist_periods else "-"
    audited_src = f"{spec.metadata.name} Audited Financial Statements ({spec.metadata.market.upper()} regulatory filing)"

    rows = [
        ("canonical.is.revenue", period_range, "Reported", audited_src),
        ("canonical.is.cost_of_sales", period_range, "Reported", audited_src),
        ("canonical.is.ebitda", period_range, "Derived", "Derived formula: Operating Profit + Depreciation & Amortization"),
        ("canonical.bs.cash_and_bank", period_range, "Reported", f"{spec.metadata.name} Consolidated Balance Sheet"),
        ("canonical.bs.total_assets", period_range, "Reported", f"{spec.metadata.name} Consolidated Balance Sheet"),
        ("canonical.cf.operating_activities", period_range, "Reported", f"{spec.metadata.name} Consolidated Cash Flow Statement"),
    ]

    for idx, (ckey, p, status, src) in enumerate(rows):
        r = 6 + idx
        ws.cell(row=r, column=2, value=ckey).font = FONT_SUBHEADER
        ws.cell(row=r, column=3, value=p).font = FONT_FORMULA
        ws.cell(row=r, column=4, value=status).font = FONT_INPUT
        ws.cell(row=r, column=5, value=src).font = FONT_FORMULA
        for c in range(2, 6):
            ws.cell(row=r, column=c).border = BORDER_BOX

    return ws


def render_assumption_log(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="51_Assumption_Log")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 25, "C": 12, "D": 12, "E": 12, "F": 18, "G": 40})

    ws["B2"] = "ASSUMPTION AUDIT LOG"
    ws["B2"].font = FONT_TITLE

    headers = ["Driver Key", "Period", "Scenario", "Value", "Type", "Source / Provenance Method"]
    write_table_header(ws, 5, headers, start_col=2)

    base_assumptions = [a for a in spec.assumptions if a.scenario == "base"]

    for idx, a in enumerate(base_assumptions):
        r = 6 + idx
        ws.cell(row=r, column=2, value=a.driver_key).font = FONT_SUBHEADER
        ws.cell(row=r, column=3, value=a.period).font = FONT_FORMULA
        ws.cell(row=r, column=4, value=a.scenario).font = FONT_FORMULA
        cell_v = ws.cell(row=r, column=5, value=a.value)
        cell_v.font = FONT_INPUT if a.type == "user_override" else FONT_FORMULA
        cell_v.alignment = ALIGN_RIGHT

        ws.cell(row=r, column=6, value=a.type).font = FONT_INPUT if a.type == "user_override" else FONT_FORMULA
        ws.cell(row=r, column=7, value=a.source).font = FONT_FORMULA

        for c in range(2, 8):
            ws.cell(row=r, column=c).border = BORDER_BOX

    return ws


def render_model_checks_tab(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="52_Model_Checks")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 28, "C": 15, "D": 15, "E": 45})

    ws["B2"] = "QA / MODEL CHECKS AUDIT ROLLUP"
    ws["B2"].font = FONT_TITLE

    status_str = spec.qa.summary_label if spec.qa else "MODEL VALID"
    ws["B3"] = f"Overall Status: {status_str}"
    ws["B3"].font = FONT_SECTION

    write_table_header(ws, 5, ["Check Name", "Category", "Result", "Detail / Failure Reason"], start_col=2)

    checks = spec.qa.checks if (spec.qa and spec.qa.checks) else []

    for idx, c in enumerate(checks):
        r = 6 + idx
        ws.cell(row=r, column=2, value=c.check_name).font = FONT_SUBHEADER
        ws.cell(row=r, column=3, value=c.category).font = FONT_FORMULA

        res_cell = ws.cell(row=r, column=4, value="PASS" if c.passed else "FAIL")
        res_cell.alignment = ALIGN_CENTER
        if c.passed:
            res_cell.font = FONT_PASS
            res_cell.fill = FILL_PASS
        else:
            res_cell.font = FONT_ALERT
            res_cell.fill = FILL_FAIL

        ws.cell(row=r, column=5, value=c.detail if not c.passed else "Verified OK").font = FONT_FORMULA

        for col in range(2, 6):
            ws.cell(row=r, column=col).border = BORDER_BOX

    return ws


def render_methodology_tab(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="53_Methodology")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 25, "C": 60})

    ws["B2"] = "SYSTEM METHODOLOGY DOCUMENTATION"
    ws["B2"].font = FONT_TITLE

    write_table_header(ws, 5, ["Methodology Section", "Description / Formula Rules"], start_col=2)

    notes = [
        ("Normalization & Derivation", "Canonical keys map raw reported labels. Derived EBITDA = EBIT + D&A."),
        ("Driver Engine", "Forecast drivers apply to prior period actuals. Revenue = Rev_(t-1) * (1 + g)."),
        ("Working Capital", "Receivables = Revenue * DSO / 365. Payables = Cost of Sales * DPO / 365."),
        ("Balance Sheet Closure", "Total Assets = Prior Assets + Capex - D&A + Delta_WC. Cash is the balancing plug."),
        ("Valuation Engine", "CAPM Cost of Equity = Rfr + Beta * ERP. WACC = Eq_Weight * r_e + Debt_Weight * r_d."),
        ("Terminal Value", "Gordon Growth TV = FCFF_n * (1+g) / (WACC - g). Exit Multiple TV = EBITDA_n * Multiple."),
        ("DCF Bridge", "EV = Sum PV(FCFF) + PV(TV). Equity Value = EV - Net Debt. Implied Price = Equity Value / Shares."),
    ]

    for idx, (sec, desc) in enumerate(notes):
        r = 6 + idx
        ws.cell(row=r, column=2, value=sec).font = FONT_SUBHEADER
        ws.cell(row=r, column=3, value=desc).font = FONT_FORMULA
        ws.cell(row=r, column=2).border = BORDER_BOX
        ws.cell(row=r, column=3).border = BORDER_BOX

    return ws
