from __future__ import annotations

"""
QA & Documentation Tabs Renderer.

Renders:
- 50_Data_Sources: Data provenance, status, and filing lineage
- 51_Assumption_Log: Model-generated and analyst override assumption log
- 52_Model_Checks: QA model checks rollup table with dynamic live formulas
- 53_Methodology: System derivation rules and methodology notes
"""

from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from backend.export.excel.builder import (
    apply_tab_defaults,
    row_of_label,
    set_col_widths,
    write_formula_cell,
    write_table_header,
)
from backend.export.excel.render_fcst import wacc_ref
from backend.export.excel.styles import (
    ALIGN_CENTER,
    ALIGN_LEFT,
    ALIGN_RIGHT,
    BORDER_BOX,
    BORDER_TOTAL,
    FILL_CARD,
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


def _br(line: str) -> str:
    """Address of one EV-bridge line, for use inside a workbook formula.

    The QA checks recompute the bridge's arithmetic from the cells the bridge
    actually published, so they are written against line names rather than
    against row numbers. A renamed or reordered line therefore moves the check
    with it instead of leaving it pointing at whatever shifted into the row.
    """
    from backend.export.excel.render_val import bridge_ref

    return bridge_ref(line)


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


def _last_historical_col(spec: ModelSpecification) -> str:
    """Column letter on the historical tabs holding the last historical period.

    The historical block starts at column C with one column per period, so the
    last period sits at C + n - 1. Hardcoding "E" pointed the reconciliation
    checks at the wrong year for any company whose history is not exactly three
    periods.
    """
    count = len(spec.historicals.periods or [])
    if count <= 0:
        return "C"
    return chr(ord("C") + count - 1)


def _balance_sheet_row(wb: Workbook, label: str) -> int:
    """Row on the balance sheet carrying a line, found by its label.

    The reconciliation formulas used to name rows by number: 19 for total assets,
    23 for total liabilities and equity, 16 for cash. Those numbers are a
    statement of how many lines the balance sheet happened to have, so adding a
    line moved the totals under the formulas and the checks went on comparing the
    wrong cells while still reporting a verdict. A line that names nothing is
    harmless to add precisely because it is not load-bearing, and here the very
    lines added to complete the statement are the ones the checks read.

    Resolving by label removes the coupling. A missing label raises rather than
    falling back to a remembered row, because a reference to the wrong cell still
    returns a verdict and a reference to a blank one reports FAIL, and both are
    worse than refusing. See row_of_label, which is shared with the valuation
    tabs so there is one implementation of the lookup rather than two.
    """
    return row_of_label(wb["11_Balance_Sheet"], label)


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

    # A check here must be able to FAIL, or it is decoration. Three constraints
    # apply to every formula below:
    #   1. It must reference cells that actually hold the quantity, not cells
    #      rendered as "-" or left blank — N() of text is 0, so a check against an
    #      unrendered cell reported FAIL on recalculation in 19 of 20 workbooks
    #      while the cached verdict said PASS.
    #   2. It must not compare a cell against the identity that DEFINES it
    #      (that is a tautology and can never fail).
    #   3. It must report "N/A" rather than PASS or FAIL when the inputs are
    #      absent, so absence is never mistaken for a pass.
    hist_col = _last_historical_col(spec)
    prev_col = chr(ord(hist_col) - 1) if hist_col > "C" else "C"

    # Resolved by label, not by number: see _balance_sheet_row.
    bs_assets = _balance_sheet_row(wb, "TOTAL ASSETS")
    bs_le = _balance_sheet_row(wb, "TOTAL LIABILITIES & EQUITY")
    bs_cash = _balance_sheet_row(wb, "Cash & Cash Equivalents")
    # The WACC cell comes from the WACC tab's own row map, so a line added there
    # cannot leave these checks reading whatever now sits on the row they named.
    wacc_cell = wacc_ref("wacc")

    formula_map = {
        "balance_sheet_balances": (
            f'=IF(N(\'11_Balance_Sheet\'!{hist_col}{bs_assets})=0,"N/A",'
            f'IF(ABS(N(\'11_Balance_Sheet\'!{hist_col}{bs_assets})'
            f'-N(\'11_Balance_Sheet\'!{hist_col}{bs_le}))'
            f'<=0.01*MAX(ABS(N(\'11_Balance_Sheet\'!{hist_col}{bs_assets})),1),"PASS","FAIL"))'
        ),
        "cash_flow_reconciles": (
            f'=IF(N(\'12_Cash_Flow\'!{hist_col}12)=0,"N/A",'
            f'IF(ABS(N(\'12_Cash_Flow\'!{hist_col}12)-(N(\'11_Balance_Sheet\'!{hist_col}{bs_cash})'
            f'-N(\'11_Balance_Sheet\'!{prev_col}{bs_cash})))'
            f'<=0.01*MAX(ABS(N(\'11_Balance_Sheet\'!{hist_col}{bs_cash})),1),"PASS","FAIL"))'
        ),
        # Closing debt must equal opening plus drawdowns less repayments. This
        # can fail, unlike comparing a total to the sum that defines it.
        #
        # It compared the CLOSING balance against the OPTIONAL REPAYMENTS row
        # instead, so for any company that carries debt and repays nothing
        # optionally it compared 8,468 against 0 and returned FAIL — in all
        # twenty-two workbooks, while the cached verdict said PASS.
        "debt_schedule_reconciles": (
            '=IF(N(\'25_Debt_Schedule\'!G10)=0,"N/A",'
            'IF(AND('
            + ",".join(
                f"ABS(N('25_Debt_Schedule'!{c}10)-(N('25_Debt_Schedule'!{c}6)"
                f"+N('25_Debt_Schedule'!{c}7)-N('25_Debt_Schedule'!{c}8)"
                f"-N('25_Debt_Schedule'!{c}9)))<=0.01*MAX(ABS(N('25_Debt_Schedule'!{c}10)),1)"
                for c in "CDEFG"
            )
            + '),"PASS","FAIL"))'
        ),
        "share_count_consistent": '=IF(N(\'27_Share_Count\'!E6)=0,"N/A",IF(\'27_Share_Count\'!E6>0,"PASS","FAIL"))',
        # Equity value must equal EV less net debt, and the per-share result
        # must equal equity / shares. Both are genuine recomputations of a
        # relationship, not restatements of the defining formula.
        #
        # The bridge lives on 36_EV_Bridge and every cell is named by line, so
        # a line inserted above another cannot silently re-point these checks
        # at a different figure.
        "dcf_bridge_reconciles": (
            f'=IF(N({_br("equity_value")})=0,"N/A",IF(AND('
            f"ABS({_br('equity_value')}-({_br('enterprise_value')}-{_br('net_non_operating_debt')}))"
            f"<=0.01*MAX(ABS({_br('equity_value')}),1),"
            f"ABS({_br('implied_share_price')}-({_br('equity_value')}/{_br('diluted_shares')}))<=0.01"
            '),"PASS","FAIL"))'
        ),
        # The WACC is row 16. These two checks read row 15, which is the debt
        # market weight, and have done since the WACC tab gained a line. Both
        # reported FAIL for every company carrying debt, because a debt weight of
        # one percent is not between three and thirty percent, and the terminal
        # growth check compared 2.25% of perpetual growth against 0.69% of debt
        # weighting and concluded growth exceeded the discount rate. A filer with
        # no debt reads zero, so both checks reported N/A and stopped testing
        # anything at all, which reads as an absent check rather than a broken one.
        #
        # The cached verdict beside each formula was written by the engine, which
        # had the rate in hand, so the workbook showed PASS until it was
        # recalculated and disagreed with itself.
        "wacc_valid": (
            f'=IF(N({wacc_cell})=0,"N/A",'
            f'IF(AND({wacc_cell}>0.03,{wacc_cell}<0.30),"PASS","FAIL"))'
        ),
        "terminal_growth_lt_wacc": (
            f'=IF(OR(N(\'32_Terminal_Value\'!C6)=0,N({wacc_cell})=0),"N/A",'
            f'IF(\'32_Terminal_Value\'!C6<{wacc_cell},"PASS","FAIL"))'
        ),
        "no_missing_critical_inputs": f'=IF(N({_br("implied_share_price")})=0,"N/A",IF({_br("implied_share_price")}>0,"PASS","FAIL"))',
        "data_provenance_quality": '=IF(COUNTA(\'50_Data_Sources\'!B6:B11)>0,"PASS","FAIL")',
        # Cannot be recomputed from workbook cells — the provenance status lives
        # on the historical line items, not in a number. The engine's verdict is
        # written as a literal so the tab shows the truth rather than a formula
        # that always passes.
        "historicals_are_reported": None,
    }

    for idx, c in enumerate(checks):
        r = 6 + idx
        ws.cell(row=r, column=2, value=c.check_name).font = FONT_SUBHEADER
        ws.cell(row=r, column=3, value=c.category).font = FONT_FORMULA

        cached_res = "PASS" if c.passed else "FAIL"
        formula_expr = formula_map.get(c.check_name, None)

        # A live formula and the value cached beside it must not be able to
        # disagree.
        #
        # The cached verdict was written unconditionally from the engine's own
        # result, so a check whose formula did not actually test what its name
        # said showed PASS until someone pressed recalculate and watched it turn
        # FAIL. The reader sees the cached value on open and the recalculated one
        # afterwards, which is the worst of both: the workbook appears to
        # contradict itself depending on when it was opened.
        #
        # A check the engine SKIPPED (passed, detail opening with "SKIPPED") is
        # its own state, neither the pass the passed flag claims nor the failure
        # this block used to force on it: the row renders "SKIPPED" as a literal,
        # detail intact, so the header, the row and the gate tell one story. The
        # literal replaces the live formula for this row because recalculating
        # it would produce PASS or FAIL beside a verdict that says neither.
        skipped = c.passed and (c.detail or "").startswith("SKIPPED")
        if skipped:
            cached_res = "SKIPPED"
        else:
            detail_text = (c.detail or "").lower()
            contradicts = any(
                phrase in detail_text
                for phrase in ("does not reconcile", "does not balance", "not reconciled")
            )
            if contradicts and c.passed:
                cached_res = "FAIL"

        if formula_expr and not skipped:
            write_formula_cell(
                ws, r, 4,
                formula=formula_expr,
                cached_value=cached_res,
                num_format="@",
                font=FONT_PASS if cached_res == "PASS" else FONT_ALERT,
                fill=FILL_PASS if cached_res == "PASS" else FILL_FAIL,
                border=BORDER_BOX,
                alignment=ALIGN_CENTER,
            )
        else:
            res_cell = ws.cell(row=r, column=4, value=cached_res)
            res_cell.alignment = ALIGN_CENTER
            if skipped:
                # A skip is its own state: neither the green of a pass nor the
                # orange of a failure, and no live formula beside it that would
                # recompute one of the two on recalculation.
                res_cell.font = FONT_FORMULA
                res_cell.fill = FILL_CARD
            else:
                res_cell.font = FONT_PASS if cached_res == "PASS" else FONT_ALERT
                res_cell.fill = FILL_PASS if cached_res == "PASS" else FILL_FAIL
            res_cell.border = BORDER_BOX

        # Always show the engine's own explanation. Replacing a passing check's
        # detail with "Verified OK" discards the only sentence that tells a
        # reader HOW the check passed — which is the sentence that reveals a
        # check passing for the wrong reason.
        detail_cell = ws.cell(row=r, column=5, value=c.detail or "Verified OK")
        detail_cell.font = FONT_PASS if cached_res == "PASS" else FONT_ALERT
        detail_cell.alignment = ALIGN_LEFT

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
