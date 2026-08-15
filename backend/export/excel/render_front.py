from __future__ import annotations

"""
Front Matter Tabs Renderer.

Renders:
- 00_Cover: Company cover page with metadata and placeholder branding
- 01_Model_Guide: Navigation guide for workbook tabs
- 02_Executive_Summary: 60-second valuation summary (share price, upside, EV, WACC, scenarios side-by-side)
- 03_Model_Control: Scenario control and global parameters
"""

from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from backend.export.excel.builder import (
    apply_tab_defaults,
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
    FILL_CARD,
    FILL_HEADER,
    FILL_PASS,
    FILL_FAIL,
    FILL_SUBHEADER,
    FMT_AMOUNT,
    FMT_CURRENCY_INT,
    FMT_PERCENT,
    FMT_PRICE,
    FONT_ALERT,
    FONT_BRAND_SUBTITLE,
    FONT_BRAND_TITLE,
    FONT_FORMULA,
    FONT_HEADER,
    FONT_INPUT,
    FONT_HYPERLINK,
    FONT_PASS,
    FONT_SECTION,
    FONT_SUBHEADER,
    FONT_SUBTITLE,
    FONT_TITLE,
    FONT_TOTAL,
)
from backend.models.spec.model_specification import ModelSpecification


def get_assumption_value(spec: ModelSpecification, driver_key: str, period: str, scenario: str = "base") -> float:
    for a in spec.assumptions:
        if a.driver_key == driver_key and a.scenario == scenario and (a.period == period or a.period == "all"):
            return a.value
    return 0.0


def render_cover(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="00_Cover")
    apply_tab_defaults(ws, freeze_cell="A1")
    set_col_widths(ws, {"A": 5, "B": 28, "C": 45, "D": 20})

    # Header / Branding Slot (Clean design font — no logo image)
    ws["B2"] = "V A L E N C E"
    ws["B2"].font = FONT_BRAND_TITLE
    ws["B2"].alignment = ALIGN_LEFT

    ws["B3"] = "VALENCE VALUATION PLATFORM"
    ws["B3"].font = FONT_BRAND_SUBTITLE
    ws["B3"].alignment = ALIGN_LEFT

    ws["B5"] = spec.metadata.name.upper()
    ws["B5"].font = FONT_TITLE

    ws["B6"] = f"Ticker: {spec.metadata.ticker} | Market: {spec.metadata.market.upper()} | Fiscal Basis: {spec.metadata.fiscal_year_end}"
    ws["B6"].font = FONT_SECTION

    # Metadata Card Box
    ws["B7"] = "MODEL METADATA"
    ws["B7"].font = FONT_HEADER
    ws["B7"].fill = FILL_HEADER
    ws["C7"].fill = FILL_HEADER

    metadata_items = [
        ("Company Name", spec.metadata.name),
        ("Ticker Symbol", spec.metadata.ticker),
        ("Primary Market", spec.metadata.market.upper()),
        ("Reporting Currency", spec.metadata.currency),
        ("Display Units", spec.metadata.units),
        ("Model Specification Version", spec.metadata.model_version),
        ("Model Generation Date", str(spec.metadata.generation_date)[:10]),
        ("Historical Periods", ", ".join(spec.historicals.periods)),
        ("Forecast Periods", ", ".join(spec.forecast.periods)),
        ("Scenarios Modeled", ", ".join([s.scenario_id for s in spec.scenarios]) if spec.scenarios else "base, bull, bear"),
    ]

    for idx, (lbl, val) in enumerate(metadata_items):
        row = 8 + idx
        ws.cell(row=row, column=2, value=lbl).font = FONT_SUBHEADER
        ws.cell(row=row, column=3, value=val).font = FONT_FORMULA
        ws.cell(row=row, column=2).border = BORDER_BOX
        ws.cell(row=row, column=3).border = BORDER_BOX

    # Footer note
    ws["B20"] = "CONFIDENTIAL — FOR INTERNAL ANALYST USE ONLY"
    ws["B20"].font = FONT_SUBTITLE

    return ws


