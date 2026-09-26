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
    FONT_ALERT,
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
from backend.export.excel.render_fcst import op_row

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

    # An analyst-set cost of equity must appear as an INPUT, not be hidden behind
    # a live CAPM formula that would recompute a different number than the engine
    # actually discounted at.
    capm_ke = (rfr + beta * erp) / 100.0
    ke_is_override = bool(
        wacc_b and wacc_b.cost_of_equity is not None
        and abs(wacc_b.cost_of_equity - (rfr + beta * erp)) > 0.005
    )
    if wacc_b and wacc_b.cost_of_equity is not None:
        ke_val = wacc_b.cost_of_equity / 100.0
    else:
        ke_val = capm_ke
    kd_val = (debt_pre / 100.0 * (1.0 - tax / 100.0))
    if wacc_b and wacc_b.wacc is not None and wacc_b.wacc != 0:
        wacc_val = wacc_b.wacc / 100.0
    else:
        wacc_val = FALLBACK_WACC / 100.0

    wacc_rows = [
        ("Risk-Free Rate (Rf) %", rfr / 100.0, None, FMT_PERCENT_PRECISION, True, rfr_note),
        ("Equity Beta (β)", beta, None, "0.00", True, beta_note),
        ("Equity Risk Premium (ERP) %", erp / 100.0, None, FMT_PERCENT_PRECISION, True, erp_note),
        (
            "Cost of Equity (r_e) %",
            ke_val if ke_is_override else "=C6+(C7*C8)",
            ke_val,
            FMT_PERCENT_PRECISION,
            ke_is_override,
            "Analyst-set cost of equity (overrides CAPM)"
            if ke_is_override
            else "CAPM formula: r_e = Rf + Beta * ERP",
        ),
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


def _last_historical_column(spec: ModelSpecification) -> str:
    """Column letter on 11_Balance_Sheet holding the last historical period.

    The historical block starts at column C and one column per period, so the
    last period sits at C + n - 1. Hardcoding "E" read the wrong year's
    balances for any company whose history is not exactly three periods, which
    shifts the opening working-capital level and therefore the whole DCF.
    """
    count = len(spec.historicals.periods or [])
    if count <= 0:
        return "C"
    return chr(ord("C") + count - 1)


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
            formula=f"='20_Operating_Model'!{col}{op_row('canonical.is.operating_profit')}",
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
            formula=f"='20_Operating_Model'!{col}{op_row('canonical.is.depreciation_amortization')}",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 10: Less: Capex
    #
    # Sourced from the capex SCHEDULE, not from the operating model's investing
    # line. A hardcoded row index on that tab once landed on operating cash flow
    # after a line was inserted, so recalculating the workbook moved free cash
    # flow by the whole of operating cash flow for every company.
    ws.cell(row=10, column=2, value="Less: Capex Outflow").font = FONT_SUBHEADER
    for idx, col in enumerate(["C", "D", "E", "F", "G"]):
        c = 3 + idx
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = abs(p.capex) if p and p.capex else None
        write_formula_cell(
            ws, 10, c,
            formula=f"=ABS('24_Capex_D&A'!{col}7)",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 11: Less: Change in Working Capital
    #
    # The engine defines the working-capital movement as a balance-sheet level
    # difference: ΔNWC = NWC_t − NWC_{t−1}, where NWC = receivables +
    # inventory − payables. '23_Working_Capital'!row 12 is that single
    # definition, so this row differences ONE consistent quantity in all five
    # columns.
    #
    # The previous version built the level inline as (AR − AP), omitting
    # inventory entirely, AND changed the definition between year 1 (a
    # historical NWC including inventory and unbilled revenue) and years 2-5 (a
    # forecast NWC including neither). Recalculating the workbook therefore
    # produced a different implied share price from the one the model and the
    # Executive Summary published — +27% on NVDA, +57% on AWI.
    ws.cell(row=11, column=2, value="Less: Change in Working Capital").font = FONT_SUBHEADER
    hist_period_col = _last_historical_column(spec)
    for idx, p_label in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        col_let = chr(67 + idx)
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = p.delta_working_capital if p else None

        if idx == 0:
            # Opening level comes from the historical balance sheet: receivables
            # + unbilled revenue + inventory − payables, on the last historical
            # column that actually carries them.
            prior_level = (
                f"(N('11_Balance_Sheet'!{hist_period_col}13)+N('11_Balance_Sheet'!{hist_period_col}14)"
                f"+N('11_Balance_Sheet'!{hist_period_col}15)-N('11_Balance_Sheet'!{hist_period_col}22))"
            )
            form = f"='23_Working_Capital'!{col_let}12-{prior_level}"
        else:
            prev_col_let = chr(67 + idx - 1)
            form = (
                f"='23_Working_Capital'!{col_let}12-'23_Working_Capital'!{prev_col_let}12"
            )

        write_formula_cell(
            ws, 11, c,
            formula=form,
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 12: Free Cash Flow to Firm (FCFF) — memo SBC deduction lives on row 15 below
    ws.cell(row=12, column=2, value="FREE CASH FLOW TO FIRM (FCFF)").font = FONT_TOTAL
    for idx, p_label in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        col_let = chr(67 + idx)
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = p.fcff if p else None
        write_formula_cell(
            ws, 12, c,
            formula=f"={col_let}8+{col_let}9-{col_let}10-{col_let}11-{col_let}15",
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

    # Row 15: Less: Stock-Based Compensation (memo deduction feeding the FCFF row above)
    ws.cell(row=15, column=2, value="Less: Stock-Based Comp (Memo)").font = FONT_SUBHEADER
    for idx, p_label in enumerate(FORECAST_PERIODS):
        c = 3 + idx
        p = fcffs[idx] if idx < len(fcffs) else None
        c_val = (p.stock_compensation or 0.0) if p else 0.0
        cell_sbc = ws.cell(row=15, column=c, value=c_val)
        cell_sbc.font = FONT_FORMULA
        cell_sbc.number_format = FMT_AMOUNT
        cell_sbc.alignment = ALIGN_RIGHT
        cell_sbc.border = BORDER_BOX

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
        (f"FY31 Final Year EBITDA ({ccy})", f"='20_Operating_Model'!G{op_row('canonical.is.ebitda')}", tv.final_year_ebitda if tv else 0, FMT_AMOUNT, False, "Final forecast year EBITDA"),
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

            # Live dynamic formula: re-discount the explicit FCFF stream AND the Gordon
            # terminal value at the trial WACC in column B, then complete the bridge.
            pv_stream = (
                "'31_DCF'!C12/(1+$B{r})^0.5+'31_DCF'!D12/(1+$B{r})^1.5"
                "+'31_DCF'!E12/(1+$B{r})^2.5+'31_DCF'!F12/(1+$B{r})^3.5"
                "+'31_DCF'!G12/(1+$B{r})^4.5"
            ).format(r=r)
            tv_term = f"('31_DCF'!G12*(1+{col_letter}$5)/($B{r}-{col_letter}$5))"
            core = f"(({pv_stream}+{tv_term}/(1+$B{r})^5)-'31_DCF'!H25)/'31_DCF'!H27"
            formula = f'=IF({col_letter}$5>=$B{r},"",{core})'
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

            # Live dynamic formula: trial-WACC PV of the explicit FCFF stream plus an
            # exit-multiple terminal value on FY31 EBITDA, completed through the bridge.
            pv_stream = (
                "'31_DCF'!C12/(1+$B{r})^0.5+'31_DCF'!D12/(1+$B{r})^1.5"
                "+'31_DCF'!E12/(1+$B{r})^2.5+'31_DCF'!F12/(1+$B{r})^3.5"
                "+'31_DCF'!G12/(1+$B{r})^4.5"
            ).format(r=r)
            tv_term = f"('20_Operating_Model'!G{op_row('canonical.is.ebitda')}*{col_letter}$13)"
            formula = f"=(({pv_stream}+{tv_term}/(1+$B{r})^5)-'31_DCF'!H25)/'31_DCF'!H27"
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
        # Live link to the DCF bridge's own net-debt cell, so the reverse DCF
        # responds to a bridge edit instead of carrying a frozen literal that
        # can silently drift from 31_DCF!H25.
        (f"Market Implied EV ({ccy})", "=C7-'31_DCF'!H25", ev_mkt, FMT_CURRENCY_INT, False, "Implied Equity Value − net debt (from 31_DCF!H25)"),
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

    # Quote provenance row — an exported model must never carry a market price
    # whose trading date and provider are invisible, which is how a stale
    # benchmark silently reads as a live quote. Flagged in red when stale.
    prov_row = 6 + len(rows)
    if rev_dcf is not None:
        prov_date = rev_dcf.market_price_date or "unknown"
        prov_src = rev_dcf.market_price_source or "unknown"
        is_stale = prov_src.startswith("stale_cache") or prov_src == "market_default"

        ws.cell(row=prov_row, column=2, value="Quote as of / source").font = FONT_SUBTITLE
        ws.cell(row=prov_row, column=2).alignment = ALIGN_LEFT
        ws.cell(row=prov_row, column=2).border = BORDER_BOX

        prov_cell = ws.cell(
            row=prov_row, column=3,
            value=f"{prov_date} · {prov_src}" + ("  [STALE — re-run for a live quote]" if is_stale else ""),
        )
        prov_cell.font = FONT_ALERT if is_stale else FONT_SUBTITLE
        prov_cell.alignment = ALIGN_RIGHT
        prov_cell.border = BORDER_BOX

        prov_note = ws.cell(
            row=prov_row, column=4,
            value="Trading date of the market quote and the free data provider it came from",
        )
        prov_note.font = FONT_SUBTITLE
        prov_note.alignment = ALIGN_LEFT
        prov_note.border = BORDER_BOX

    # The balance sheet the net debt figure came from. An enterprise value is
    # only interpretable alongside both its price date and its balance-sheet
    # date: the same company at the same price carries a different enterprise
    # value depending on whether the balance sheet is three months old or two
    # years old, and nothing else on the page reveals which.
    bridge = base_val.dcf_bridge if base_val else None
    if bridge is not None and bridge.less_net_debt is not None:
        bs_row = prov_row + 1
        ws.cell(row=bs_row, column=2, value="Balance sheet as of").font = FONT_SUBTITLE
        ws.cell(row=bs_row, column=2).alignment = ALIGN_LEFT
        ws.cell(row=bs_row, column=2).border = BORDER_BOX

        bs_cell = ws.cell(
            row=bs_row,
            column=3,
            value=f"{bridge.balance_sheet_as_of or 'unknown'} · {bridge.balance_sheet_source or 'unknown'}",
        )
        bs_cell.font = FONT_SUBTITLE
        bs_cell.alignment = ALIGN_RIGHT
        bs_cell.border = BORDER_BOX

        basis_row = bs_row + 1
        ws.cell(row=basis_row, column=2, value="Net cash basis").font = FONT_SUBTITLE
        ws.cell(row=basis_row, column=2).alignment = ALIGN_LEFT
        ws.cell(row=basis_row, column=2).border = BORDER_BOX

        basis_cell = ws.cell(
            row=basis_row, column=3, value=bridge.debt_basis_note or ""
        )
        basis_cell.font = FONT_SUBTITLE
        basis_cell.alignment = ALIGN_LEFT
        basis_cell.border = BORDER_BOX

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

    # The BASE column is written as live formulas into the DCF/WACC/terminal
    # chain. It was previously all literals, which made 02_Executive_Summary's
    # "live" price cell a pointer to a dead end: editing the DCF moved nothing
    # on the summary page, and a real error inside 31_DCF stayed invisible
    # because nothing downstream ever recomputed.
    #
    # Bull and bear remain literals — the workbook renders one DCF chain, and
    # the alternative scenarios are engine outputs, not separate models.
    base_formulas = {
        0: "='31_DCF'!H28",
        1: "='31_DCF'!H19",
        2: "='31_DCF'!H25*(-1)",
        3: "='31_DCF'!H26",
        4: "='27_Share_Count'!E6",
        5: "='30_WACC'!C15",
        6: "='32_Terminal_Value'!C6",
        7: f"='20_Operating_Model'!G{op_row('canonical.is.revenue')}",
        8: "='22_Cost_Build'!G6",
    }
    rows = [
        (f"Implied Share Price ({curr}) — base is live from 31_DCF", base_v.dcf_bridge.implied_share_price, bull_v.dcf_bridge.implied_share_price, bear_v.dcf_bridge.implied_share_price, FMT_PRICE),
        (f"Enterprise Value ({ccy})", base_v.dcf_bridge.enterprise_value, bull_v.dcf_bridge.enterprise_value, bear_v.dcf_bridge.enterprise_value, FMT_CURRENCY_INT),
        (f"Net Cash / (Debt) ({ccy})", -base_v.dcf_bridge.less_net_debt if base_v.dcf_bridge.less_net_debt is not None else 0, -bull_v.dcf_bridge.less_net_debt if bull_v.dcf_bridge.less_net_debt is not None else 0, -bear_v.dcf_bridge.less_net_debt if bear_v.dcf_bridge.less_net_debt is not None else 0, FMT_CURRENCY_INT),
        (f"Equity Value ({ccy})", base_v.dcf_bridge.equity_value, bull_v.dcf_bridge.equity_value, bear_v.dcf_bridge.equity_value, FMT_CURRENCY_INT),
        ("Diluted Shares", base_v.dcf_bridge.shares_outstanding, bull_v.dcf_bridge.shares_outstanding, bear_v.dcf_bridge.shares_outstanding, FMT_AMOUNT),
        ("Discount Rate (WACC %)", base_v.wacc.wacc / 100.0 if base_v.wacc.wacc is not None else 0, bull_v.wacc.wacc / 100.0 if bull_v.wacc.wacc is not None else 0, bear_v.wacc.wacc / 100.0 if bear_v.wacc.wacc is not None else 0, FMT_PERCENT),
        ("Terminal Growth Rate %", base_v.terminal_value.terminal_growth_rate / 100.0 if base_v.terminal_value.terminal_growth_rate is not None else 0, bull_v.terminal_value.terminal_growth_rate / 100.0 if bull_v.terminal_value.terminal_growth_rate is not None else 0, bear_v.terminal_value.terminal_growth_rate / 100.0 if bear_v.terminal_value.terminal_growth_rate is not None else 0, FMT_PERCENT),
        (f"FY31 Revenue ({ccy})", rev_base, rev_bull, rev_bear, FMT_CURRENCY_INT),
        ("FY31 EBITDA Margin % (derived)", r_base_pct, r_bull_pct, r_bear_pct, FMT_PERCENT),
    ]

    for idx, (lbl, v1, v2, v3, fmt) in enumerate(rows):
        r = 6 + idx
        ws.cell(row=r, column=2, value=lbl).font = FONT_TOTAL if idx == 0 else FONT_SUBHEADER
        write_formula_cell(
            ws, r, 3,
            formula=base_formulas.get(idx),
            cached_value=v1,
            num_format=fmt,
            font=FONT_TOTAL if idx == 0 else FONT_FORMULA,
            border=BORDER_TOTAL if idx == 0 else BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )
        for c_idx, val in ((4, v2), (5, v3)):
            cell = ws.cell(row=r, column=c_idx, value=val)
            cell.font = FONT_TOTAL if idx == 0 else FONT_FORMULA
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_TOTAL if idx == 0 else BORDER_BOX

    return ws


def render_trading_comps(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    """Tab 40_Trading_Comps: Public Peer Comparables Benchmarking & Multiple Valuation."""
    ws = wb.create_sheet(title="40_Trading_Comps")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 28, "C": 18, "D": 14, "E": 14, "F": 14, "G": 14, "H": 14, "I": 14})

    ws["B2"] = f"{spec.metadata.name.upper()} — PUBLIC TRADING COMPARABLES"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "Industry Peer Group Multiples, Statistical Benchmarks & Implied Target Valuation"
    ws["B3"].font = FONT_SECTION

    from backend.valuation.comps import compute_trading_comps
    base_val = spec.get_valuation("base")
    dcf_b = base_val.dcf_bridge if base_val else None

    target_rev = spec.forecast.get_value("canonical.is.revenue", "FY27", "base") or 1000.0
    target_ebitda = spec.forecast.get_value("canonical.is.ebitda", "FY27", "base") or 300.0
    target_np = spec.forecast.get_value("canonical.is.net_profit", "FY27", "base") or 150.0
    net_debt = dcf_b.less_net_debt if dcf_b and dcf_b.less_net_debt is not None else 0.0
    shares = dcf_b.shares_outstanding if dcf_b and dcf_b.shares_outstanding is not None else 100.0

    comps = compute_trading_comps(
        target_ticker=spec.metadata.ticker,
        target_sector=spec.metadata.sector or "Technology",
        target_revenue_fy27=target_rev,
        target_ebitda_fy27=target_ebitda,
        target_net_profit_fy27=target_np,
        net_debt=net_debt,
        shares_outstanding=shares,
    )

    # 1. Peer Table Header
    headers = ["Peer Company", "Ticker", "Market", "EV / Rev", "EV / EBITDA", "P / E", "FCF Yield %", "ROIC %"]
    write_table_header(ws, 5, headers, start_col=2)

    for idx, p in enumerate(comps.peers):
        r = 6 + idx
        ws.cell(row=r, column=2, value=p.company_name).font = FONT_FORMULA
        ws.cell(row=r, column=3, value=p.ticker).font = FONT_FORMULA
        ws.cell(row=r, column=4, value=p.market).font = FONT_FORMULA

        ws.cell(row=r, column=5, value=p.ev_revenue).number_format = "0.0\"x\""
        ws.cell(row=r, column=6, value=p.ev_ebitda).number_format = "0.0\"x\""
        ws.cell(row=r, column=7, value=p.pe_ratio).number_format = "0.0\"x\""
        ws.cell(row=r, column=8, value=p.fcf_yield_pct / 100.0).number_format = FMT_PERCENT
        ws.cell(row=r, column=9, value=p.roic_pct / 100.0).number_format = FMT_PERCENT

        for col_i in range(2, 10):
            ws.cell(row=r, column=col_i).border = BORDER_BOX
            if col_i >= 5:
                ws.cell(row=r, column=col_i).alignment = ALIGN_RIGHT
                ws.cell(row=r, column=col_i).font = FONT_FORMULA

    # 2. Benchmark Summary Statistics
    bench_r = 6 + len(comps.peers) + 1
    write_table_header(ws, bench_r, ["Statistic / Benchmark", "", "", "EV / Rev", "EV / EBITDA", "P / E", "FCF Yield %", "ROIC %"], start_col=2)

    stat_names = [("25th Percentile", "p25"), ("Median", "median"), ("Mean / Average", "mean"), ("75th Percentile", "p75")]
    for s_idx, (s_lbl, s_attr) in enumerate(stat_names):
        r = bench_r + 1 + s_idx
        ws.cell(row=r, column=2, value=s_lbl).font = FONT_TOTAL if "Median" in s_lbl else FONT_SUBHEADER
        ws.cell(row=r, column=5, value=getattr(comps.benchmarks["ev_revenue"], s_attr)).number_format = "0.0\"x\""
        ws.cell(row=r, column=6, value=getattr(comps.benchmarks["ev_ebitda"], s_attr)).number_format = "0.0\"x\""
        ws.cell(row=r, column=7, value=getattr(comps.benchmarks["pe_ratio"], s_attr)).number_format = "0.0\"x\""
        ws.cell(row=r, column=8, value=getattr(comps.benchmarks["fcf_yield"], s_attr) / 100.0).number_format = FMT_PERCENT
        ws.cell(row=r, column=9, value=getattr(comps.benchmarks["roic"], s_attr) / 100.0).number_format = FMT_PERCENT

        for col_i in range(2, 10):
            ws.cell(row=r, column=col_i).border = BORDER_TOTAL if "Median" in s_lbl else BORDER_BOX
            if col_i >= 5:
                ws.cell(row=r, column=col_i).alignment = ALIGN_RIGHT
                ws.cell(row=r, column=col_i).font = FONT_TOTAL if "Median" in s_lbl else FONT_FORMULA

    # 3. Implied Target Valuation Bridge
    val_r = bench_r + len(stat_names) + 2
    ws.cell(row=val_r, column=2, value="IMPLIED PEER VALUATION BRIDGE").font = FONT_SUBHEADER
    write_table_header(ws, val_r + 1, ["Methodology", "Benchmark Multiple", "Target FY27 Metric", "Implied EV", "Net Debt", "Implied Equity Value", "Implied Share Price"], start_col=2)

    curr = spec.metadata.currency
    for v_idx, v in enumerate(comps.implied_valuations):
        r = val_r + 2 + v_idx
        ws.cell(row=r, column=2, value=v.methodology).font = FONT_FORMULA
        ws.cell(row=r, column=3, value=v.benchmark_multiple).number_format = "0.0\"x\""
        ws.cell(row=r, column=4, value=v.target_metric_value).number_format = FMT_CURRENCY_INT
        ws.cell(row=r, column=5, value=v.implied_ev).number_format = FMT_CURRENCY_INT
        ws.cell(row=r, column=6, value=v.net_debt).number_format = FMT_CURRENCY_INT
        ws.cell(row=r, column=7, value=v.implied_equity_value).number_format = FMT_CURRENCY_INT
        ws.cell(row=r, column=8, value=v.implied_share_price).number_format = FMT_PRICE

        for col_i in range(2, 9):
            ws.cell(row=r, column=col_i).border = BORDER_BOX
            if col_i >= 3:
                ws.cell(row=r, column=col_i).alignment = ALIGN_RIGHT
                ws.cell(row=r, column=col_i).font = FONT_TOTAL if col_i == 8 else FONT_FORMULA

    return ws


def render_valuation_comparison(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    """Tab 41_Valuation_Comparison: Institutional Valuation Football Field & Range Chart."""
    ws = wb.create_sheet(title="41_Valuation_Comparison")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 38, "C": 18, "D": 16, "E": 16, "F": 16, "G": 16, "H": 30})

    ws["B2"] = f"{spec.metadata.name.upper()} — VALUATION FOOTBALL FIELD"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "Cross-Methodology Valuation Ranges (Intrinsic DCF vs Relative Comps vs Market)"
    ws["B3"].font = FONT_SECTION

    from backend.valuation.football_field import compute_football_field
    base_val = spec.get_valuation("base")
    bull_val = spec.get_valuation("bull")
    bear_val = spec.get_valuation("bear")
    rev_dcf = base_val.reverse_dcf if base_val else None

    mkt_price = (
        (rev_dcf.market_price if rev_dcf and rev_dcf.market_price else None)
        or (base_val.dcf_bridge.implied_share_price if base_val else 100.0)
    )
    dcf_base = base_val.dcf_bridge.implied_share_price if base_val else mkt_price
    dcf_bull = bull_val.dcf_bridge.implied_share_price if bull_val else dcf_base * 1.25
    dcf_bear = bear_val.dcf_bridge.implied_share_price if bear_val else dcf_base * 0.75

    from backend.valuation.comps import compute_trading_comps
    dcf_b = base_val.dcf_bridge if base_val else None
    target_rev = spec.forecast.get_value("canonical.is.revenue", "FY27", "base") or 1000.0
    target_ebitda = spec.forecast.get_value("canonical.is.ebitda", "FY27", "base") or 300.0
    target_np = spec.forecast.get_value("canonical.is.net_profit", "FY27", "base") or 150.0
    net_debt = dcf_b.less_net_debt if dcf_b and dcf_b.less_net_debt is not None else 0.0
    shares = dcf_b.shares_outstanding if dcf_b and dcf_b.shares_outstanding is not None else 100.0

    comps_res = compute_trading_comps(
        target_ticker=spec.metadata.ticker,
        target_sector=spec.metadata.sector or "Technology",
        target_revenue_fy27=target_rev,
        target_ebitda_fy27=target_ebitda,
        target_net_profit_fy27=target_np,
        net_debt=net_debt,
        shares_outstanding=shares,
    )

    comps_ev = comps_res.implied_valuations[0].implied_share_price
    comps_pe = comps_res.implied_valuations[1].implied_share_price
    q = getattr(comps_res, "quartile_implied_prices", {}) or {
        "pe_ratio": {"p25": None, "p75": None},
        "ev_ebitda": {"p25": None, "p75": None},
    }

    ff = compute_football_field(
        ticker=spec.metadata.ticker,
        currency=spec.metadata.currency,
        current_price=mkt_price,
        dcf_base_price=dcf_base,
        dcf_bull_price=dcf_bull,
        dcf_bear_price=dcf_bear,
        comps_pe_price=comps_pe,
        comps_ev_ebitda_price=comps_ev,
        base_valuation_output=base_val,
        comps_pe_low=q["pe_ratio"]["p25"],
        comps_pe_high=q["pe_ratio"]["p75"],
        comps_ev_ebitda_low=q["ev_ebitda"]["p25"],
        comps_ev_ebitda_high=q["ev_ebitda"]["p75"],
    )

    headers = ["Valuation Methodology", "Category", "Low Implied Price", "Mid / Base Price", "High Implied Price", "Range Spread", "Methodology Notes"]
    write_table_header(ws, 5, headers, start_col=2)

    for idx, bar in enumerate(ff.valuation_bars):
        r = 6 + idx
        ws.cell(row=r, column=2, value=bar.methodology).font = FONT_TOTAL if "DCF Perpetuity" in bar.methodology else FONT_SUBHEADER
        ws.cell(row=r, column=3, value=bar.category).font = FONT_FORMULA
        ws.cell(row=r, column=4, value=bar.low_value).number_format = FMT_PRICE
        ws.cell(row=r, column=5, value=bar.mid_value).number_format = FMT_PRICE
        ws.cell(row=r, column=6, value=bar.high_value).number_format = FMT_PRICE
        ws.cell(row=r, column=7, value=bar.spread).number_format = FMT_PRICE
        ws.cell(row=r, column=8, value=bar.notes).font = FONT_SUBTITLE

        for col_i in range(2, 9):
            ws.cell(row=r, column=col_i).border = BORDER_BOX
            if col_i in (4, 5, 6, 7):
                ws.cell(row=r, column=col_i).alignment = ALIGN_RIGHT
                ws.cell(row=r, column=col_i).font = FONT_TOTAL if col_i == 5 else FONT_FORMULA

    # Summary Statistics Block
    sum_r = 6 + len(ff.valuation_bars) + 2
    ws.cell(row=sum_r, column=2, value="VALUATION SYNTHESIS & BENCHMARKS").font = FONT_SUBHEADER
    ws.cell(row=sum_r + 1, column=2, value=f"Current Market Share Price ({spec.metadata.currency})").font = FONT_TOTAL
    ws.cell(row=sum_r + 1, column=3, value=ff.current_market_price).number_format = FMT_PRICE
    ws.cell(row=sum_r + 1, column=3).font = FONT_TOTAL

    ws.cell(row=sum_r + 2, column=2, value=f"Mean Fair Value Across Methodologies ({spec.metadata.currency})").font = FONT_TOTAL
    ws.cell(row=sum_r + 2, column=3, value=ff.mean_fair_value).number_format = FMT_PRICE
    ws.cell(row=sum_r + 2, column=3).font = FONT_TOTAL

    return ws


def render_investment_returns(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    """Tab 42_Investment_Returns: Private Equity Exit Returns, MoIC & IRR Waterfall."""
    ws = wb.create_sheet(title="42_Investment_Returns")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 32, "C": 14, "D": 16, "E": 14, "F": 16, "G": 16, "H": 14, "I": 14})

    ws["B2"] = f"{spec.metadata.name.upper()} — INVESTMENT RETURNS & PE EXIT ANALYSIS"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "3-Year & 5-Year Exit Enterprise Value, Equity IRR % and MoIC Multiple on Invested Capital"
    ws["B3"].font = FONT_SECTION

    from backend.valuation.returns import compute_investment_returns
    base_val = spec.get_valuation("base")
    dcf_b = base_val.dcf_bridge if base_val else None
    rev_dcf = base_val.reverse_dcf if base_val else None

    entry_p = (
        (rev_dcf.market_price if rev_dcf and rev_dcf.market_price else None)
        or (dcf_b.implied_share_price if dcf_b else 100.0)
    )
    sh = dcf_b.shares_outstanding if dcf_b and dcf_b.shares_outstanding is not None else 100.0

    ebitda_fy29 = spec.forecast.get_value("canonical.is.ebitda", "FY29", "base") or 500.0
    ebitda_fy31 = spec.forecast.get_value("canonical.is.ebitda", "FY31", "base") or 700.0
    net_debt = dcf_b.less_net_debt if dcf_b and dcf_b.less_net_debt is not None else 0.0

    returns = compute_investment_returns(
        entry_price=entry_p,
        shares_outstanding=sh,
        ebitda_fy29=ebitda_fy29,
        ebitda_fy31=ebitda_fy31,
        net_debt_fy29=net_debt * 0.90,
        net_debt_fy31=net_debt * 0.75,
        base_exit_multiple=18.0,
    )

    # 1. Exit Scenarios Table
    headers = ["Exit Scenario", "Exit Year", "Exit EBITDA", "Exit Multiple", "Exit EV", "Exit Equity Value", "MoIC Multiple", "Equity IRR %"]
    write_table_header(ws, 5, headers, start_col=2)

    for idx, sc in enumerate(returns.exit_scenarios):
        r = 6 + idx
        ws.cell(row=r, column=2, value=sc.scenario).font = FONT_TOTAL if "Base Case" in sc.scenario else FONT_SUBHEADER
        ws.cell(row=r, column=3, value=sc.exit_year).font = FONT_FORMULA
        ws.cell(row=r, column=4, value=sc.exit_ebitda).number_format = FMT_CURRENCY_INT
        ws.cell(row=r, column=5, value=sc.exit_multiple).number_format = "0.0\"x\""
        ws.cell(row=r, column=6, value=sc.exit_ev).number_format = FMT_CURRENCY_INT
        ws.cell(row=r, column=7, value=sc.exit_equity_value).number_format = FMT_CURRENCY_INT
        ws.cell(row=r, column=8, value=sc.moic).number_format = "0.00\"x\""
        ws.cell(row=r, column=9, value=sc.equity_irr_pct / 100.0).number_format = FMT_PERCENT

        for col_i in range(2, 10):
            ws.cell(row=r, column=col_i).border = BORDER_TOTAL if "Base Case" in sc.scenario else BORDER_BOX
            if col_i >= 4:
                ws.cell(row=r, column=col_i).alignment = ALIGN_RIGHT
                ws.cell(row=r, column=col_i).font = FONT_TOTAL if col_i in (8, 9) else FONT_FORMULA

    # 2. 2D Returns Matrix (Entry Share Price vs Exit Multiple)
    mat_r = 6 + len(returns.exit_scenarios) + 2
    ws.cell(row=mat_r, column=2, value="5-YEAR 2D RETURNS SENSITIVITY MATRIX (EQUITY IRR %)").font = FONT_SUBHEADER
    ws.cell(row=mat_r + 1, column=2, value="Entry Share Price").font = FONT_SECTION

    # Matrix Headers: Exit Multiples
    mult_headers = ["Entry Price"] + [f"Exit {cell.exit_multiple:.1f}x" for cell in returns.returns_matrix[0]]
    write_table_header(ws, mat_r + 2, mult_headers, start_col=2)

    for row_i, row_data in enumerate(returns.returns_matrix):
        r = mat_r + 3 + row_i
        ws.cell(row=r, column=2, value=row_data[0].entry_price).number_format = FMT_PRICE
        ws.cell(row=r, column=2).font = FONT_INPUT
        ws.cell(row=r, column=2).alignment = ALIGN_RIGHT
        ws.cell(row=r, column=2).border = BORDER_BOX

        for col_i, cell_data in enumerate(row_data):
            c = 3 + col_i
            cell_v = ws.cell(row=r, column=c, value=cell_data.irr_pct / 100.0)
            cell_v.number_format = FMT_PERCENT
            cell_v.font = FONT_TOTAL if (row_i == 2 and col_i == 2) else FONT_FORMULA
            cell_v.alignment = ALIGN_RIGHT
            cell_v.border = BORDER_TOTAL if (row_i == 2 and col_i == 2) else BORDER_BOX

    return ws

