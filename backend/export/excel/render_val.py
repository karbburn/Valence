from __future__ import annotations

"""
Valuation Tabs Renderer.

Renders:
- 30_WACC: WACC CAPM cost of equity & capital weighting with live formulas
- 31_DCF: 5-year FCFF, discount factors, PV(FCFF), TV, EV -> Share Price bridge with live formulas
- 32_Terminal_Value: Dual terminal value (Gordon Growth & Exit Multiple)
- 33_Sensitivity: Dynamic 2D sensitivity formula grids (WACC x Growth, WACC x Multiple)
- 34_Reverse_DCF: Market implied perpetuity terminal growth rate with live closed-form formula
- 35_Scenario_Analysis: Base, Bull, Bear outputs side-by-side
"""

from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from backend.export.excel.builder import (
    apply_tab_defaults,
    register_formula_value,
    set_col_widths,
    write_formula_cell,
    write_table_header,
)
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

# Named fallbacks
FALLBACK_WACC = 12.0
FALLBACK_TERMINAL_GROWTH = 4.0
FALLBACK_EXIT_MULTIPLE = 20.0


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
    eq_weight = wacc_b.equity_weight if (wacc_b and wacc_b.equity_weight is not None) else 1.0
    debt_weight = wacc_b.debt_weight if (wacc_b and wacc_b.debt_weight is not None) else 0.0

    rfr_note = f"{spec.metadata.market.upper()} sovereign 10-Year yield"
    beta_note = f"{spec.metadata.ticker} 2Y weekly beta vs primary index"
    erp_note = f"Damodaran {spec.metadata.market.upper()} published Equity Risk Premium"

    if wacc_b and wacc_b.source_notes:
        sn = wacc_b.source_notes
        if "Rfr=" in sn:
            try:
                rfr_part = sn.split("Rfr=")[1].split("),")[0]
                if "(" in rfr_part:
                    rfr_note = rfr_part.split("(")[1].strip()
            except Exception:
                pass
        if "Beta=" in sn:
            try:
                beta_part = sn.split("Beta=")[1].split("),")[0]
                if "(" in beta_part:
                    beta_note = beta_part.split("(")[1].strip()
            except Exception:
                pass
        if "ERP=" in sn:
            try:
                erp_part = sn.split("ERP=")[1].split(").")[0]
                if "(" in erp_part:
                    erp_note = erp_part.split("(")[1].strip()
            except Exception:
                pass

    ke_val = (wacc_b.cost_of_equity / 100.0) if (wacc_b and wacc_b.cost_of_equity) else ((rfr + beta * erp) / 100.0)
    kd_val = (debt_pre / 100.0 * (1.0 - tax / 100.0))
    if wacc_b and wacc_b.wacc is not None and wacc_b.wacc != 0:
        wacc_val = wacc_b.wacc / 100.0
    else:
        wacc_val = FALLBACK_WACC / 100.0

    wacc_rows = [
        ("Risk-Free Rate (Rf) %", rfr / 100.0, None, FMT_PERCENT_PRECISION, True, rfr_note),
        ("Equity Beta (β)", beta, None, "0.00", True, beta_note),
        ("Equity Risk Premium (ERP) %", erp / 100.0, None, FMT_PERCENT_PRECISION, True, erp_note),
        ("Cost of Equity (r_e) %", "=C6+(C7*C8)", ke_val, FMT_PERCENT_PRECISION, False, "CAPM formula: r_e = Rf + Beta * ERP"),
        ("Pre-Tax Cost of Debt %", debt_pre / 100.0, None, FMT_PERCENT_PRECISION, True, f"{spec.metadata.ticker} pre-tax cost of borrowings"),
        ("Effective Tax Rate %", tax / 100.0, None, FMT_PERCENT_PRECISION, True, "Forecast average tax rate"),
        ("After-Tax Cost of Debt (r_d) %", "=C10*(1-C11)", kd_val, FMT_PERCENT_PRECISION, False, "Pre-tax * (1 - tax_rate)"),
        ("Equity Market Weight %", eq_weight, None, FMT_PERCENT, False, "Market Cap / Total Capital"),
        ("Debt Market Weight %", debt_weight, None, FMT_PERCENT, False, "Total Debt / Total Capital"),
        ("WEIGHTED AVERAGE COST OF CAPITAL (WACC) %", "=(C13*C9)+(C14*C12)", wacc_val, FMT_PERCENT_PRECISION, False, "Total WACC = Equity Weight * r_e + Debt Weight * r_d"),
    ]

    for idx, (label, val, c_val, fmt, is_inp, note) in enumerate(wacc_rows):
        r = 6 + idx
        is_tot = idx == len(wacc_rows) - 1
        ws.cell(row=r, column=2, value=label).font = FONT_TOTAL if is_tot else FONT_SUBHEADER
        
        if str(val).startswith("="):
            write_formula_cell(
                ws, r, 3,
                formula=val,
                cached_value=c_val,
                num_format=fmt,
                font=FONT_TOTAL if is_tot else FONT_FORMULA,
                border=BORDER_TOTAL if is_tot else BORDER_BOX,
                alignment=ALIGN_RIGHT,
            )
        else:
            cell_v = ws.cell(row=r, column=3, value=val)
            cell_v.font = FONT_INPUT if is_inp else (FONT_TOTAL if is_tot else FONT_FORMULA)
            cell_v.number_format = fmt
            cell_v.alignment = ALIGN_RIGHT
            cell_v.border = BORDER_TOTAL if is_tot else BORDER_BOX

        cell_n = ws.cell(row=r, column=4, value=note)
        cell_n.font = FONT_SUBTITLE
        cell_n.alignment = ALIGN_LEFT
        ws.cell(row=r, column=2).border = BORDER_TOTAL if is_tot else BORDER_BOX
        ws.cell(row=r, column=4).border = BORDER_TOTAL if is_tot else BORDER_BOX

    return ws