def render_model_guide(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="01_Model_Guide")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 25, "C": 28, "D": 50})

    ws["B2"] = "WORKBOOK MODEL GUIDE"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "Complete Tab Architecture and Navigation Reference"
    ws["B3"].font = FONT_SUBTITLE

    write_table_header(ws, 5, ["Group", "Tab Name", "Description"], start_col=2)

    guide_items = [
        ("Front Matter", "00_Cover", "Company cover page, metadata, and branding slot"),
        ("Front Matter", "01_Model_Guide", "Workbook structure and tab navigation reference"),
        ("Front Matter", "02_Executive_Summary", "60-second valuation overview & scenario outputs"),
        ("Front Matter", "03_Model_Control", "Scenario selector and global model controls"),
        ("Historical Financials", "10_Income_Statement", "Historical Income Statement (FY24-FY26)"),
        ("Historical Financials", "11_Balance_Sheet", "Historical Balance Sheet (FY24-FY26)"),
        ("Historical Financials", "12_Cash_Flow", "Historical Cash Flow Statement (FY24-FY26)"),
        ("Historical Financials", "13_Financial_Ratios", "Historical margins, growth rates & working capital"),
        ("Historical Financials", "14_Historical_Drivers", "Historical financial driver series"),
        ("Forecast & Schedules", "20_Operating_Model", "Combined 3-statement forecast model (FY27-FY31)"),
        ("Forecast & Schedules", "21_Revenue_Build", "Segment revenue forecast & YoY growth"),
        ("Forecast & Schedules", "22_Cost_Build", "EBITDA & operating cost structure forecast"),
        ("Forecast & Schedules", "23_Working_Capital", "DSO & DPO driven working capital forecast"),
        ("Forecast & Schedules", "24_Capex_D&A", "Capex % revenue & D&A schedule"),
        ("Forecast & Schedules", "25_Debt_Schedule", "Generic debt schedule (thin for zero debt)"),
        ("Forecast & Schedules", "26_Tax_Schedule", "Effective tax rate & PBT tax forecast"),
        ("Forecast & Schedules", "27_Share_Count", "Diluted share count schedule"),
        ("Valuation", "30_WACC", "WACC CAPM cost of equity & capital weighting"),
        ("Valuation", "31_DCF", "5-year FCFF, PV discounting, and EV -> Price bridge"),
        ("Valuation", "32_Terminal_Value", "Dual terminal value: Gordon Growth & Exit Multiple"),
        ("Valuation", "33_Sensitivity", "2D sensitivity grids (WACC x Growth, WACC x Multiple)"),
        ("Valuation", "34_Reverse_DCF", "Market implied perpetuity terminal growth rate"),
        ("Valuation", "35_Scenario_Analysis", "Base, Bull, Bear outputs side-by-side"),
        ("QA / Documentation", "50_Data_Sources", "Line item status, source filings & lineage"),
        ("QA / Documentation", "51_Assumption_Log", "Model-generated & analyst override assumptions"),
        ("QA / Documentation", "52_Model_Checks", "QA model checks rollup table and status"),
        ("QA / Documentation", "53_Methodology", "System derivation and valuation methodology notes"),
    ]

    for idx, (group, tab, desc) in enumerate(guide_items):
        row = 6 + idx
        ws.cell(row=row, column=2, value=group).font = FONT_SUBHEADER
        cell_tab = ws.cell(row=row, column=3, value=tab)
        cell_tab.font = FONT_HYPERLINK
        cell_tab.hyperlink = f"#'{tab}'!A1"
        ws.cell(row=row, column=4, value=desc).font = FONT_FORMULA
        for c in range(2, 5):
            ws.cell(row=row, column=c).border = BORDER_BOX

    return ws


