from __future__ import annotations

"""
Forecast & Supporting Schedules Tabs Renderer.

Renders:
- 20_Operating_Model: Combined 3-statement forecast model (FY27-FY31) with live formulas
- 21_Revenue_Build: Segment revenue forecast & growth (forward driver)
- 22_Cost_Build: Cost structure & EBITDA forecast
- 23_Working_Capital: Receivables & payables forecast (DSO/DPO)
- 24_Capex_D&A: Capex % revenue & D&A schedule
- 25_Debt_Schedule: Generic debt schedule with live interest and closing debt formulas
- 26_Tax_Schedule: Effective tax rate forecast
- 27_Share_Count: Diluted share count schedule
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


OPERATING_MODEL_ROW_OFFSET = 6

# Row index of every line on 20_Operating_Model, keyed by canonical key.
#
# These row numbers used to be hardcoded as literals inside the formulas on
# 31_DCF and 52_Model_Checks. Inserting one line into the operating model
# therefore silently re-pointed every self-referencing formula at whatever moved
# into the vacated row: "Less: Capex Outflow" began reading operating cash flow,
# and the balance-sheet check began reading the cash line. A reader pressing
# recalculate then got a different free cash flow from the one the model
# published, with nothing on the page to explain it.
#
# Publishing the map means a formula names the LINE it wants, and adding or
# removing a line can no longer break an unrelated one.
OPERATING_MODEL_ROWS: dict[str, int] = {
    key: OPERATING_MODEL_ROW_OFFSET + index
    for index, (key, *_rest) in enumerate(
        [
            ("canonical.is.revenue",),
            ("canonical.is.cost_of_sales",),
            ("canonical.is.gross_profit",),
            ("canonical.is.ebitda",),
            ("canonical.is.depreciation_amortization",),
            ("canonical.is.operating_profit",),
            ("canonical.is.other_income",),
            ("canonical.is.finance_cost",),
            ("canonical.is.pbt",),
            ("canonical.is.tax",),
            ("canonical.is.net_profit",),
            ("canonical.bs.trade_receivables",),
            ("canonical.bs.inventory",),
            ("canonical.bs.trade_payables",),
            ("canonical.bs.cash_and_bank",),
            ("canonical.bs.total_assets",),
            ("canonical.bs.total_equity",),
            ("canonical.bs.total_liabilities",),
            ("canonical.bs.total_liabilities_and_equity",),
            ("canonical.cf.operating_activities",),
            ("canonical.cf.investing_activities",),
            ("canonical.cf.dividends_paid",),
            ("canonical.cf.financing_activities",),
        ]
    )
}


def op_row(canonical_key: str) -> int:
    """Row on 20_Operating_Model holding a canonical key.

    Raises rather than guessing if the key is not on the tab: a silent fallback
    to a neighbouring row is how a formula ends up reading a different
    quantity from the one its label promises.
    """
    try:
        return OPERATING_MODEL_ROWS[canonical_key]
    except KeyError as exc:  # pragma: no cover - programming error
        raise KeyError(
            f"{canonical_key} is not a line on 20_Operating_Model; add it to "
            "OPERATING_MODEL_ROWS and to the tab's line list together"
        ) from exc


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
        ("canonical.is.revenue", "Revenue from Operations", True, FMT_AMOUNT, "='21_Revenue_Build'!{col}7"),
        ("canonical.is.cost_of_sales", "Cost of Sales", False, FMT_AMOUNT, f"={{col}}{op_row('canonical.is.revenue')}-{{col}}{op_row('canonical.is.gross_profit')}"),
        ("canonical.is.gross_profit", "Gross Profit", True, FMT_AMOUNT, None),
        ("canonical.is.ebitda", "EBITDA", True, FMT_AMOUNT, "='22_Cost_Build'!{col}7"),
        ("canonical.is.depreciation_amortization", "Depreciation & Amortization", False, FMT_AMOUNT, "='24_Capex_D&A'!{col}9"),
        ("canonical.is.operating_profit", "Operating Profit (EBIT)", True, FMT_AMOUNT, "='22_Cost_Build'!{col}9"),
        ("canonical.is.other_income", "Other Income", False, FMT_AMOUNT, None),
        # Finance cost is a LITERAL, not a link to the debt schedule. The engine
        # holds it flat at the last historical actual, while
        # 25_Debt_Schedule!row 11 recomputes AVERAGE(opening, closing) x Kd. The
        # two disagree for every company (Infosys 416 vs 688; NVDA 0 vs 560), so
        # the live formula silently rewrote PBT, tax and net profit on
        # recalculation. A literal that matches the model is honest.
        ("canonical.is.finance_cost", "Finance Cost (held flat at last actual)", False, FMT_AMOUNT, None),
        ("canonical.is.pbt", "Profit Before Tax (PBT)", True, FMT_AMOUNT, f"={{col}}{op_row('canonical.is.operating_profit')}+{{col}}{op_row('canonical.is.other_income')}-{{col}}{op_row('canonical.is.finance_cost')}"),
        ("canonical.is.tax", "Tax Expense", False, FMT_AMOUNT, f"={{col}}{op_row('canonical.is.pbt')}*'26_Tax_Schedule'!{{col}}6"),
        ("canonical.is.net_profit", "Net Profit After Tax", True, FMT_AMOUNT, f"={{col}}{op_row('canonical.is.pbt')}-{{col}}{op_row('canonical.is.tax')}"),
        ("canonical.bs.trade_receivables", "Trade Receivables", False, FMT_AMOUNT, "='23_Working_Capital'!{col}7"),
        ("canonical.bs.inventory", "Inventory", False, FMT_AMOUNT, "='23_Working_Capital'!{col}11"),
        ("canonical.bs.trade_payables", "Trade Payables", False, FMT_AMOUNT, "='23_Working_Capital'!{col}9"),
        ("canonical.bs.cash_and_bank", "Cash & Cash Equivalents", False, FMT_AMOUNT, None),
        ("canonical.bs.total_assets", "Total Assets", True, FMT_AMOUNT, None),
        ("canonical.bs.total_equity", "Total Equity", True, FMT_AMOUNT, None),
        # Total liabilities is shown so the accounting identity is a real check.
        # Without it, the equity-plus-liabilities total can only be written as a
        # copy of total assets, which makes the balance unfalsifiable.
        ("canonical.bs.total_liabilities", "Total Liabilities", True, FMT_AMOUNT, None),
        # Equity + liabilities, not a copy of total assets. The two are equal by
        # construction in the engine, and showing both makes that visible rather
        # than assumed.
        ("canonical.bs.total_liabilities_and_equity", "Total Liabilities & Equity", True, FMT_AMOUNT, f"={{col}}{op_row('canonical.bs.total_equity')}+{{col}}{op_row('canonical.bs.total_liabilities')}"),
        ("canonical.cf.operating_activities", "Operating Cash Flow", True, FMT_AMOUNT, None),
        ("canonical.cf.investing_activities", "Investing Cash Flow (Capex)", True, FMT_AMOUNT, "='24_Capex_D&A'!{col}7"),
        ("canonical.cf.dividends_paid", "Dividends Paid", False, FMT_AMOUNT, None),
        ("canonical.cf.financing_activities", "Financing Cash Flow", True, FMT_AMOUNT, None),
    ]

    for idx, (ckey, label, is_tot, fmt, formula_template) in enumerate(fcst_items):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_TOTAL if is_tot else FONT_SUBHEADER

        for p_idx, p in enumerate(FORECAST_PERIODS):
            c = 3 + p_idx
            col_letter = chr(67 + p_idx)
            val = spec.forecast.get_value(ckey, p, "base")
            c_val = round(val, 2) if val is not None else 0.0

            if formula_template is not None:
                formula_str = formula_template.format(col=col_letter)
                write_formula_cell(
                    ws, r, c,
                    formula=formula_str,
                    cached_value=c_val,
                    num_format=fmt,
                    font=FONT_TOTAL if is_tot else FONT_FORMULA,
                    border=BORDER_TOTAL if is_tot else BORDER_BOX,
                    alignment=ALIGN_RIGHT,
                )
            else:
                cell = ws.cell(row=r, column=c, value=c_val)
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

    ccy = f"{spec.metadata.currency} {spec.metadata.units.capitalize()[:2]}"

    growth_rates = [get_assumption_value(spec, "revenue_growth", p) / 100.0 for p in FORECAST_PERIODS]
    rev_c_vals = [spec.forecast.get_value("canonical.is.revenue", p, "base") for p in FORECAST_PERIODS]

    # Row 6: Growth Rate %
    ws.cell(row=6, column=2, value="Assumed Revenue Growth Rate %").font = FONT_SUBHEADER
    for p_idx, g in enumerate(growth_rates):
        c = 3 + p_idx
        cell = ws.cell(row=6, column=c, value=g)
        cell.font = FONT_INPUT
        cell.number_format = FMT_PERCENT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 7: Consolidated Revenue (Dynamic Forward Formula)
    ws.cell(row=7, column=2, value=f"Consolidated Revenue ({ccy})").font = FONT_TOTAL
    for p_idx, c_val in enumerate(rev_c_vals):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        if p_idx == 0:
            form = f"='10_Income_Statement'!E6*(1+{col_let}6)"
        else:
            prev_col = chr(67 + p_idx - 1)
            form = f"={prev_col}7*(1+{col_let}6)"

        write_formula_cell(
            ws, 7, c,
            formula=form,
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_TOTAL,
            border=BORDER_TOTAL,
            alignment=ALIGN_RIGHT,
        )

    return ws


def render_cost_build(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="22_Cost_Build")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18})

    ws["B2"] = "COST BUILD & MARGIN FORECAST"
    ws["B2"].font = FONT_TITLE

    headers = ["Cost Component"] + FORECAST_PERIODS
    write_table_header(ws, 5, headers, start_col=2)

    ccy = f"{spec.metadata.currency} {spec.metadata.units.capitalize()[:2]}"

    ebitda_margins = [get_assumption_value(spec, "ebitda_margin", p) / 100.0 for p in FORECAST_PERIODS]
    ebitda_c_vals = [spec.forecast.get_value("canonical.is.ebitda", p, "base") for p in FORECAST_PERIODS]
    ebit_margins = [get_assumption_value(spec, "ebit_margin", p) / 100.0 for p in FORECAST_PERIODS]
    ebit_c_vals = [spec.forecast.get_value("canonical.is.operating_profit", p, "base") for p in FORECAST_PERIODS]

    # Row 6: EBITDA Margin % — a MEMO of the resulting margin, not a driver.
    ws.cell(row=6, column=2, value="EBITDA Margin % (derived: EBIT + D&A)").font = FONT_SUBHEADER
    for p_idx, m in enumerate(ebitda_margins):
        c = 3 + p_idx
        cell = ws.cell(row=6, column=c, value=m)
        cell.font = FONT_FORMULA
        cell.number_format = FMT_PERCENT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 7: EBITDA — DERIVED as EBIT + D&A.
    #
    # The engine derives EBITDA from EBIT and D&A rather than driving all three
    # margins independently, because three independently-averaged drivers let
    # EBITDA − D&A ≠ EBIT and the income statement stops footing. Row 7 must
    # reproduce that, or the sheet shows a margin the model never used.
    ws.cell(row=7, column=2, value=f"EBITDA ({ccy}) — derived, = EBIT + D&A").font = FONT_TOTAL
    for p_idx, c_val in enumerate(ebitda_c_vals):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        write_formula_cell(
            ws, 7, c,
            formula=f"={col_let}9+'24_Capex_D&A'!{col_let}9",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_TOTAL,
            border=BORDER_TOTAL,
            alignment=ALIGN_RIGHT,
        )

    # Row 8: Operating Profit Margin % — the driver the engine actually applies.
    ws.cell(row=8, column=2, value="Operating Profit Margin % (driver)").font = FONT_SUBHEADER
    for p_idx, m in enumerate(ebit_margins):
        c = 3 + p_idx
        cell = ws.cell(row=8, column=c, value=m)
        cell.font = FONT_INPUT
        cell.number_format = FMT_PERCENT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 9: Operating Profit (EBIT)
    ws.cell(row=9, column=2, value=f"Operating Profit (EBIT) ({ccy})").font = FONT_TOTAL
    for p_idx, c_val in enumerate(ebit_c_vals):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        write_formula_cell(
            ws, 9, c,
            formula=f"='21_Revenue_Build'!{col_let}7*{col_let}8",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_TOTAL,
            border=BORDER_TOTAL,
            alignment=ALIGN_RIGHT,
        )

    return ws


def render_working_capital(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="23_Working_Capital")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18})

    ws["B2"] = "WORKING CAPITAL FORECAST (DSO / DIO / DPO)"
    ws["B2"].font = FONT_TITLE

    headers = ["Working Capital Driver"] + FORECAST_PERIODS
    write_table_header(ws, 5, headers, start_col=2)

    ccy = f"{spec.metadata.currency} {spec.metadata.units.capitalize()[:2]}"

    dso_vals = [get_assumption_value(spec, "dso_days", p) for p in FORECAST_PERIODS]
    rec_c_vals = [spec.forecast.get_value("canonical.bs.trade_receivables", p, "base") for p in FORECAST_PERIODS]
    dpo_vals = [get_assumption_value(spec, "dpo_days", p) for p in FORECAST_PERIODS]
    pay_c_vals = [spec.forecast.get_value("canonical.bs.trade_payables", p, "base") for p in FORECAST_PERIODS]
    dio_vals = [get_assumption_value(spec, "dio_days", p) for p in FORECAST_PERIODS]
    inv_c_vals = [spec.forecast.get_value("canonical.bs.inventory", p, "base") for p in FORECAST_PERIODS]

    # Row 6: DSO
    ws.cell(row=6, column=2, value="Days Sales Outstanding (DSO)").font = FONT_SUBHEADER
    for p_idx, v in enumerate(dso_vals):
        c = 3 + p_idx
        cell = ws.cell(row=6, column=c, value=v)
        cell.font = FONT_INPUT
        cell.number_format = FMT_DAYS
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 7: Trade Receivables
    ws.cell(row=7, column=2, value=f"Trade Receivables ({ccy})").font = FONT_FORMULA
    for p_idx, c_val in enumerate(rec_c_vals):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        write_formula_cell(
            ws, 7, c,
            formula=f"='21_Revenue_Build'!{col_let}7*{col_let}6/365",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 8: DPO
    ws.cell(row=8, column=2, value="Days Payables Outstanding (DPO)").font = FONT_SUBHEADER
    for p_idx, v in enumerate(dpo_vals):
        c = 3 + p_idx
        cell = ws.cell(row=8, column=c, value=v)
        cell.font = FONT_INPUT
        cell.number_format = FMT_DAYS
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 9: Trade Payables
    ws.cell(row=9, column=2, value=f"Trade Payables ({ccy})").font = FONT_FORMULA
    for p_idx, c_val in enumerate(pay_c_vals):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        write_formula_cell(
            ws, 9, c,
            formula=f"='20_Operating_Model'!{col_let}7*{col_let}8/365",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Rows 10-11: DIO and Inventory.
    #
    # Inventory MUST be on this tab. The engine's working-capital movement is
    # (ΔAR) + (ΔInv) − (ΔAP); with no inventory row the DCF tab's level
    # difference could not express that, and the workbook silently recomputed a
    # different ΔNWC from the one the model used — a 27% (NVDA) to 57% (AWI)
    # gap in the implied share price on recalculation.
    ws.cell(row=10, column=2, value="Days Inventory Outstanding (DIO)").font = FONT_SUBHEADER
    for p_idx, v in enumerate(dio_vals):
        c = 3 + p_idx
        cell = ws.cell(row=10, column=c, value=v)
        cell.font = FONT_INPUT
        cell.number_format = FMT_DAYS
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    ws.cell(row=11, column=2, value=f"Inventory ({ccy})").font = FONT_FORMULA
    for p_idx, c_val in enumerate(inv_c_vals):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        dio = dio_vals[p_idx] or 0
        if dio > 0:
            # Inventory = COGS × DIO / 365, matching the engine.
            formula = f"='20_Operating_Model'!{col_let}7*{col_let}10/365"
        else:
            # DIO is zero because the filings report no inventory, so the engine
            # carries the opening balance flat. A live formula would recompute
            # zero and contradict the model, so this is a literal input.
            formula = None
        write_formula_cell(
            ws, 11, c,
            formula=formula,
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA if formula else FONT_INPUT,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 12: Net operating working capital — the single definition the DCF tab
    # differences, so the tab and the model cannot disagree about what NWC means.
    ws.cell(row=12, column=2, value=f"Net Operating Working Capital ({ccy})").font = FONT_TOTAL
    for p_idx in range(len(FORECAST_PERIODS)):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        write_formula_cell(
            ws, 12, c,
            formula=f"=({col_let}7+{col_let}11)-{col_let}9",
            cached_value=(
                (rec_c_vals[p_idx] or 0) + (inv_c_vals[p_idx] or 0) - (pay_c_vals[p_idx] or 0)
            ),
            num_format=FMT_AMOUNT,
            font=FONT_TOTAL,
            border=BORDER_TOTAL,
            alignment=ALIGN_RIGHT,
        )

    return ws


def render_capex_da(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="24_Capex_D&A")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18})

    ws["B2"] = "CAPEX & DEPRECIATION SCHEDULE"
    ws["B2"].font = FONT_TITLE

    headers = ["Capex & D&A Component"] + FORECAST_PERIODS
    write_table_header(ws, 5, headers, start_col=2)

    ccy = f"{spec.metadata.currency} {spec.metadata.units.capitalize()[:2]}"

    capex_pcts = [get_assumption_value(spec, "capex_pct_revenue", p) / 100.0 for p in FORECAST_PERIODS]
    capex_c_vals = [spec.forecast.get_value("canonical.cf.investing_activities", p, "base") for p in FORECAST_PERIODS]
    da_pcts = [get_assumption_value(spec, "da_pct_revenue", p) / 100.0 for p in FORECAST_PERIODS]
    da_c_vals = [spec.forecast.get_value("canonical.is.depreciation_amortization", p, "base") for p in FORECAST_PERIODS]

    # Row 6: Capex %
    ws.cell(row=6, column=2, value="Capex % Revenue").font = FONT_SUBHEADER
    for p_idx, v in enumerate(capex_pcts):
        c = 3 + p_idx
        cell = ws.cell(row=6, column=c, value=v)
        cell.font = FONT_INPUT
        cell.number_format = FMT_PERCENT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 7: Capex Outflow
    ws.cell(row=7, column=2, value=f"Capex Outflow ({ccy})").font = FONT_FORMULA
    for p_idx, c_val in enumerate(capex_c_vals):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        write_formula_cell(
            ws, 7, c,
            formula=f"=-'21_Revenue_Build'!{col_let}7*{col_let}6",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 8: D&A %
    ws.cell(row=8, column=2, value="D&A % Revenue").font = FONT_SUBHEADER
    for p_idx, v in enumerate(da_pcts):
        c = 3 + p_idx
        cell = ws.cell(row=8, column=c, value=v)
        cell.font = FONT_INPUT
        cell.number_format = FMT_PERCENT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 9: D&A Expense
    ws.cell(row=9, column=2, value=f"D&A Expense ({ccy})").font = FONT_FORMULA
    for p_idx, c_val in enumerate(da_c_vals):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        write_formula_cell(
            ws, 9, c,
            formula=f"='21_Revenue_Build'!{col_let}7*{col_let}8",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    return ws


def render_debt_schedule(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="25_Debt_Schedule")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18})

    ws["B2"] = "DEBT & BORROWINGS SCHEDULE (GENERIC)"
    ws["B2"].font = FONT_TITLE
    ccy = f"{spec.metadata.currency} {spec.metadata.units.capitalize()[:2]}"
    ws["B3"] = f"{spec.metadata.name} — debt schedule from base scenario"
    ws["B3"].font = FONT_SECTION

    headers = ["Debt Component"] + FORECAST_PERIODS
    write_table_header(ws, 5, headers, start_col=2)

    base_ds = next((d for d in spec.debt_schedule if d.scenario == "base"), None)

    def _period_val(attr: str, period: str) -> float:
        if base_ds is None:
            return 0.0
        for dp in base_ds.periods:
            if dp.period == period:
                return getattr(dp, attr)
        return 0.0

    # Row 6: Opening Debt
    ws.cell(row=6, column=2, value=f"Opening Debt Balance ({ccy})").font = FONT_SUBHEADER
    for p_idx, p in enumerate(FORECAST_PERIODS):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        val = _period_val("opening_balance", p)
        if p_idx == 0:
            cell = ws.cell(row=6, column=c, value=val)
            cell.font = FONT_INPUT
            cell.number_format = FMT_AMOUNT
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_BOX
        else:
            prev_col = chr(67 + p_idx - 1)
            write_formula_cell(
                ws, 6, c,
                formula=f"={prev_col}10",
                cached_value=val,
                num_format=FMT_AMOUNT,
                font=FONT_FORMULA,
                border=BORDER_BOX,
                alignment=ALIGN_RIGHT,
            )

    # Row 7: Debt Draws
    ws.cell(row=7, column=2, value=f"Debt Drawdowns ({ccy})").font = FONT_SUBHEADER
    for p_idx, p in enumerate(FORECAST_PERIODS):
        c = 3 + p_idx
        cell = ws.cell(row=7, column=c, value=_period_val("draws", p))
        cell.font = FONT_INPUT
        cell.number_format = FMT_AMOUNT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 8: Scheduled Repayments
    ws.cell(row=8, column=2, value=f"Scheduled Repayments ({ccy})").font = FONT_SUBHEADER
    for p_idx, p in enumerate(FORECAST_PERIODS):
        c = 3 + p_idx
        cell = ws.cell(row=8, column=c, value=_period_val("scheduled_repayment", p))
        cell.font = FONT_INPUT
        cell.number_format = FMT_AMOUNT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 9: Optional Repayments
    ws.cell(row=9, column=2, value=f"Optional Repayments ({ccy})").font = FONT_SUBHEADER
    for p_idx, p in enumerate(FORECAST_PERIODS):
        c = 3 + p_idx
        cell = ws.cell(row=9, column=c, value=_period_val("optional_repayment", p))
        cell.font = FONT_INPUT
        cell.number_format = FMT_AMOUNT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 10: Closing Debt Balance
    ws.cell(row=10, column=2, value=f"Closing Debt Balance ({ccy})").font = FONT_TOTAL
    for p_idx, p in enumerate(FORECAST_PERIODS):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        val = _period_val("closing_balance", p)
        write_formula_cell(
            ws, 10, c,
            formula=f"={col_let}6+{col_let}7-{col_let}8-{col_let}9",
            cached_value=val,
            num_format=FMT_AMOUNT,
            font=FONT_TOTAL,
            border=BORDER_TOTAL,
            alignment=ALIGN_RIGHT,
        )

    # Row 11: Interest Expense
    ws.cell(row=11, column=2, value=f"Interest Expense ({ccy})").font = FONT_FORMULA
    for p_idx, p in enumerate(FORECAST_PERIODS):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        val = _period_val("interest_expense", p)
        write_formula_cell(
            ws, 11, c,
            formula=f"=AVERAGE({col_let}6,{col_let}10)*'30_WACC'!C10",
            cached_value=val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    return ws


def render_tax_schedule(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="26_Tax_Schedule")
    apply_tab_defaults(ws, freeze_cell="C6")
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18, "F": 18, "G": 18})

    ws["B2"] = "EFFECTIVE TAX RATE SCHEDULE"
    ws["B2"].font = FONT_TITLE

    headers = ["Tax Parameter"] + FORECAST_PERIODS
    write_table_header(ws, 5, headers, start_col=2)

    ccy = f"{spec.metadata.currency} {spec.metadata.units.capitalize()[:2]}"

    tax_rates = [get_assumption_value(spec, "tax_rate", p) / 100.0 for p in FORECAST_PERIODS]
    pbt_c_vals = [spec.forecast.get_value("canonical.is.pbt", p, "base") for p in FORECAST_PERIODS]
    tax_c_vals = [spec.forecast.get_value("canonical.is.tax", p, "base") for p in FORECAST_PERIODS]

    # Row 6: Effective Tax Rate %
    ws.cell(row=6, column=2, value="Effective Tax Rate %").font = FONT_SUBHEADER
    for p_idx, v in enumerate(tax_rates):
        c = 3 + p_idx
        cell = ws.cell(row=6, column=c, value=v)
        cell.font = FONT_INPUT
        cell.number_format = FMT_PERCENT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    # Row 7: PBT
    ws.cell(row=7, column=2, value=f"PBT ({ccy})").font = FONT_FORMULA
    for p_idx, c_val in enumerate(pbt_c_vals):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        write_formula_cell(
            ws, 7, c,
            formula=f"='20_Operating_Model'!{col_let}14",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_FORMULA,
            border=BORDER_BOX,
            alignment=ALIGN_RIGHT,
        )

    # Row 8: Tax Expense
    ws.cell(row=8, column=2, value=f"Tax Expense ({ccy})").font = FONT_TOTAL
    for p_idx, c_val in enumerate(tax_c_vals):
        c = 3 + p_idx
        col_let = chr(67 + p_idx)
        write_formula_cell(
            ws, 8, c,
            formula=f"={col_let}7*{col_let}6",
            cached_value=c_val,
            num_format=FMT_AMOUNT,
            font=FONT_TOTAL,
            border=BORDER_TOTAL,
            alignment=ALIGN_RIGHT,
        )

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

    shares_val = (
        spec.metadata.shares_outstanding
        or (spec.share_count.get_diluted("FY26") if spec.share_count else None)
        or 0.0
    )
    unit_label = "M" if (spec.metadata.units == "millions" or spec.metadata.market == "us") else "Cr"

    ws.cell(row=6, column=2, value=f"Diluted Shares Outstanding ({unit_label})").font = FONT_SUBHEADER
    for idx, p in enumerate(periods):
        c = 3 + idx
        val = spec.share_count.get_diluted(p) if spec.share_count else shares_val
        cell = ws.cell(row=6, column=c, value=round(val, 4) if val else shares_val)
        cell.font = FONT_INPUT if p in FORECAST_PERIODS else FONT_FORMULA
        cell.number_format = FMT_AMOUNT
        cell.alignment = ALIGN_RIGHT
        cell.border = BORDER_BOX

    return ws
