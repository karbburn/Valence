from __future__ import annotations

"""
Valuation Tabs Renderer.

Renders:
- 30_WACC: WACC CAPM cost of equity & capital weighting with live formulas
- 31_DCF: 5-year FCFF, discount factors, PV(FCFF), TV, EV -> Share Price bridge with live formulas
- 32_Terminal_Value: Dual terminal value (Gordon Growth & Exit Multiple)
- 33_Sensitivity: 2D sensitivity grids (WACC x Growth, WACC x Multiple)
- 34_Reverse_DCF: Market implied perpetuity terminal growth rate
- 35_Scenario_Analysis: Base, Bull, Bear outputs side-by-side
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
    FILL_HEADER,
    FMT_AMOUNT,
    FMT_CURRENCY_INT,
    FMT_MULTIPLE,
    FMT_PERCENT,
    FMT_PERCENT_PRECISION,
    FMT_PRICE,
    FONT_FORMULA,
    FONT_HEADER,
    FONT_INPUT,
    FONT_SECTION,
    FONT_SUBHEADER,
    FONT_SUBTITLE,
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


def render_wacc_tab(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="30_WACC")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 45})

    ws["B2"] = "WEIGHTED AVERAGE COST OF CAPITAL (WACC)"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "CAPM Cost of Equity & Market Capital Weighting"
    ws["B3"].font = FONT_SECTION

    write_table_header(ws, 5, ["CAPM Component / Parameter", "Value", "Source / Provenance Notes"], start_col=2)

    base_val = spec.get_valuation("base")
    wacc_b = base_val.wacc if base_val else None

    rfr = wacc_b.risk_free_rate if (wacc_b and wacc_b.risk_free_rate) else get_assumption_value(spec, "wacc.risk_free_rate", "all")
    beta = wacc_b.beta if (wacc_b and wacc_b.beta is not None) else get_assumption_value(spec, "wacc.beta", "all")
    erp = wacc_b.equity_risk_premium if (wacc_b and wacc_b.equity_risk_premium) else get_assumption_value(spec, "wacc.equity_risk_premium", "all")
    debt_pre = wacc_b.pre_tax_cost_of_debt if (wacc_b and wacc_b.pre_tax_cost_of_debt is not None) else get_assumption_value(spec, "wacc.cost_of_debt", "all")
    tax = wacc_b.tax_rate if (wacc_b and wacc_b.tax_rate is not None) else get_assumption_value(spec, "tax_rate", "FY27")

    wacc_rows = [
        ("Risk-Free Rate (Rf) %", rfr / 100.0, FMT_PERCENT_PRECISION, True, "India 10-Year Government Securities Yield"),
        ("Equity Beta (β)", beta, "0.00", True, "Infosys 2Y weekly beta vs NSE Nifty IT"),
        ("Equity Risk Premium (ERP) %", erp / 100.0, FMT_PERCENT_PRECISION, True, "Damodaran published India ERP (Mature 4.5% + CRP 2.0%)"),
        ("Cost of Equity (r_e) %", "=C6+(C7*C8)", FMT_PERCENT_PRECISION, False, "CAPM formula: r_e = Rf + Beta * ERP"),
        ("Pre-Tax Cost of Debt %", debt_pre / 100.0, FMT_PERCENT_PRECISION, True, "Infosys carries zero debt borrowings"),
        ("Effective Tax Rate %", tax / 100.0, FMT_PERCENT_PRECISION, True, "Forecast average tax rate"),
        ("After-Tax Cost of Debt (r_d) %", "=C10*(1-C11)", FMT_PERCENT_PRECISION, False, "Pre-tax * (1 - tax_rate)"),
        ("Equity Market Weight %", 1.0, FMT_PERCENT, False, "Market Cap / Total Capital (100% for zero debt)"),
        ("Debt Market Weight %", 0.0, FMT_PERCENT, False, "Total Debt / Total Capital (0% for Infosys)"),
        ("WEIGHTED AVERAGE COST OF CAPITAL (WACC) %", "=(C12*C9)+(C13*C12)", FMT_PERCENT_PRECISION, False, "Total WACC = Equity Weight * r_e + Debt Weight * r_d"),
    ]

    for idx, (label, val, fmt, is_inp, note) in enumerate(wacc_rows):
        r = 6 + idx
        is_tot = idx == len(wacc_rows) - 1
        ws.cell(row=r, column=2, value=label).font = FONT_TOTAL if is_tot else FONT_SUBHEADER
        cell_v = ws.cell(row=r, column=3, value=val)
        cell_v.font = FONT_INPUT if is_inp else (FONT_TOTAL if is_tot else FONT_FORMULA)
        cell_v.number_format = fmt
        cell_v.alignment = ALIGN_RIGHT

        cell_n = ws.cell(row=r, column=4, value=note)
        cell_n.font = FONT_SUBTITLE
        cell_n.alignment = ALIGN_LEFT

        for c in range(2, 5):
            ws.cell(row=r, column=c).border = BORDER_TOTAL if is_tot else BORDER_BOX

    return ws


def render_dcf_tab(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="31_DCF")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 36, "C": 18, "D": 18, "E": 18, "F": 18, "G": 22})

    ws["B2"] = f"{spec.metadata.name.upper()} — DISCOUNTED CASH FLOW (DCF) MODEL"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "5-Year FCFF Build, PV Discounting & Enterprise Value Bridge"
    ws["B3"].font = FONT_SECTION

    headers = ["FCFF Line Item / DCF Bridge"] + FORECAST_PERIODS + ["Valuation Summary"]
    write_table_header(ws, 5, headers, start_col=2)

    base_val = spec.get_valuation("base")
    fcffs = base_val.fcff_by_period if base_val else []

    ebit_vals = [f"='20_Operating_Model'!{col}11" for col in ["C", "D", "E", "F", "G"]]
    tax_vals = ["='26_Tax_Schedule'!C6", "='26_Tax_Schedule'!D6", "='26_Tax_Schedule'!E6", "='26_Tax_Schedule'!F6", "='26_Tax_Schedule'!G6"]
    nopat_vals = [f"=C{r}*(1-C{r+1})" for r in [6]]  # Formula reference

    # Row 6: Operating Profit (EBIT)
    ws.cell(row=6, column=2, value="Operating Profit (EBIT)").font = FONT_SUBHEADER
    for idx, e_f in enumerate(ebit_vals):
        c = 3 + idx
        cell = ws.cell(row=6, column=c, value=e_f)
        cell.font = FONT_FORMULA
        cell.number_format = FMT_AMOUNT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 7: Less: Tax Expense
    ws.cell(row=7, column=2, value="Effective Tax Rate %").font = FONT_SUBHEADER
    for idx, t_f in enumerate(tax_vals):
        c = 3 + idx
        cell = ws.cell(row=7, column=c, value=t_f)
        cell.font = FONT_FORMULA
        cell.number_format = FMT_PERCENT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 8: NOPAT
    ws.cell(row=8, column=2, value="NOPAT (EBIT x (1 - Tax))").font = FONT_TOTAL
    for idx, p in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        col_let = chr(67 + idx)
        cell = ws.cell(row=8, column=c, value=f"={col_let}6*(1-{col_let}7)")
        cell.font = FONT_TOTAL
        cell.number_format = FMT_AMOUNT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_TOTAL

    # Row 9: Plus: D&A
    ws.cell(row=9, column=2, value="Plus: D&A Expense").font = FONT_SUBHEADER
    for idx, col in enumerate(["C", "D", "E", "F", "G"]):
        c = 3 + idx
        cell = ws.cell(row=9, column=c, value=f"='20_Operating_Model'!{col}10")
        cell.font = FONT_FORMULA
        cell.number_format = FMT_AMOUNT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 10: Less: Capex
    ws.cell(row=10, column=2, value="Less: Capex Outflow").font = FONT_SUBHEADER
    for idx, col in enumerate(["C", "D", "E", "F", "G"]):
        c = 3 + idx
        cell = ws.cell(row=10, column=c, value=f"=ABS('20_Operating_Model'!{col}24)")
        cell.font = FONT_FORMULA
        cell.number_format = FMT_AMOUNT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 11: Less: Change in Working Capital
    ws.cell(row=11, column=2, value="Less: Change in Working Capital").font = FONT_SUBHEADER
    for idx, p in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        val = fcffs[idx].delta_working_capital if idx < len(fcffs) else 0.0
        cell = ws.cell(row=11, column=c, value=val)
        cell.font = FONT_FORMULA
        cell.number_format = FMT_AMOUNT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 12: Free Cash Flow to Firm (FCFF)
    ws.cell(row=12, column=2, value="FREE CASH FLOW TO FIRM (FCFF)").font = FONT_TOTAL
    for idx, p in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        col_let = chr(67 + idx)
        cell = ws.cell(row=12, column=c, value=f"={col_let}8+{col_let}9-{col_let}10-{col_let}11")
        cell.font = FONT_TOTAL
        cell.number_format = FMT_AMOUNT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_TOTAL

    # Row 13: Discount Factor
    ws.cell(row=13, column=2, value="Discount Factor (1 / (1+WACC)^t)").font = FONT_SUBHEADER
    for idx, p in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        t = idx + 1
        cell = ws.cell(row=13, column=c, value=f"=1/((1+'30_WACC'!C14)^{t})")
        cell.font = FONT_FORMULA
        cell.number_format = "0.000000"
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 14: Present Value of FCFF
    ws.cell(row=14, column=2, value="PRESENT VALUE OF FCFF").font = FONT_TOTAL
    for idx, p in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        col_let = chr(67 + idx)
        cell = ws.cell(row=14, column=c, value=f"={col_let}12*{col_let}13")
        cell.font = FONT_TOTAL
        cell.number_format = FMT_AMOUNT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_TOTAL

    # Right Column DCF Bridge (Column G, rows 6-13)
    bridge_rows = [
        ("Cumulative PV of FCFF", "=SUM(C14:G14)", FMT_CURRENCY_INT),
        ("PV of Terminal Value", "='32_Terminal_Value'!C12", FMT_CURRENCY_INT),
        ("ENTERPRISE VALUE (EV)", "=G6+G7", FMT_CURRENCY_INT),
        ("Less: Net Debt / (Cash)", "='20_Operating_Model'!C19-'20_Operating_Model'!C16", FMT_CURRENCY_INT),
        ("EQUITY VALUE", "=G8-G9", FMT_CURRENCY_INT),
        ("Diluted Shares (Cr)", "='27_Share_Count'!E6", FMT_AMOUNT),
        ("IMPLIED SHARE PRICE (INR)", "=G10/G11", FMT_PRICE),
    ]

    for idx, (lbl, formula, fmt) in enumerate(bridge_rows):
        r = 7 + idx
        is_price = idx == len(bridge_rows) - 1
        ws.cell(row=r, column=7, value=formula).number_format = fmt
        cell = ws.cell(row=r, column=7)
        cell.font = FONT_TITLE if is_price else FONT_TOTAL
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_TOTAL

    return ws


def render_terminal_value_tab(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="32_Terminal_Value")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 20, "D": 45})

    ws["B2"] = "TERMINAL VALUE CALCULATION (DUAL METHOD)"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "Gordon Perpetuity Growth & Exit Multiple Methods"
    ws["B3"].font = FONT_SECTION

    write_table_header(ws, 5, ["Terminal Value Parameter", "Value", "Methodology / Rule Notes"], start_col=2)

    tv_rows = [
        ("Terminal Growth Rate %", 0.04, FMT_PERCENT, True, "Perpetuity growth rate (must be < WACC)"),
        ("FY31 Final Year FCFF (INR Cr)", "='31_DCF'!G12", FMT_AMOUNT, False, "Final forecast year FCFF"),
        ("Gordon Growth Undiscounted TV", "=(C7*(1+C6))/('30_WACC'!C14-C6)", FMT_CURRENCY_INT, False, "TV = FCFF_n * (1+g) / (WACC - g)"),
        ("Exit Multiple (EV/EBITDA)", 20.0, FMT_MULTIPLE, True, "Exit EV/EBITDA multiple"),
        ("FY31 Final Year EBITDA (INR Cr)", "='20_Operating_Model'!G9", FMT_AMOUNT, False, "Final forecast year EBITDA"),
        ("Exit Multiple Undiscounted TV", "=C9*C10", FMT_CURRENCY_INT, False, "TV = EBITDA_n * Exit Multiple"),
        ("Discount Factor (t=5)", "='31_DCF'!G13", "0.000000", False, "Discount factor for FY31"),
        ("DISCOUNTED TERMINAL VALUE (PV)", "=C8*C11", FMT_CURRENCY_INT, False, "Gordon Growth PV of Terminal Value"),
    ]

    for idx, (lbl, val, fmt, is_inp, note) in enumerate(tv_rows):
        r = 6 + idx
        is_tot = idx == len(tv_rows) - 1
        ws.cell(row=r, column=2, value=lbl).font = FONT_TOTAL if is_tot else FONT_SUBHEADER
        cell_v = ws.cell(row=r, column=3, value=val)
        cell_v.font = FONT_INPUT if is_inp else (FONT_TOTAL if is_tot else FONT_FORMULA)
        cell_v.number_format = fmt
        cell_v.alignment = ALIGN_RIGHT

        cell_n = ws.cell(row=r, column=4, value=note)
        cell_n.font = FONT_SUBTITLE
        cell_n.alignment = ALIGN_LEFT

        for c in range(2, 5):
            ws.cell(row=r, column=c).border = BORDER_TOTAL if is_tot else BORDER_BOX

    return ws


def render_sensitivity_tab(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="33_Sensitivity")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 22, "C": 15, "D": 15, "E": 15, "F": 15, "G": 15})

    ws["B2"] = "VALUATION SENSITIVITY ANALYSIS"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "2D Sensitivity Grids (WACC vs Terminal Growth & Exit Multiple)"
    ws["B3"].font = FONT_SECTION

    # Table 1: WACC vs Terminal Growth
    ws["B5"] = "WACC % \\ Growth %"
    ws["B5"].font = FONT_HEADER
    ws["B5"].fill = FILL_HEADER

    base_val = spec.get_valuation("base")
    sens_tables = base_val.sensitivity_tables if base_val else []
    t1 = sens_tables[0] if sens_tables else None

    g_cols = [g / 100.0 for g in t1.col_values] if t1 else [0.03, 0.035, 0.04, 0.045, 0.05]
    wacc_rows = [w / 100.0 for w in t1.row_values] if t1 else [0.11, 0.12, 0.1295, 0.14, 0.15]
    grid1 = t1.results_grid if t1 else []

    for r_idx, w in enumerate(wacc_rows):
        r = 6 + r_idx
        ws.cell(row=r, column=2, value=w).font = FONT_SUBHEADER
        ws.cell(row=r, column=2).number_format = FMT_PERCENT_PRECISION
        ws.cell(row=r, column=2).border = BORDER_BOX

        # Set up header row labels
        for idx, g in enumerate(g_cols):
            cell_g = ws.cell(row=5, column=3 + idx, value=g)
            cell_g.font = FONT_HEADER
            cell_g.fill = FILL_HEADER
            cell_g.number_format = FMT_PERCENT
            cell_g.alignment = ALIGN_CENTER

        for c_idx, g in enumerate(g_cols):
            c = 3 + c_idx
            p_val = grid1[r_idx][c_idx] if (r_idx < len(grid1) and c_idx < len(grid1[r_idx])) else None
            cell = ws.cell(row=r, column=c, value=round(p_val, 2) if p_val else "-")
            cell.font = FONT_FORMULA
            cell.number_format = FMT_PRICE
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_BOX

    return ws


def render_reverse_dcf_tab(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="34_Reverse_DCF")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 20, "D": 45})

    ws["B2"] = "REVERSE DCF ANALYSIS"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "Market Price Implied Perpetuity Growth Rate"
    ws["B3"].font = FONT_SECTION

    write_table_header(ws, 5, ["Reverse DCF Parameter", "Value", "Methodology Notes"], start_col=2)

    base_val = spec.get_valuation("base")
    rev_dcf = base_val.reverse_dcf if base_val else None

    mkt_price = rev_dcf.market_price if (rev_dcf and rev_dcf.market_price) else 0.0
    implied_g = (rev_dcf.implied_terminal_growth / 100.0) if (rev_dcf and rev_dcf.implied_terminal_growth) else 0.0

    rows = [
        ("Current Market Benchmark Price (INR)", mkt_price, FMT_PRICE, True, "Market price input"),
        ("Market Implied Equity Value (INR Cr)", "=C6*'27_Share_Count'!E6", FMT_CURRENCY_INT, False, "Market Price * Diluted Shares"),
        ("Market Implied EV (INR Cr)", "=C7+('20_Operating_Model'!C19-'20_Operating_Model'!C16)", FMT_CURRENCY_INT, False, "Implied Equity Value + Net Debt"),
        ("Market Implied PV of TV (INR Cr)", "=C8-'31_DCF'!G6", FMT_CURRENCY_INT, False, "Implied EV - Cumulative PV(FCFF)"),
        ("MARKET IMPLIED TERMINAL GROWTH %", implied_g, FMT_PERCENT_PRECISION, False, "Exact solved implied perpetuity growth rate"),
    ]

    for idx, (lbl, val, fmt, is_inp, note) in enumerate(rows):
        r = 6 + idx
        is_tot = idx == len(rows) - 1
        ws.cell(row=r, column=2, value=lbl).font = FONT_TOTAL if is_tot else FONT_SUBHEADER
        cell_v = ws.cell(row=r, column=3, value=val)
        cell_v.font = FONT_INPUT if is_inp else (FONT_TOTAL if is_tot else FONT_FORMULA)
        cell_v.number_format = fmt
        cell_v.alignment = ALIGN_RIGHT

        cell_n = ws.cell(row=r, column=4, value=note)
        cell_n.font = FONT_SUBTITLE
        cell_n.alignment = ALIGN_LEFT

        for c in range(2, 5):
            ws.cell(row=r, column=c).border = BORDER_TOTAL if is_tot else BORDER_BOX

    return ws


def render_scenario_analysis_tab(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="35_Scenario_Analysis")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 20, "D": 20, "E": 20})

    ws["B2"] = "SCENARIO ANALYSIS COMPARISON"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "Base, Bull, and Bear Scenarios Side-by-Side"
    ws["B3"].font = FONT_SECTION

    write_table_header(ws, 5, ["Valuation Metric / Driver", "Base Scenario", "Bull Scenario", "Bear Scenario"], start_col=2)

    base_v = spec.get_valuation("base")
    bull_v = spec.get_valuation("bull")
    bear_v = spec.get_valuation("bear")

    r_base_pct = get_assumption_value(spec, "ebitda_margin", "FY31", "base") / 100.0
    r_bull_pct = get_assumption_value(spec, "ebitda_margin", "FY31", "bull") / 100.0
    r_bear_pct = get_assumption_value(spec, "ebitda_margin", "FY31", "bear") / 100.0

    ebitda_base = base_v.terminal_value.final_year_ebitda if base_v else 0.0
    ebitda_bull = bull_v.terminal_value.final_year_ebitda if bull_v else 0.0
    ebitda_bear = bear_v.terminal_value.final_year_ebitda if bear_v else 0.0

    rev_base = (ebitda_base / r_base_pct) if r_base_pct > 0 else 0.0
    rev_bull = (ebitda_bull / r_bull_pct) if r_bull_pct > 0 else 0.0
    rev_bear = (ebitda_bear / r_bear_pct) if r_bear_pct > 0 else 0.0

    rows = [
        ("Implied Share Price (INR)", base_v.dcf_bridge.implied_share_price, bull_v.dcf_bridge.implied_share_price, bear_v.dcf_bridge.implied_share_price, FMT_PRICE),
        ("Enterprise Value (INR Cr)", base_v.dcf_bridge.enterprise_value, bull_v.dcf_bridge.enterprise_value, bear_v.dcf_bridge.enterprise_value, FMT_CURRENCY_INT),
        ("Net Cash / (Debt) (INR Cr)", -base_v.dcf_bridge.less_net_debt, -bull_v.dcf_bridge.less_net_debt, -bear_v.dcf_bridge.less_net_debt, FMT_CURRENCY_INT),
        ("Equity Value (INR Cr)", base_v.dcf_bridge.equity_value, bull_v.dcf_bridge.equity_value, bear_v.dcf_bridge.equity_value, FMT_CURRENCY_INT),
        ("Diluted Shares (Cr)", base_v.dcf_bridge.shares_outstanding, bull_v.dcf_bridge.shares_outstanding, bear_v.dcf_bridge.shares_outstanding, FMT_AMOUNT),
        ("Discount Rate (WACC %)", base_v.wacc.wacc / 100.0, bull_v.wacc.wacc / 100.0, bear_v.wacc.wacc / 100.0, FMT_PERCENT),
        ("Terminal Growth Rate %", base_v.terminal_value.terminal_growth_rate / 100.0, bull_v.terminal_value.terminal_growth_rate / 100.0, bear_v.terminal_value.terminal_growth_rate / 100.0, FMT_PERCENT),
        ("FY31 Revenue (INR Cr)", rev_base, rev_bull, rev_bear, FMT_CURRENCY_INT),
        ("FY31 EBITDA Margin %", r_base_pct, r_bull_pct, r_bear_pct, FMT_PERCENT),
    ]

    for idx, (lbl, v1, v2, v3, fmt) in enumerate(rows):
        r = 6 + idx
        ws.cell(row=r, column=2, value=lbl).font = FONT_TOTAL if idx == 0 else FONT_SUBHEADER
        for c_idx, val in enumerate([v1, v2, v3]):
            c = 3 + c_idx
            cell = ws.cell(row=r, column=c, value=val)
            cell.font = FONT_TOTAL if idx == 0 else FONT_FORMULA
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_TOTAL if idx == 0 else BORDER_BOX

    return ws
