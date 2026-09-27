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
    FILL_CODE,
    FONT_CODE,
    FONT_FORMULA,
    FONT_HEADER,
    FONT_INPUT,
    FONT_HYPERLINK,
    FONT_SIGNATURE,
    FONT_PASS,
    FONT_SECTION,
    FONT_SUBHEADER,
    FONT_SUBTITLE,
    FONT_TITLE,
    FONT_TOTAL,
)
from backend.export.excel.links import AUTHOR_URL, VALENCE_URL
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
    #
    # The wordmark is the single place on the cover that navigates to the
    # platform. The strapline beneath it is plain text: two adjacent cells
    # linking to the same destination makes a reader choose between them, and
    # neither looks like the intended one.
    ws["B2"] = "V A L E N C E"
    ws["B2"].font = FONT_BRAND_TITLE
    ws["B2"].hyperlink = VALENCE_URL
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

    # Footer note with creator hyperlink (Prominent 14pt Signature)
    ws["B20"] = "By Sourabh"
    ws["B20"].font = FONT_SIGNATURE
    ws["B20"].hyperlink = AUTHOR_URL

    return ws


def render_model_guide(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="01_Model_Guide")
    apply_tab_defaults(ws, freeze_cell="A5")
    set_col_widths(ws, {"A": 5, "B": 32, "C": 45, "D": 65})

    ws["B2"] = "WORKBOOK MODEL GUIDE & DASHBOARD"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = "Complete 30-Tab Architecture, Interactive Navigation & Financial User Guide"
    ws["B3"].font = FONT_SUBTITLE

    # ------------------------------------------------------------------ #
    # 1. Quick Jump Dashboard Bar
    # ------------------------------------------------------------------ #
    ws["B5"] = "QUICK JUMP DASHBOARD (CORE VALUATION TABS)"
    ws["B5"].font = FONT_HEADER
    ws["B5"].fill = FILL_HEADER
    ws["C5"].fill = FILL_HEADER
    ws["D5"].fill = FILL_HEADER

    quick_jumps = [
        ("02_Executive_Summary", "Executive Summary", "60-second valuation summary, upside/downside & Base/Bull/Bear price targets"),
        ("20_Operating_Model", "Operating Model", "5-year integrated 3-statement forecast model linked to schedules 21-27"),
        ("31_DCF", "DCF Valuation", "Unlevered FCFF model, WACC discount factors & present value by year"),
        ("36_EV_Bridge", "EV Bridge", "Enterprise value to equity value and implied share price, with the basis each term was struck on"),
        ("41_Valuation_Comparison", "Football Field", "Institutional multi-methodology range synthesis (DCF vs Comps vs Market)"),
        ("52_Model_Checks", "Model Audit Checks", "Automated 9-point accounting equality and financial logic audit rollup"),
    ]

    for q_idx, (t_name, label, desc) in enumerate(quick_jumps):
        r = 6 + q_idx
        ws.cell(row=r, column=2, value=f"Jump to {label}").font = FONT_SUBHEADER
        cell_q = ws.cell(row=r, column=3, value=f"Open '{t_name}'")
        cell_q.font = FONT_HYPERLINK
        cell_q.hyperlink = f"#'{t_name}'!A1"
        ws.cell(row=r, column=4, value=desc).font = FONT_FORMULA
        for c in range(2, 5):
            ws.cell(row=r, column=c).border = BORDER_BOX

    # ------------------------------------------------------------------ #
    # 2. Complete 30-Tab Architecture Directory
    # ------------------------------------------------------------------ #
    dir_start = 6 + len(quick_jumps) + 2
    ws.cell(row=dir_start, column=2, value="COMPLETE 30-TAB WORKBOOK DIRECTORY").font = FONT_TITLE
    ws.cell(row=dir_start + 1, column=2, value="Full list of all 30 worksheets grouped by model section with clickable navigation links.").font = FONT_SUBTITLE

    write_table_header(ws, dir_start + 3, ["Section / Group", "Tab Name", "Worksheet Purpose & Content Description"], start_col=2)

    guide_items = [
        # Front Matter
        ("Front Matter", "00_Cover", "Company cover page, metadata, and branding slot"),
        ("Front Matter", "01_Model_Guide", "Workbook structure and tab navigation reference"),
        ("Front Matter", "02_Executive_Summary", "60-second valuation overview & scenario outputs"),
        ("Front Matter", "03_Model_Control", "Scenario selector and global model controls"),
        # Historical Financials
        ("Historical Financials", "10_Income_Statement", "Historical Income Statement (FY24-FY26)"),
        ("Historical Financials", "11_Balance_Sheet", "Historical Balance Sheet (FY24-FY26)"),
        ("Historical Financials", "12_Cash_Flow", "Historical Cash Flow Statement (FY24-FY26)"),
        ("Historical Financials", "13_Financial_Ratios", "Historical margins, growth rates & working capital"),
        ("Historical Financials", "14_Historical_Drivers", "Historical financial driver series"),
        # Forecast & Schedules
        ("Forecast & Schedules", "20_Operating_Model", "Combined 3-statement forecast model (FY27-FY31)"),
        ("Forecast & Schedules", "21_Revenue_Build", "Segment revenue forecast & YoY growth"),
        ("Forecast & Schedules", "22_Cost_Build", "EBITDA & operating cost structure forecast"),
        ("Forecast & Schedules", "23_Working_Capital", "DSO & DPO driven working capital forecast"),
        ("Forecast & Schedules", "24_Capex_D&A", "Capex % revenue & D&A schedule"),
        ("Forecast & Schedules", "25_Debt_Schedule", "Generic debt schedule (thin for zero debt)"),
        ("Forecast & Schedules", "26_Tax_Schedule", "Effective tax rate & PBT tax forecast"),
        ("Forecast & Schedules", "27_Share_Count", "Diluted share count schedule"),
        # Valuation
        ("Valuation", "30_WACC", "WACC CAPM cost of equity & capital weighting"),
        ("Valuation", "31_DCF", "5-year FCFF build and PV discounting, year by year"),
        ("Valuation", "36_EV_Bridge", "EV -> equity value -> implied share price, with the basis and date of every term"),
        ("Valuation", "32_Terminal_Value", "Dual terminal value: Gordon Growth & Exit Multiple"),
        ("Valuation", "33_Sensitivity", "2D sensitivity grids (WACC x Growth, WACC x Multiple)"),
        ("Valuation", "34_Reverse_DCF", "Market implied perpetuity terminal growth rate"),
        ("Valuation", "35_Scenario_Analysis", "Base, Bull, Bear outputs side-by-side"),
        # Supporting Analysis
        ("Supporting Analysis", "40_Trading_Comps", "Public peer group trading multiples & implied target valuation"),
        ("Supporting Analysis", "41_Valuation_Comparison", "Institutional valuation Football Field multi-methodology range chart"),
        ("Supporting Analysis", "42_Investment_Returns", "Private Equity exit returns, 3Y/5Y MoIC and Equity IRR waterfall"),
        # QA / Documentation
        ("QA / Documentation", "50_Data_Sources", "Line item status, source filings & lineage"),
        ("QA / Documentation", "51_Assumption_Log", "Model-generated & analyst override assumptions"),
        ("QA / Documentation", "52_Model_Checks", "QA model checks rollup table and status"),
        ("QA / Documentation", "53_Methodology", "System derivation and valuation methodology notes"),
    ]

    curr_group = ""
    row_offset = dir_start + 4

    for idx, (group, tab, desc) in enumerate(guide_items):
        if group != curr_group:
            curr_group = group
            ws.cell(row=row_offset, column=2, value=group.upper()).font = FONT_SECTION
            ws.cell(row=row_offset, column=2).fill = FILL_SUBHEADER
            ws.cell(row=row_offset, column=3).fill = FILL_SUBHEADER
            ws.cell(row=row_offset, column=4).fill = FILL_SUBHEADER
            ws.cell(row=row_offset, column=2).border = BORDER_BOX
            ws.cell(row=row_offset, column=3).border = BORDER_BOX
            ws.cell(row=row_offset, column=4).border = BORDER_BOX
            row_offset += 1

        ws.cell(row=row_offset, column=2, value=group).font = FONT_SUBHEADER
        cell_tab = ws.cell(row=row_offset, column=3, value=tab)
        cell_tab.font = FONT_HYPERLINK
        cell_tab.hyperlink = f"#'{tab}'!A1"
        ws.cell(row=row_offset, column=4, value=desc).font = FONT_FORMULA
        for c in range(2, 5):
            ws.cell(row=row_offset, column=c).border = BORDER_BOX
        row_offset += 1

    # ------------------------------------------------------------------ #
    # How To Use This Model — Student & Analyst User Guide
    # ------------------------------------------------------------------ #
    start_r = 6 + len(guide_items) + 2

    ws.cell(row=start_r, column=2, value="HOW TO USE THIS MODEL (STUDENT & ANALYST GUIDE)").font = FONT_TITLE
    ws.cell(row=start_r + 1, column=2, value="A beginner-friendly step-by-step guide to reading, modifying, and understanding this financial model.").font = FONT_SUBTITLE

    # Beginner Conceptual Explanation Card Box
    r_intro = start_r + 3
    ws.cell(row=r_intro, column=2, value="1. VALUATION CONCEPTUAL OVERVIEW (WHAT IS A DCF?)").font = FONT_HEADER
    ws.cell(row=r_intro, column=2).fill = FILL_HEADER
    ws.cell(row=r_intro, column=3).fill = FILL_HEADER
    ws.cell(row=r_intro, column=4).fill = FILL_HEADER

    concept_steps = [
        ("Core Objective", "Calculate the intrinsic fair value per share of a company by discounting its future cash flow generator back to today."),
        ("Step 1: Cash Flow", "Forecast 5 years of Free Cash Flow to Firm (FCFF) — the net cash left over after operating expenses, taxes, and capital investments."),
        ("Step 2: Discount Rate", "Discount future cash flows back to present value using WACC (Weighted Average Cost of Capital) to adjust for risk and time value of money."),
        ("Step 3: Equity Bridge", "Add Cash & Investments to Enterprise Value, subtract Total Debt to find Equity Value, and divide by Diluted Share Count."),
        ("Step 4: Decision Rule", "If Implied Fair Price > Live Market Price, the stock is Undervalued (Bullish). If lower, the stock is Overvalued (Bearish)."),
    ]
    for idx, (lbl, desc) in enumerate(concept_steps):
        row_i = r_intro + 1 + idx
        ws.cell(row=row_i, column=2, value=lbl).font = FONT_SUBHEADER
        ws.cell(row=row_i, column=3, value=desc).font = FONT_FORMULA
        ws.merge_cells(start_row=row_i, start_column=3, end_row=row_i, end_column=4)
        for c in range(2, 5):
            ws.cell(row=row_i, column=c).border = BORDER_BOX

    # 2. Color Coding & Cell Conventions
    r = r_intro + len(concept_steps) + 2
    write_table_header(ws, r, ["Convention", "Cell Type", "Description & How to Interact"], start_col=2)
    
    color_guide = [
        ("Blue Text / Shaded Fill", "Analyst Input / Override", "EDITABLE BY YOU! Modify these numbers (e.g. expected revenue growth % or profit margins) in 03_Model_Control or 51_Assumption_Log."),
        ("Black Text", "Dynamic Excel Formula", "AUTOMATED MATH! Calculated automatically using standard accounting, 3-statement, and DCF formulas."),
        ("Blue Underline", "Hyperlink Navigation", "CLICKABLE LINKS! Click any tab name to navigate directly to that worksheet."),
        ("Green / Red Text", "QA / Delta Indicator", "MODEL FEEDBACK! Green indicates balance sheet 100% balance or positive upside; Red flags potential errors or downside."),
    ]
    for idx, (conv, ctype, desc) in enumerate(color_guide):
        row_i = r + 1 + idx
        ws.cell(row=row_i, column=2, value=conv).font = FONT_SUBHEADER
        ws.cell(row=row_i, column=3, value=ctype).font = FONT_FORMULA
        ws.cell(row=row_i, column=4, value=desc).font = FONT_FORMULA
        for c in range(2, 5):
            ws.cell(row=row_i, column=c).border = BORDER_BOX

    # 3. Modeling Workflow
    r_wf = r + len(color_guide) + 2
    write_table_header(ws, r_wf, ["Workflow Step", "Target Sheet", "Modeling Action & Purpose"], start_col=2)
    
    workflow_guide = [
        ("Step 1: Executive Overview", "02_Executive_Summary", "Start here! Get a 60-second summary of implied share price vs market benchmark, WACC, and scenario outputs."),
        ("Step 2: Operating Model", "20_Operating_Model", "Inspect historical financial actuals (FY24-FY26) and 5-year integrated 3-statement forecast (FY27-FY31)."),
        ("Step 3: WACC & DCF Schedule", "30_WACC & 31_DCF", "Examine CAPM Cost of Equity, mid-year discount factors (1+WACC)^-(t-0.5), and free cash flows year by year."),
        ("Step 3b: EV Bridge", "36_EV_Bridge", "Walk enterprise value to equity value and the implied share price, with the balance-sheet date and debt basis each term was struck on."),
        ("Step 4: Terminal Value & ROIC", "32_Terminal_Value", "Validate dual terminal value outputs (Gordon Growth vs Exit Multiple) and check implied terminal ROIC consistency."),
        ("Step 5: Sensitivity & Reverse DCF", "33_Sensitivity & 34_Reverse_DCF", "Test 2D sensitivity matrices (WACC x Growth, WACC x Multiple) and solve for market-implied growth expectations."),
        ("Step 6: Scenario & Audit Log", "35_Scenario_Analysis & 52_Model_Checks", "Compare Base, Bull, and Bear cases side-by-side and review automated QA check results."),
    ]
    for idx, (step, target, desc) in enumerate(workflow_guide):
        row_i = r_wf + 1 + idx
        ws.cell(row=row_i, column=2, value=step).font = FONT_SUBHEADER
        cell_t = ws.cell(row=row_i, column=3, value=target)
        cell_t.font = FONT_HYPERLINK
        first_sheet = target.split(" ")[0]
        cell_t.hyperlink = f"#'{first_sheet}'!A1"
        ws.cell(row=row_i, column=4, value=desc).font = FONT_FORMULA
        for c in range(2, 5):
            ws.cell(row=row_i, column=c).border = BORDER_BOX

    # 4. Key Valuation Formulas
    r_fm = r_wf + len(workflow_guide) + 2
    write_table_header(ws, r_fm, ["Valuation Metric", "Excel Formula Structure", "Methodology Explanation (Plain English)"], start_col=2)
    
    formula_guide = [
        ("Free Cash Flow to Firm (FCFF)", "NOPAT + D&A - CapEx - ΔNWC", "The actual cash left over for all capital providers after paying operating expenses, taxes, and capital investments."),
        ("Stock-Based Compensation Deduction", "FCFF less Stock Comp (memo row)", "SBC is a real economic cost even though non-cash under accounting rules; deducting it prevents overstating value at dilution's expense."),
        ("Mid-Year Discount Factor", "1 / ((1 + WACC) ^ (t - 0.5))", "Discounts future cash flows assuming cash is received evenly throughout the year (exponent t - 0.5 for t=1..5)."),
        ("Terminal Value (Gordon Growth)", "FCFF_5 * (1 + g) / (WACC - g)", "Estimates the value of all cash flows beyond Year 5 assuming the company grows forever at a steady rate g. Terminal growth anchors to each market's long-run nominal GDP (US ~2.25%, India ~4.0%)."),
        ("Equity Value Bridge", "EV + Cash + MktSec + NonCurrInv - Debt", "Converts Enterprise Value (business operations) to Equity Value (shareholders' wealth) by adding cash and subtracting debt."),
        ("Implied Share Price", "Equity Value / Diluted Shares", "Calculates the fair value price per share to compare directly against live market stock price."),
        ("Reverse DCF Implied Growth", "Solve g such that value equals market price", "Inverts the model to reveal what growth the market is pricing in; notes flag implied perpetuity growth outside a plausible -2% to +5% band."),
    ]
    for idx, (metric, form_str, desc) in enumerate(formula_guide):
        row_i = r_fm + 1 + idx
        ws.cell(row=row_i, column=2, value=metric).font = FONT_SUBHEADER
        cell_form = ws.cell(row=row_i, column=3, value=form_str)
        cell_form.font = FONT_CODE
        cell_form.fill = FILL_CODE
        cell_form.alignment = ALIGN_LEFT
        ws.cell(row=row_i, column=4, value=desc).font = FONT_FORMULA
        for c in range(2, 5):
            ws.cell(row=row_i, column=c).border = BORDER_BOX

    return ws