def render_executive_summary(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="02_Executive_Summary")
    apply_tab_defaults(ws, freeze_cell="A6")
    set_col_widths(ws, {"A": 5, "B": 32, "C": 18, "D": 18, "E": 18, "F": 22})

    ws["B2"] = f"{spec.metadata.name.upper()} ({spec.metadata.ticker})"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "EXECUTIVE VALUATION SUMMARY (60-SECOND OVERVIEW)"
    ws["B3"].font = FONT_SECTION

    # Fetch Base / Bull / Bear valuation outputs
    base_val = spec.get_valuation("base")
    bull_val = spec.get_valuation("bull")
    bear_val = spec.get_valuation("bear")

    mkt_price = base_val.reverse_dcf.market_price if (base_val and base_val.reverse_dcf and base_val.reverse_dcf.market_price) else 0.0
    base_price = base_val.dcf_bridge.implied_share_price if (base_val and base_val.dcf_bridge) else 0.0
    bull_price = bull_val.dcf_bridge.implied_share_price if (bull_val and bull_val.dcf_bridge) else 0.0
    bear_price = bear_val.dcf_bridge.implied_share_price if (bear_val and bear_val.dcf_bridge) else 0.0

    upside_pct = ((base_price - mkt_price) / mkt_price * 100.0) if mkt_price > 0 else 0.0

    # Key KPI Cards Header Row
    ws["B5"] = "Market Benchmark Price"
    ws["C5"] = "Base Implied Price"
    ws["D5"] = "Implied Upside / (Downside)"
    ws["E5"] = "WACC %"
    ws["F5"] = "QA Status"

    for c in range(2, 7):
        cell = ws.cell(row=5, column=c)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER

    wacc_pct = (base_val.wacc.wacc / 100.0) if (base_val and base_val.wacc and base_val.wacc.wacc) else 0.12

    ws["B6"] = mkt_price
    ws["B6"].number_format = FMT_PRICE

    write_formula_cell(ws, 6, 3, "='35_Scenario_Analysis'!C6", cached_value=base_price, num_format=FMT_PRICE)
    write_formula_cell(ws, 6, 4, "=(C6-B6)/B6", cached_value=(upside_pct / 100.0), num_format=FMT_PERCENT)
    write_formula_cell(ws, 6, 5, "='30_WACC'!C15", cached_value=wacc_pct, num_format=FMT_PERCENT)

    ws["F6"] = spec.qa.summary_label if spec.qa else "MODEL VALID"

    for c in range(2, 7):
        cell = ws.cell(row=6, column=c)
        cell.font = FONT_TITLE
        cell.alignment = ALIGN_CENTER
        cell.fill = FILL_CARD
        cell.border = BORDER_BOX

    if spec.qa and spec.qa.all_passed:
        ws["F6"].fill = FILL_PASS
        ws["F6"].font = FONT_PASS
    else:
        ws["F6"].fill = FILL_FAIL
        ws["F6"].font = FONT_ALERT

    # Valuation Comparison Table
    write_table_header(ws, 9, ["Valuation Metric", "Base Scenario", "Bull Scenario", "Bear Scenario"], start_col=2)

    ccy = f"{spec.metadata.currency} {spec.metadata.units.capitalize()[:2]}"
    curr = spec.metadata.currency

    r_base_pct = get_assumption_value(spec, "ebitda_margin", "FY31", "base") / 100.0
    r_bull_pct = get_assumption_value(spec, "ebitda_margin", "FY31", "bull") / 100.0
    r_bear_pct = get_assumption_value(spec, "ebitda_margin", "FY31", "bear") / 100.0

    ebitda_base = base_val.terminal_value.final_year_ebitda if base_val else 0.0
    ebitda_bull = bull_val.terminal_value.final_year_ebitda if bull_val else 0.0
    ebitda_bear = bear_val.terminal_value.final_year_ebitda if bear_val else 0.0

    rev_base = (ebitda_base / r_base_pct) if r_base_pct > 0 else 0.0
    rev_bull = (ebitda_bull / r_bull_pct) if r_bull_pct > 0 else 0.0
    rev_bear = (ebitda_bear / r_bear_pct) if r_bear_pct > 0 else 0.0

    val_rows = [
        (f"Implied Share Price ({curr})", "='35_Scenario_Analysis'!C6", "='35_Scenario_Analysis'!D6", "='35_Scenario_Analysis'!E6", base_price, bull_price, bear_price, FMT_PRICE),
        (f"Enterprise Value ({ccy})", "='35_Scenario_Analysis'!C7", "='35_Scenario_Analysis'!D7", "='35_Scenario_Analysis'!E7", base_val.dcf_bridge.enterprise_value if base_val else 0, bull_val.dcf_bridge.enterprise_value if bull_val else 0, bear_val.dcf_bridge.enterprise_value if bear_val else 0, FMT_CURRENCY_INT),
        (f"Net Cash / (Debt) ({ccy})", "='35_Scenario_Analysis'!C8", "='35_Scenario_Analysis'!D8", "='35_Scenario_Analysis'!E8", -base_val.dcf_bridge.less_net_debt if base_val else 0, -bull_val.dcf_bridge.less_net_debt if bull_val else 0, -bear_val.dcf_bridge.less_net_debt if bear_val else 0, FMT_CURRENCY_INT),
        (f"Equity Value ({ccy})", "='35_Scenario_Analysis'!C9", "='35_Scenario_Analysis'!D9", "='35_Scenario_Analysis'!E9", base_val.dcf_bridge.equity_value if base_val else 0, bull_val.dcf_bridge.equity_value if bull_val else 0, bear_val.dcf_bridge.equity_value if bear_val else 0, FMT_CURRENCY_INT),
        ("Diluted Shares", "='35_Scenario_Analysis'!C10", "='35_Scenario_Analysis'!D10", "='35_Scenario_Analysis'!E10", base_val.dcf_bridge.shares_outstanding if base_val else 0, bull_val.dcf_bridge.shares_outstanding if bull_val else 0, bear_val.dcf_bridge.shares_outstanding if bear_val else 0, FMT_AMOUNT),
        ("Discount Rate (WACC %)", "='35_Scenario_Analysis'!C11", "='35_Scenario_Analysis'!D11", "='35_Scenario_Analysis'!E11", (base_val.wacc.wacc / 100.0) if base_val else 0, (bull_val.wacc.wacc / 100.0) if bull_val else 0, (bear_val.wacc.wacc / 100.0) if bear_val else 0, FMT_PERCENT),
        ("Terminal Growth Rate %", "='35_Scenario_Analysis'!C12", "='35_Scenario_Analysis'!D12", "='35_Scenario_Analysis'!E12", (base_val.terminal_value.terminal_growth_rate / 100.0) if base_val else 0, (bull_val.terminal_value.terminal_growth_rate / 100.0) if bull_val else 0, (bear_val.terminal_value.terminal_growth_rate / 100.0) if bear_val else 0, FMT_PERCENT),
        (f"FY31 Revenue ({ccy})", "='35_Scenario_Analysis'!C13", "='35_Scenario_Analysis'!D13", "='35_Scenario_Analysis'!E13", rev_base, rev_bull, rev_bear, FMT_CURRENCY_INT),
        ("FY31 EBITDA Margin %", "='35_Scenario_Analysis'!C14", "='35_Scenario_Analysis'!D14", "='35_Scenario_Analysis'!E14", r_base_pct, r_bull_pct, r_bear_pct, FMT_PERCENT),
    ]

    for idx, (lbl, f_base, f_bull, f_bear, v_base, v_bull, v_bear, fmt) in enumerate(val_rows):
        r = 10 + idx
        ws.cell(row=r, column=2, value=lbl).font = FONT_TOTAL if idx == 0 else FONT_SUBHEADER
        ws.cell(row=r, column=2).border = BORDER_TOTAL if idx == 0 else BORDER_BOX
        
        for c_offset, (form_str, val_num) in enumerate([(f_base, v_base), (f_bull, v_bull), (f_bear, v_bear)]):
            c = 3 + c_offset
            write_formula_cell(
                ws, r, c,
                formula=form_str,
                cached_value=val_num,
                num_format=fmt,
                font=FONT_TOTAL if idx == 0 else FONT_FORMULA,
                border=BORDER_TOTAL if idx == 0 else BORDER_BOX,
                alignment=ALIGN_RIGHT,
            )

    return ws