def render_dcf_tab(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="31_DCF")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 36, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18, "H": 22})

    ws["B2"] = f"{spec.metadata.name.upper()} — DISCOUNTED CASH FLOW (DCF) MODEL"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "5-Year FCFF Build, PV Discounting & Enterprise Value Bridge"
    ws["B3"].font = FONT_SECTION

    headers = ["FCFF Line Item / DCF Bridge"] + FORECAST_PERIODS + ["Valuation Summary"]
    write_table_header(ws, 5, headers, start_col=2)

    base_val = spec.get_valuation("base")
    fcffs = base_val.fcff_by_period if base_val else []

    # Row 6: Operating Profit (EBIT)
    ws.cell(row=6, column=2, value="Operating Profit (EBIT)").font = FONT_SUBHEADER
    for idx, col in enumerate(["C", "D", "E", "F", "G"]):
        c = 3 + idx
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = p.ebit if p else None
        write_formula_cell(
            ws, 6, c,
            formula=f"='20_Operating_Model'!{col}11",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 7: Less: Tax Expense
    ws.cell(row=7, column=2, value="Effective Tax Rate %").font = FONT_SUBHEADER
    for idx, col in enumerate(["C", "D", "E", "F", "G"]):
        c = 3 + idx
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = (p.tax_rate / 100.0) if p and p.tax_rate else None
        write_formula_cell(
            ws, 7, c,
            formula=f"='26_Tax_Schedule'!{col}6",
            cached_value=c_val,
            num_format=FMT_PERCENT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 8: NOPAT
    ws.cell(row=8, column=2, value="NOPAT (EBIT x (1 - Tax))").font = FONT_TOTAL
    for idx, p_label in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        col_let = chr(67 + idx)
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = p.nopat if p else None
        write_formula_cell(
            ws, 8, c,
            formula=f"={col_let}6*(1-{col_let}7)",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_TOTAL,
            border=BORDER_TOTAL,
            alignment=ALIGN_RIGHT,
        )

    # Row 9: Plus: D&A
    ws.cell(row=9, column=2, value="Plus: D&A Expense").font = FONT_SUBHEADER
    for idx, col in enumerate(["C", "D", "E", "F", "G"]):
        c = 3 + idx
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = p.da if p else None
        write_formula_cell(
            ws, 9, c,
            formula=f"='20_Operating_Model'!{col}10",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 10: Less: Capex
    ws.cell(row=10, column=2, value="Less: Capex Outflow").font = FONT_SUBHEADER
    for idx, col in enumerate(["C", "D", "E", "F", "G"]):
        c = 3 + idx
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = abs(p.capex) if p and p.capex else None
        write_formula_cell(
            ws, 10, c,
            formula=f"=ABS('20_Operating_Model'!{col}24)",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 11: Less: Change in Working Capital (Clean Delta NWC Formula)
    ws.cell(row=11, column=2, value="Less: Change in Working Capital").font = FONT_SUBHEADER
    for idx, p_label in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        col_let = chr(67 + idx)
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = p.delta_working_capital if p else None

        if idx == 0:
            form = f"=('23_Working_Capital'!C7-'23_Working_Capital'!C9)-('11_Balance_Sheet'!E10-'11_Balance_Sheet'!E17)"
        else:
            prev_col_let = chr(67 + idx - 1)
            form = f"=('23_Working_Capital'!{col_let}7-'23_Working_Capital'!{col_let}9)-('23_Working_Capital'!{prev_col_let}7-'23_Working_Capital'!{prev_col_let}9)"

        write_formula_cell(
            ws, 11, c,
            formula=form,
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 12: Free Cash Flow to Firm (FCFF)
    ws.cell(row=12, column=2, value="FREE CASH FLOW TO FIRM (FCFF)").font = FONT_TOTAL
    for idx, p_label in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        col_let = chr(67 + idx)
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = p.fcff if p else None
        write_formula_cell(
            ws, 12, c,
            formula=f"={col_let}8+{col_let}9-{col_let}10-{col_let}11",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_TOTAL,
            border=BORDER_TOTAL,
            alignment=ALIGN_RIGHT,
        )

    # Row 13: Discount Factor (Mid-Year Convention)
    ws.cell(row=13, column=2, value="Mid-Year Discount Factor (1 / (1+WACC)^(t - 0.5))").font = FONT_SUBHEADER
    for idx, p_label in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        t = idx + 1
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = p.discount_factor if p else None
        write_formula_cell(
            ws, 13, c,
            formula=f"=1/((1+'30_WACC'!C15)^({t}-0.5))",
            cached_value=c_val,
            num_format="0.000000",
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 14: Present Value of FCFF
    ws.cell(row=14, column=2, value="PRESENT VALUE OF FCFF").font = FONT_TOTAL
    for idx, p_label in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        col_let = chr(67 + idx)
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = p.pv_fcff if p else None
        write_formula_cell(
            ws, 14, c,
            formula=f"={col_let}12*{col_let}13",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_TOTAL,
            border=BORDER_TOTAL,
            alignment=ALIGN_RIGHT,
        )

    # DCF Bridge Block (rows 17-28, Column B = labels, Column H = values)
    ws["B16"] = "DCF BRIDGE — EV TO EQUITY VALUE"
    ws["B16"].font = FONT_SECTION

    ccy = spec.metadata.currency
    b_obj = base_val.dcf_bridge if base_val else None

    cash_val = b_obj.cash_and_equivalents if (b_obj and b_obj.cash_and_equivalents is not None) else 0.0
    mkt_sec_val = b_obj.marketable_securities if (b_obj and b_obj.marketable_securities is not None) else 0.0
    non_curr_inv_val = b_obj.non_current_investments if (b_obj and b_obj.non_current_investments is not None) else 0.0
    tot_debt_val = b_obj.total_debt if (b_obj and b_obj.total_debt is not None) else 0.0
    min_int_val = ((b_obj.minority_interest or 0.0) + (b_obj.preferred_stock or 0.0)) if b_obj else 0.0
    net_debt = (b_obj.less_net_debt if b_obj and b_obj.less_net_debt is not None else 0.0)

    unit_lbl = "M" if (spec.metadata.units == "millions" or spec.metadata.market == "us") else "Cr"

    bridge_rows = [
        ("Cumulative PV of FCFF (Mid-Year)", "=SUM(C14:G14)", b_obj.sum_pv_fcff if b_obj else 0, FMT_CURRENCY_INT),
        ("PV of Terminal Value", "='32_Terminal_Value'!C13", b_obj.pv_terminal_value if b_obj else 0, FMT_CURRENCY_INT),
        ("ENTERPRISE VALUE (EV)", "=H17+H18", b_obj.enterprise_value if b_obj else 0, FMT_CURRENCY_INT),
        ("Plus: Cash & Cash Equivalents", cash_val, cash_val, FMT_CURRENCY_INT),
        ("Plus: Marketable Securities", mkt_sec_val, mkt_sec_val, FMT_CURRENCY_INT),
        ("Plus: Non-Current Investments", non_curr_inv_val, non_curr_inv_val, FMT_CURRENCY_INT),
        ("Less: Total Debt", tot_debt_val, tot_debt_val, FMT_CURRENCY_INT),
        ("Less: Minority Interest & Preferred", min_int_val, min_int_val, FMT_CURRENCY_INT),
        ("Net Non-Operating Debt / (Cash)", "=(H23+H24)-(H20+H21+H22)", net_debt, FMT_CURRENCY_INT),
        ("EQUITY VALUE", "=H19-H25", b_obj.equity_value if b_obj else 0, FMT_CURRENCY_INT),
        (f"Diluted Shares ({unit_lbl})", "='27_Share_Count'!E6", b_obj.shares_outstanding if b_obj else 0, FMT_AMOUNT),
        (f"IMPLIED SHARE PRICE ({ccy})", "=H26/H27", b_obj.implied_share_price if b_obj else 0, FMT_PRICE),
    ]

    for idx, (lbl, formula, c_val, fmt) in enumerate(bridge_rows):
        r = 17 + idx
        is_price = idx == len(bridge_rows) - 1
        
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=7)
        cell_lbl = ws.cell(row=r, column=2, value=lbl)
        cell_lbl.font = FONT_TOTAL if is_price else FONT_SUBHEADER
        cell_lbl.alignment = ALIGN_LEFT
        
        for col in range(2, 8):
            ws.cell(row=r, column=col).border = BORDER_TOTAL if is_price else BORDER_BOX

        if str(formula).startswith("="):
            write_formula_cell(
                ws, r, 8,
                formula=formula,
                cached_value=c_val,
                num_format=fmt,
                font=FONT_TITLE if is_price else FONT_TOTAL,
                border=BORDER_TOTAL if is_price else BORDER_BOX,
                alignment=ALIGN_RIGHT,
            )
        else:
            cell = ws.cell(row=r, column=8, value=formula)
            cell.font = FONT_TITLE if is_price else FONT_TOTAL
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_TOTAL if is_price else BORDER_BOX

    return ws


def render_terminal_value_tab(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="32_Terminal_Value")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 38, "C": 20, "D": 45})

    ws["B2"] = "TERMINAL VALUE CALCULATION (DUAL METHOD & QUALITY CHECKS)"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "Gordon Perpetuity Growth, Exit Multiple & Terminal ROIC Analysis"
    ws["B3"].font = FONT_SECTION

    write_table_header(ws, 5, ["Terminal Value Parameter", "Value", "Methodology / Rule Notes"], start_col=2)
    ccy = f"{spec.metadata.currency} {spec.metadata.units.capitalize()[:2]}"
    base_val = spec.get_valuation("base")
    tv = base_val.terminal_value if base_val else None

    reinvest_fmt = FMT_PERCENT if (tv and tv.reinvestment_rate is not None) else "@"
    reinvest_val = (tv.reinvestment_rate / 100.0) if (tv and tv.reinvestment_rate is not None) else "-"
    roic_fmt = FMT_PERCENT if (tv and tv.implied_roic is not None) else "@"
    roic_val = (tv.implied_roic / 100.0) if (tv and tv.implied_roic is not None) else "-"

    tgr = tv.terminal_growth_rate if (tv and tv.terminal_growth_rate is not None) else FALLBACK_TERMINAL_GROWTH
    exit_mult = tv.exit_multiple if (tv and tv.exit_multiple is not None) else FALLBACK_EXIT_MULTIPLE

    tv_rows = [
        ("Terminal Growth Rate %", tgr / 100.0, None, FMT_PERCENT, True, "Perpetuity growth rate (must be < WACC)"),
        (f"FY31 Final Year FCFF ({ccy})", "='31_DCF'!G12", tv.final_year_fcff if tv else 0, FMT_AMOUNT, False, "Final forecast year FCFF"),
        ("Gordon Growth Undiscounted TV", "=(C7*(1+C6)/('30_WACC'!C15-C6))", tv.terminal_value_undiscounted if tv else 0, FMT_CURRENCY_INT, False, "TV = FCFF_n * (1+g) / (WACC - g)"),
        ("Exit Multiple (EV/EBITDA)", exit_mult, None, FMT_MULTIPLE, True, "Exit EV/EBITDA multiple"),
        (f"FY31 Final Year EBITDA ({ccy})", "='20_Operating_Model'!G9", tv.final_year_ebitda if tv else 0, FMT_AMOUNT, False, "Final forecast year EBITDA"),
        ("Exit Multiple Undiscounted TV", "=C9*C10", tv.exit_multiple_tv_undiscounted if tv else 0, FMT_CURRENCY_INT, False, "TV = EBITDA_n * Exit Multiple"),
        ("Discount Factor (t=5)", "=1/((1+'30_WACC'!C15)^5)", tv.discount_factor if tv else 0, "0.000000", False, "Discount factor for Year 5"),
        ("DISCOUNTED TERMINAL VALUE (PV)", "=C8*C12", base_val.dcf_bridge.pv_terminal_value if base_val else 0, FMT_CURRENCY_INT, False, "Gordon Growth PV of Terminal Value"),
        ("Terminal Year NOPAT (Quality Check)", tv.terminal_nopat if (tv and tv.terminal_nopat is not None) else "-", None, FMT_CURRENCY_INT if (tv and tv.terminal_nopat) else "@", False, "Terminal NOPAT = EBIT_5 * (1+g) * (1 - Tax)"),
        ("Implied Reinvestment Rate %", reinvest_val, None, reinvest_fmt, False, "Reinvestment Rate = (Terminal NOPAT - Terminal FCFF) / NOPAT"),
        ("Implied Terminal ROIC %", roic_val, None, roic_fmt, False, "ValueDriver check: g / Reinvestment Rate"),
    ]

    for idx, (lbl, val, c_val, fmt, is_inp, note) in enumerate(tv_rows):
        r = 6 + idx
        is_tot = idx == 7  # DISCOUNTED TERMINAL VALUE (PV)
        ws.cell(row=r, column=2, value=lbl).font = FONT_TOTAL if is_tot else FONT_SUBHEADER
        
        if str(val).startswith("="):
            write_formula_cell(
                ws, r, 3,
                formula=val,
                cached_value=c_val,
                num_format=fmt,
                font=FONT_TOTAL if is_tot else FONT_FORMULA,
                border=BORDER_TOTAL if is_tot else BORDER_BOX,
                alignment=ALIGN_RIGHT,
            )
        else:
            cell_v = ws.cell(row=r, column=3, value=val)
            cell_v.font = FONT_INPUT if is_inp else (FONT_TOTAL if is_tot else FONT_FORMULA)
            cell_v.number_format = fmt
            cell_v.alignment = ALIGN_RIGHT
            cell_v.border = BORDER_TOTAL if is_tot else BORDER_BOX

        cell_n = ws.cell(row=r, column=4, value=note)
        cell_n.font = FONT_SUBTITLE
        cell_n.alignment = ALIGN_LEFT
        ws.cell(row=r, column=2).border = BORDER_TOTAL if is_tot else BORDER_BOX
        ws.cell(row=r, column=4).border = BORDER_TOTAL if is_tot else BORDER_BOX

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

    # Column headers for Grid 1
    for idx, g in enumerate(g_cols):
        col_letter = chr(67 + idx)
        cell_g = ws.cell(row=5, column=3 + idx, value=g)
        cell_g.font = FONT_HEADER
        cell_g.fill = FILL_HEADER
        cell_g.number_format = FMT_PERCENT
        cell_g.alignment = ALIGN_CENTER

    for r_idx, w in enumerate(wacc_rows):
        r = 6 + r_idx
        cell_w = ws.cell(row=r, column=2, value=w)
        cell_w.font = FONT_SUBHEADER
        cell_w.number_format = FMT_PERCENT_PRECISION
        cell_w.border = BORDER_BOX

        for c_idx, g in enumerate(g_cols):
            c = 3 + c_idx
            col_letter = chr(67 + c_idx)
            p_val = grid1[r_idx][c_idx] if (r_idx < len(grid1) and c_idx < len(grid1[r_idx])) else None
            
            # Live Dynamic Formula for Sensitivity Matrix
            formula = f"=((('31_DCF'!H17+('31_DCF'!G12*(1+{col_letter}$5)/($B{r}-{col_letter}$5))/(1+$B{r})^5)-'31_DCF'!H25)/'31_DCF'!H27)"
            write_formula_cell(
                ws, r, c,
                formula=formula,
                cached_value=p_val,
                num_format=FMT_PRICE,
                font=FONT_FORMULA,
                border=BORDER_BOX,
                alignment=ALIGN_RIGHT,
            )

    # Table 2: WACC % \\ Multiple
    ws["B13"] = "WACC % \\ Multiple"
    ws["B13"].font = FONT_HEADER
    ws["B13"].fill = FILL_HEADER

    t2 = sens_tables[1] if len(sens_tables) > 1 else None
    m_cols = t2.col_values if t2 else [15.0, 17.5, 20.0, 22.5, 25.0]
    wacc_rows2 = [w / 100.0 for w in t2.row_values] if t2 else [0.11, 0.12, 0.1295, 0.14, 0.15]
    grid2 = t2.results_grid if t2 else []

    # Column headers for Grid 2
    for idx, m in enumerate(m_cols):
        cell_m = ws.cell(row=13, column=3 + idx, value=m)
        cell_m.font = FONT_HEADER
        cell_m.fill = FILL_HEADER
        cell_m.number_format = FMT_MULTIPLE
        cell_m.alignment = ALIGN_CENTER

    for r_idx, w in enumerate(wacc_rows2):
        r = 14 + r_idx
        cell_w = ws.cell(row=r, column=2, value=w)
        cell_w.font = FONT_SUBHEADER
        cell_w.number_format = FMT_PERCENT_PRECISION
        cell_w.border = BORDER_BOX

        for c_idx, m in enumerate(m_cols):
            c = 3 + c_idx
            col_letter = chr(67 + c_idx)
            p_val = grid2[r_idx][c_idx] if (r_idx < len(grid2) and c_idx < len(grid2[r_idx])) else None
            
            # Live Dynamic Formula for Multiple Matrix
            formula = f"=((('31_DCF'!H17+('20_Operating_Model'!G9*{col_letter}$13)/(1+$B{r})^5)-'31_DCF'!H25)/'31_DCF'!H27)"
            write_formula_cell(
                ws, r, c,
                formula=formula,
                cached_value=p_val,
                num_format=FMT_PRICE,
                font=FONT_FORMULA,
                border=BORDER_BOX,
                alignment=ALIGN_RIGHT,
            )

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
    shares = base_val.dcf_bridge.shares_outstanding if (base_val and base_val.dcf_bridge.shares_outstanding is not None) else 0.0

    ccy = f"{spec.metadata.currency} {spec.metadata.units.capitalize()[:2]}"
    net_debt = (base_val.dcf_bridge.less_net_debt if base_val and base_val.dcf_bridge.less_net_debt is not None else 0.0)

    eq_val_mkt = mkt_price * shares
    ev_mkt = eq_val_mkt + net_debt
    pv_tv_mkt = ev_mkt - (base_val.dcf_bridge.sum_pv_fcff if (base_val and base_val.dcf_bridge.sum_pv_fcff is not None) else 0.0)

    rows = [
        (f"Current Market Benchmark Price ({spec.metadata.currency})", mkt_price, None, FMT_PRICE, True, "Market price input"),
        (f"Market Implied Equity Value ({ccy})", "=C6*'27_Share_Count'!E6", eq_val_mkt, FMT_CURRENCY_INT, False, "Market Price * Diluted Shares"),
        (f"Market Implied EV ({ccy})", f"=C7{net_debt:+.2f}", ev_mkt, FMT_CURRENCY_INT, False, "Implied Equity Value + Net Debt"),
        (f"Market Implied PV of TV ({ccy})", "=C8-'31_DCF'!H17", pv_tv_mkt, FMT_CURRENCY_INT, False, "Implied EV - Cumulative PV(FCFF)"),
        ("MARKET IMPLIED TERMINAL GROWTH %", "=((C9*(1+'30_WACC'!C15)^5*'30_WACC'!C15 - '31_DCF'!G12)/(C9*(1+'30_WACC'!C15)^5 + '31_DCF'!G12))", implied_g, FMT_PERCENT_PRECISION, False, rev_dcf.method_note if rev_dcf and rev_dcf.method_note else "Exact solved implied perpetuity growth rate"),
    ]

    for idx, (lbl, val, c_val, fmt, is_inp, note) in enumerate(rows):
        r = 6 + idx
        is_tot = idx == len(rows) - 1
        ws.cell(row=r, column=2, value=lbl).font = FONT_TOTAL if is_tot else FONT_SUBHEADER
        
        if str(val).startswith("="):
            write_formula_cell(
                ws, r, 3,
                formula=val,
                cached_value=c_val,
                num_format=fmt,
                font=FONT_TOTAL if is_tot else FONT_FORMULA,
                border=BORDER_TOTAL if is_tot else BORDER_BOX,
                alignment=ALIGN_RIGHT,
            )
        else:
            cell_v = ws.cell(row=r, column=3, value=val)
            cell_v.font = FONT_INPUT if is_inp else (FONT_TOTAL if is_tot else FONT_FORMULA)
            cell_v.number_format = fmt
            cell_v.alignment = ALIGN_RIGHT
            cell_v.border = BORDER_TOTAL if is_tot else BORDER_BOX

        cell_n = ws.cell(row=r, column=4, value=note)
        cell_n.font = FONT_SUBTITLE
        cell_n.alignment = ALIGN_LEFT
        ws.cell(row=r, column=2).border = BORDER_TOTAL if is_tot else BORDER_BOX
        ws.cell(row=r, column=4).border = BORDER_TOTAL if is_tot else BORDER_BOX

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

    ebitda_base = (base_v.terminal_value.final_year_ebitda if (base_v and base_v.terminal_value.final_year_ebitda is not None) else 0.0)
    ebitda_bull = (bull_v.terminal_value.final_year_ebitda if (bull_v and bull_v.terminal_value.final_year_ebitda is not None) else 0.0)
    ebitda_bear = (bear_v.terminal_value.final_year_ebitda if (bear_v and bear_v.terminal_value.final_year_ebitda is not None) else 0.0)

    rev_base = (ebitda_base / r_base_pct) if r_base_pct > 0 else 0.0
    rev_bull = (ebitda_bull / r_bull_pct) if r_bull_pct > 0 else 0.0
    rev_bear = (ebitda_bear / r_bear_pct) if r_bear_pct > 0 else 0.0

    ccy = f"{spec.metadata.currency} {spec.metadata.units.capitalize()[:2]}"
    curr = spec.metadata.currency
    rows = [
        (f"Implied Share Price ({curr})", base_v.dcf_bridge.implied_share_price, bull_v.dcf_bridge.implied_share_price, bear_v.dcf_bridge.implied_share_price, FMT_PRICE),
        (f"Enterprise Value ({ccy})", base_v.dcf_bridge.enterprise_value, bull_v.dcf_bridge.enterprise_value, bear_v.dcf_bridge.enterprise_value, FMT_CURRENCY_INT),
        (f"Net Cash / (Debt) ({ccy})", -base_v.dcf_bridge.less_net_debt if base_v.dcf_bridge.less_net_debt is not None else 0, -bull_v.dcf_bridge.less_net_debt if bull_v.dcf_bridge.less_net_debt is not None else 0, -bear_v.dcf_bridge.less_net_debt if bear_v.dcf_bridge.less_net_debt is not None else 0, FMT_CURRENCY_INT),
        (f"Equity Value ({ccy})", base_v.dcf_bridge.equity_value, bull_v.dcf_bridge.equity_value, bear_v.dcf_bridge.equity_value, FMT_CURRENCY_INT),
        ("Diluted Shares", base_v.dcf_bridge.shares_outstanding, bull_v.dcf_bridge.shares_outstanding, bear_v.dcf_bridge.shares_outstanding, FMT_AMOUNT),
        ("Discount Rate (WACC %)", base_v.wacc.wacc / 100.0 if base_v.wacc.wacc is not None else 0, bull_v.wacc.wacc / 100.0 if bull_v.wacc.wacc is not None else 0, bear_v.wacc.wacc / 100.0 if bear_v.wacc.wacc is not None else 0, FMT_PERCENT),
        ("Terminal Growth Rate %", base_v.terminal_value.terminal_growth_rate / 100.0 if base_v.terminal_value.terminal_growth_rate is not None else 0, bull_v.terminal_value.terminal_growth_rate / 100.0 if bull_v.terminal_value.terminal_growth_rate is not None else 0, bear_v.terminal_value.terminal_growth_rate / 100.0 if bear_v.terminal_value.terminal_growth_rate is not None else 0, FMT_PERCENT),
        (f"FY31 Revenue ({ccy})", rev_base, rev_bull, rev_bear, FMT_CURRENCY_INT),
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