def _model_status_label(spec) -> str:
    """The QA banner, qualified by any valuation method that produced nothing.

    The QA checks are structural: they ask whether the arithmetic ties and
    whether the inputs are sound. None of them can notice that an entire
    valuation method was absent, because the comparables analysis is built at
    render time and a company whose peers cannot be sourced has nothing wrong
    with its balance sheet.

    A workbook therefore read "MODEL VALID" while its comparables page was
    entirely empty — every check passing, and one of the ways of valuing the
    company silently missing. The banner is where a reader looks first, so it is
    where that has to be said.
    """
    label = spec.qa.summary_label if spec.qa else "MODEL VALID"
    if not label.startswith("MODEL VALID"):
        return label

    try:
        from backend.valuation.comps import compute_trading_comps

        base_val = spec.get_valuation("base")
        bridge = base_val.dcf_bridge if base_val else None
        comps = compute_trading_comps(
            target_ticker=spec.metadata.ticker,
            target_sector=spec.metadata.sector or "Technology",
            target_revenue_fy27=spec.forecast.get_value("canonical.is.revenue", "FY27", "base") or 1000.0,
            target_ebitda_fy27=spec.forecast.get_value("canonical.is.ebitda", "FY27", "base") or 300.0,
            target_net_profit_fy27=spec.forecast.get_value("canonical.is.net_profit", "FY27", "base") or 150.0,
            net_debt=(bridge.less_net_debt if bridge else 0.0) or 0.0,
            shares_outstanding=(bridge.shares_outstanding if bridge else 100.0) or 100.0,
        )
    except Exception:
        return f"{label} — COMPARABLES UNAVAILABLE"

    if not comps.peers or not comps.implied_valuations:
        return f"{label} — COMPARABLES UNAVAILABLE"
    return label


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
    # The KPI card shows a bare price; stamp its date + provider on the label so
    # a reader can never mistake a stale benchmark for a live quote.
    rev_dcf = base_val.reverse_dcf if base_val else None
    if rev_dcf is not None and rev_dcf.market_price:
        prov_date = rev_dcf.market_price_date or "unknown"
        prov_src = rev_dcf.market_price_source or "unknown"
        ws["B5"] = f"Market Benchmark Price (as of {prov_date} · {prov_src})"

    write_formula_cell(ws, 6, 3, "='35_Scenario_Analysis'!C6", cached_value=base_price, num_format=FMT_PRICE)
    write_formula_cell(ws, 6, 4, '=IF(B6=0,"N/A",(C6-B6)/B6)', cached_value=(upside_pct / 100.0), num_format=FMT_PERCENT)
    write_formula_cell(ws, 6, 5, "='30_WACC'!C15", cached_value=wacc_pct, num_format=FMT_PERCENT)

    ws["F6"] = _model_status_label(spec)

    for c in range(2, 7):
        cell = ws.cell(row=6, column=c)
        cell.font = FONT_TITLE
        cell.alignment = ALIGN_CENTER
        cell.fill = FILL_CARD
        cell.border = BORDER_BOX

    if "COMPARABLES UNAVAILABLE" in str(ws["F6"].value):
        # A missing method is not a green light. The banner is shaded as a
        # warning rather than a pass, so the state is visible before the words
        # are read.
        ws["F6"].fill = FILL_FAIL
        ws["F6"].font = FONT_ALERT
    elif spec.qa and spec.qa.all_passed:
        ws["F6"].fill = FILL_PASS
        ws["F6"].font = FONT_PASS
    else:
        ws["F6"].fill = FILL_FAIL
        ws["F6"].font = FONT_ALERT

    # Valuation Comparison Table
    write_table_header(ws, 9, ["Valuation Metric", "Base Scenario", "Bull Scenario", "Bear Scenario"], start_col=2)

    ccy = f"{spec.metadata.currency} {spec.metadata.units.capitalize()[:2]}"
    curr = spec.metadata.currency

    # Final-year revenue and margin are read from each scenario's OWN forecast.
    #
    # They used to be back-solved: final-year EBITDA divided by the ebitda_margin
    # driver. The engine derives earnings as operating profit plus depreciation,
    # so that driver does not move the model. For a company whose margin resolves
    # to zero the division returned zero and the executive summary published
    # FY31 revenue of 0 against an actual 712.92 — the first page of the workbook
    # stating a company earns nothing.
    def _final_year(scenario: str) -> tuple[float, float]:
        revenue = spec.forecast.get_value("canonical.is.revenue", "FY31", scenario) or 0.0
        ebitda = spec.forecast.get_value("canonical.is.ebitda", "FY31", scenario) or 0.0
        return revenue, (ebitda / revenue) if revenue else 0.0

    rev_base, r_base_pct = _final_year("base")
    rev_bull, r_bull_pct = _final_year("bull")
    rev_bear, r_bear_pct = _final_year("bear")

    val_rows = [
        (f"Implied Share Price ({curr})", "='35_Scenario_Analysis'!C6", "='35_Scenario_Analysis'!D6", "='35_Scenario_Analysis'!E6", base_price, bull_price, bear_price, FMT_PRICE),
        (f"Enterprise Value ({ccy})", "='35_Scenario_Analysis'!C7", "='35_Scenario_Analysis'!D7", "='35_Scenario_Analysis'!E7", base_val.dcf_bridge.enterprise_value if base_val else 0, bull_val.dcf_bridge.enterprise_value if bull_val else 0, bear_val.dcf_bridge.enterprise_value if bear_val else 0, FMT_CURRENCY_INT),
        (f"Net Cash / (Debt) ({ccy})", "='35_Scenario_Analysis'!C8", "='35_Scenario_Analysis'!D8", "='35_Scenario_Analysis'!E8", -base_val.dcf_bridge.less_net_debt if (base_val and base_val.dcf_bridge.less_net_debt is not None) else 0, -bull_val.dcf_bridge.less_net_debt if (bull_val and bull_val.dcf_bridge.less_net_debt is not None) else 0, -bear_val.dcf_bridge.less_net_debt if (bear_val and bear_val.dcf_bridge.less_net_debt is not None) else 0, FMT_CURRENCY_INT),
        (f"Equity Value ({ccy})", "='35_Scenario_Analysis'!C9", "='35_Scenario_Analysis'!D9", "='35_Scenario_Analysis'!E9", base_val.dcf_bridge.equity_value if base_val else 0, bull_val.dcf_bridge.equity_value if bull_val else 0, bear_val.dcf_bridge.equity_value if bear_val else 0, FMT_CURRENCY_INT),
        ("Diluted Shares", "='35_Scenario_Analysis'!C10", "='35_Scenario_Analysis'!D10", "='35_Scenario_Analysis'!E10", base_val.dcf_bridge.shares_outstanding if base_val else 0, bull_val.dcf_bridge.shares_outstanding if bull_val else 0, bear_val.dcf_bridge.shares_outstanding if bear_val else 0, FMT_AMOUNT),
        ("Discount Rate (WACC %)", "='35_Scenario_Analysis'!C11", "='35_Scenario_Analysis'!D11", "='35_Scenario_Analysis'!E11", (base_val.wacc.wacc / 100.0) if (base_val and base_val.wacc.wacc is not None) else 0, (bull_val.wacc.wacc / 100.0) if (bull_val and bull_val.wacc.wacc is not None) else 0, (bear_val.wacc.wacc / 100.0) if (bear_val and bear_val.wacc.wacc is not None) else 0, FMT_PERCENT),
        ("Terminal Growth Rate %", "='35_Scenario_Analysis'!C12", "='35_Scenario_Analysis'!D12", "='35_Scenario_Analysis'!E12", (base_val.terminal_value.terminal_growth_rate / 100.0) if (base_val and base_val.terminal_value.terminal_growth_rate is not None) else 0, (bull_val.terminal_value.terminal_growth_rate / 100.0) if (bull_val and bull_val.terminal_value.terminal_growth_rate is not None) else 0, (bear_val.terminal_value.terminal_growth_rate / 100.0) if (bear_val and bear_val.terminal_value.terminal_growth_rate is not None) else 0, FMT_PERCENT),
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
        ("Model Mode", "Analyst Mode", "Full financial modeling mode with all supporting tabs"),
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