def render_model_control(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="03_Model_Control")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 30, "C": 25, "D": 40})

    ws["B2"] = "MODEL CONTROL & SCENARIO SELECTION"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "Global Model Parameters and Active Scenario Toggles"
    ws["B3"].font = FONT_SUBTITLE

    write_table_header(ws, 5, ["Control Parameter", "Current Value", "Description"], start_col=2)

    controls = [
        ("Active Scenario", "base", "Primary scenario driving live model sheets (base / bull / bear)"),
        ("Model Mode", "Analyst Mode", "Full financial modeling mode with 23 detail tabs"),
        ("Taxonomy Mapping", f"{spec.metadata.market.upper()} Normalized Taxonomy v1.0", "Normalized financial taxonomy registry"),
        ("Model Schema Version", spec.metadata.model_version, "Pydantic contract schema version"),
        ("Reporting Currency", spec.metadata.currency, "Company financial statement currency"),
        ("Display Unit Basis", spec.metadata.units, f"Monetary figures in {spec.metadata.currency} {spec.metadata.units.capitalize()}"),
    ]

    for idx, (lbl, val, desc) in enumerate(controls):
        r = 6 + idx
        ws.cell(row=r, column=2, value=lbl).font = FONT_SUBHEADER
        ws.cell(row=r, column=3, value=val).font = FONT_INPUT
        ws.cell(row=r, column=4, value=desc).font = FONT_FORMULA
        for c in range(2, 5):
            ws.cell(row=r, column=c).border = BORDER_BOX

    return ws
