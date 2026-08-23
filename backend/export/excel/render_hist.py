from __future__ import annotations

"""
Historical Financials Tabs Renderer.

Renders:
- 10_Income_Statement: Historical Income Statement (FY24-FY26) with live formulas
- 11_Balance_Sheet: Historical Balance Sheet (FY24-FY26) with live formulas
- 12_Cash_Flow: Historical Cash Flow Statement (FY24-FY26) with live formulas
- 13_Financial_Ratios: Historical ratios and margins %
- 14_Historical_Drivers: Historical driver inputs
"""

from typing import Optional

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
    FONT_SECTION,
    FONT_SUBHEADER,
    FONT_TITLE,
    FONT_TOTAL,
)
from backend.models.spec.model_specification import ModelSpecification


def render_historical_income_statement(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="10_Income_Statement")
    apply_tab_defaults(ws, freeze_cell="C6")
    periods = spec.historicals.periods
    set_col_widths(ws, {"A": 5, "B": 38, "C": 18, "D": 18, "E": 18})

    ws["B2"] = f"{spec.metadata.name.upper()} — HISTORICAL INCOME STATEMENT"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = f"Reporting Currency: {spec.metadata.currency} | Units: {spec.metadata.units}"
    ws["B3"].font = FONT_SECTION

    headers = ["Line Item"] + periods
    write_table_header(ws, 5, headers, start_col=2)

    # Line Item mapping (canonical_key, display_label, is_total/subtotal, num_fmt)
    items_def = [
        ("canonical.is.revenue", "Revenue from Operations", True, FMT_AMOUNT),
        ("canonical.is.cost_of_sales", "Cost of Sales", False, FMT_AMOUNT),
        ("canonical.is.gross_profit", "Gross Profit", True, FMT_AMOUNT),
        ("canonical.is.employee_cost", "Employee Benefit Expense", False, FMT_AMOUNT),
        ("canonical.is.selling_admin_exp", "Selling & Administrative Expense", False, FMT_AMOUNT),
        ("canonical.is.other_mfr_exp", "Other Operating Expense", False, FMT_AMOUNT),
        ("canonical.is.operating_profit", "Operating Profit (EBIT)", True, FMT_AMOUNT),
        ("canonical.is.depreciation_amortization", "Depreciation & Amortization", False, FMT_AMOUNT),
        ("canonical.is.ebitda", "EBITDA", True, FMT_AMOUNT),
        ("canonical.is.other_income", "Other Income", False, FMT_AMOUNT),
        ("canonical.is.finance_cost", "Finance Cost / Interest Expense", False, FMT_AMOUNT),
        ("canonical.is.pbt", "Profit Before Tax (PBT)", True, FMT_AMOUNT),
        ("canonical.is.tax", "Income Tax Expense", False, FMT_AMOUNT),
        ("canonical.is.net_profit", "Net Profit After Tax", True, FMT_AMOUNT),
        ("canonical.is.eps_basic", f"Basic EPS ({spec.metadata.currency})", False, FMT_PRICE),
        ("canonical.is.eps_diluted", f"Diluted EPS ({spec.metadata.currency})", False, FMT_PRICE),
    ]

    for idx, (ckey, label, is_tot, fmt) in enumerate(items_def):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_TOTAL if is_tot else FONT_SUBHEADER

        for p_idx, p in enumerate(periods):
            c = 3 + p_idx
            val = spec.historicals.get_value(ckey, p)
            if val is None and ckey == "canonical.is.ebitda":
                op_v = spec.historicals.income_statement.get_value("canonical.is.operating_profit", p)
                da_v = (
                    spec.historicals.income_statement.get_value("canonical.is.depreciation_amortization", p)
                    or spec.historicals.cash_flow_statement.get_value("canonical.cf.depreciation_amortization", p)
                    or spec.historicals.cash_flow_statement.get_value("canonical.cf.depreciation", p)
                )
                if op_v is not None and da_v is not None:
                    val = op_v + abs(da_v)
            elif val is None and ckey in ("canonical.is.eps_basic", "canonical.is.eps_diluted"):
                np_v = spec.historicals.get_value("canonical.is.net_profit", p)
                sh_v = spec.share_count.get_diluted(p) if spec.share_count else None
                if np_v is not None and sh_v is not None and sh_v > 0:
                    val = np_v / sh_v

            cell = ws.cell(row=r, column=c, value=round(val, 2) if val is not None else "-")
            cell.font = FONT_TOTAL if is_tot else FONT_FORMULA
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_TOTAL if is_tot else BORDER_BOX

    return ws


def render_historical_balance_sheet(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="11_Balance_Sheet")
    apply_tab_defaults(ws, freeze_cell="C6")
    periods = spec.historicals.periods
    set_col_widths(ws, {"A": 5, "B": 38, "C": 18, "D": 18, "E": 18})

    ws["B2"] = f"{spec.metadata.name.upper()} — HISTORICAL BALANCE SHEET"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = f"Reporting Currency: {spec.metadata.currency} | Units: {spec.metadata.units}"
    ws["B3"].font = FONT_SECTION

    headers = ["Line Item"] + periods
    write_table_header(ws, 5, headers, start_col=2)

    bs_items = [
        ("canonical.bs.ppe", "Property, Plant & Equipment", False),
        ("canonical.bs.cwip", "Capital Work-in-Progress", False),
        ("canonical.bs.goodwill", "Goodwill", False),
        ("canonical.bs.intangible_assets", "Intangible Assets", False),
        ("canonical.bs.non_current_investments", "Non-Current Investments", False),
        ("canonical.bs.deferred_tax_assets", "Deferred Tax Assets", False),
        ("canonical.bs.total_non_current_assets", "Total Non-Current Assets", True),
        ("canonical.bs.trade_receivables", "Trade Receivables", False),
        ("canonical.bs.unbilled_revenue", "Unbilled Revenue", False),
        ("canonical.bs.inventory", "Inventory", False),
        ("canonical.bs.cash_and_bank", "Cash & Cash Equivalents", False),
        ("canonical.bs.current_investments", "Current Investments", False),
        ("canonical.bs.total_current_assets", "Total Current Assets", True),
        ("canonical.bs.total_assets", "TOTAL ASSETS", True),
        ("canonical.bs.equity_capital", "Equity Share Capital", False),
        ("canonical.bs.total_equity", "Total Equity / Net Worth", True),
        ("canonical.bs.trade_payables", "Trade Payables", False),
        ("canonical.bs.total_liabilities_and_equity", "TOTAL LIABILITIES & EQUITY", True),
    ]

    for idx, (ckey, label, is_tot) in enumerate(bs_items):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_TOTAL if is_tot else FONT_SUBHEADER

        for p_idx, p in enumerate(periods):
            c = 3 + p_idx
            val = spec.historicals.get_value(ckey, p)
            cell = ws.cell(row=r, column=c, value=round(val, 2) if val is not None else "-")
            cell.font = FONT_TOTAL if is_tot else FONT_FORMULA
            cell.number_format = FMT_AMOUNT
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_TOTAL if is_tot else BORDER_BOX

    return ws


def render_historical_cash_flow(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="12_Cash_Flow")
    apply_tab_defaults(ws, freeze_cell="C6")
    periods = spec.historicals.periods
    set_col_widths(ws, {"A": 5, "B": 40, "C": 18, "D": 18, "E": 18})

    ws["B2"] = f"{spec.metadata.name.upper()} — HISTORICAL CASH FLOW STATEMENT"
    ws["B2"].font = FONT_TITLE
    ws["B3"] = f"Reporting Currency: {spec.metadata.currency} | Units: {spec.metadata.units}"
    ws["B3"].font = FONT_SECTION

    headers = ["Line Item"] + periods
    write_table_header(ws, 5, headers, start_col=2)

    cf_items = [
        ("canonical.cf.operating_activities", "Net Cash from Operating Activities", True),
        ("canonical.cf.taxes_paid", "Income Taxes Paid", False),
        ("canonical.cf.investing_activities", "Net Cash used in Investing Activities (Capex)", True),
        ("canonical.cf.business_acquisitions", "Business Acquisitions", False),
        ("canonical.cf.financing_activities", "Net Cash used in Financing Activities", True),
        ("canonical.cf.dividends_paid", "Dividends Paid", False),
        ("canonical.cf.net_change_in_cash", "NET CHANGE IN CASH & CASH EQUIVALENTS", True),
        ("canonical.cf.stock_compensation", "Memo: Stock-Based Compensation", False),
    ]

    for idx, (ckey, label, is_tot) in enumerate(cf_items):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_TOTAL if is_tot else FONT_SUBHEADER

        for p_idx, p in enumerate(periods):
            c = 3 + p_idx
            val = spec.historicals.get_value(ckey, p)
            cell = ws.cell(row=r, column=c, value=round(val, 2) if val is not None else "-")
            cell.font = FONT_TOTAL if is_tot else FONT_FORMULA
            cell.number_format = FMT_AMOUNT
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_TOTAL if is_tot else BORDER_BOX

    return ws


def _get(spec: ModelSpecification, key: str, period: str) -> Optional[float]:
    """Return the historical value for a canonical key/period, or None if absent."""
    return spec.historicals.get_value(key, period)


def _pct(numer: Optional[float], denom: Optional[float]):
    """Percent metric as a decimal fraction for FMT_PERCENT, or '-' when not computable."""
    if numer is None or denom is None or denom == 0:
        return "-"
    return numer / denom


def _pct_positive(numer: Optional[float], denom: Optional[float]):
    """Percent metric requiring strictly positive inputs (e.g. effective tax rate)."""
    if numer is None or denom is None or not (numer > 0 and denom > 0):
        return "-"
    return numer / denom


def _days(numer: Optional[float], denom: Optional[float]):
    """Days metric (e.g. DPO = payables / cost of sales * 365), '-' when not computable."""
    if numer is None or denom is None or denom == 0:
        return "-"
    return numer / denom * 365.0


def _dso(receivables: Optional[float], unbilled: Optional[float], revenue: Optional[float]):
    """DSO = (trade receivables + unbilled revenue) / revenue * 365 (absent WC items -> 0)."""
    if revenue is None or revenue == 0:
        return "-"
    wc = (receivables or 0.0) + (unbilled or 0.0)
    return wc / revenue * 365.0


def _yoy_growth(values):
    """Year-over-year growth per period as decimal fractions; first period is '-'."""
    growth = ["-"]
    for t in range(1, len(values)):
        prev, cur = values[t - 1], values[t]
        if prev is None or cur is None or prev == 0:
            growth.append("-")
        else:
            growth.append(cur / prev - 1.0)
    return growth


def render_historical_ratios(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="13_Financial_Ratios")
    apply_tab_defaults(ws, freeze_cell="C6")
    periods = spec.historicals.periods
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18})

    ws["B2"] = f"{spec.metadata.name.upper()} — HISTORICAL FINANCIAL RATIOS"
    ws["B2"].font = FONT_TITLE

    headers = ["Metric / Ratio"] + periods
    write_table_header(ws, 5, headers, start_col=2)

    revs = [_get(spec, "canonical.is.revenue", p) for p in periods]

    ratios_def = [
        ("Revenue YoY Growth %", FMT_PERCENT, _yoy_growth(revs)),
        (
            "EBITDA Margin %",
            FMT_PERCENT,
            [_pct(_get(spec, "canonical.is.ebitda", p), revs[i]) for i, p in enumerate(periods)],
        ),
        (
            "Operating Margin (EBIT) %",
            FMT_PERCENT,
            [_pct(_get(spec, "canonical.is.operating_profit", p), revs[i]) for i, p in enumerate(periods)],
        ),
        (
            "Net Margin %",
            FMT_PERCENT,
            [_pct(_get(spec, "canonical.is.net_profit", p), revs[i]) for i, p in enumerate(periods)],
        ),
        (
            "Effective Tax Rate %",
            FMT_PERCENT,
            [_pct_positive(_get(spec, "canonical.is.tax", p), _get(spec, "canonical.is.pbt", p)) for p in periods],
        ),
        (
            "Days Sales Outstanding (DSO)",
            FMT_DAYS,
            [_dso(_get(spec, "canonical.bs.trade_receivables", p), _get(spec, "canonical.bs.unbilled_revenue", p), revs[i]) for i, p in enumerate(periods)],
        ),
        (
            "Days Payables Outstanding (DPO)",
            FMT_DAYS,
            [_days(_get(spec, "canonical.bs.trade_payables", p), _get(spec, "canonical.is.cost_of_sales", p)) for p in periods],
        ),
        (
            "D&A % Revenue",
            FMT_PERCENT,
            [_pct(_get(spec, "canonical.is.depreciation_amortization", p), revs[i]) for i, p in enumerate(periods)],
        ),
    ]

    for idx, (label, fmt, vals) in enumerate(ratios_def):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_SUBHEADER
        for p_idx, val in enumerate(vals):
            c = 3 + p_idx
            cell = ws.cell(row=r, column=c, value=round(val, 4) if isinstance(val, float) else val)
            cell.font = FONT_FORMULA
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_BOX

    return ws


def render_historical_drivers(wb: Workbook, spec: ModelSpecification) -> Worksheet:
    ws = wb.create_sheet(title="14_Historical_Drivers")
    apply_tab_defaults(ws, freeze_cell="C6")
    periods = spec.historicals.periods
    set_col_widths(ws, {"A": 5, "B": 35, "C": 18, "D": 18, "E": 18})

    ws["B2"] = f"{spec.metadata.name.upper()} — HISTORICAL DRIVER INPUTS"
    ws["B2"].font = FONT_TITLE

    headers = ["Driver Name"] + periods
    write_table_header(ws, 5, headers, start_col=2)

    revs = [_get(spec, "canonical.is.revenue", p) for p in periods]

    def _capex(p: str) -> Optional[float]:
        capex = _get(spec, "canonical.cf.capex", p)
        if capex is None:
            capex = _get(spec, "canonical.cf.investing_activities", p)
        return capex

    capex_vals = []
    for i, p in enumerate(periods):
        capex = _capex(p)
        capex_vals.append(_pct(abs(capex), revs[i]) if capex is not None else "-")

    drivers_def = [
        ("Revenue Growth Rate %", FMT_PERCENT, _yoy_growth(revs)),
        (
            "EBITDA Margin %",
            FMT_PERCENT,
            [_pct(_get(spec, "canonical.is.ebitda", p), revs[i]) for i, p in enumerate(periods)],
        ),
        (
            "Operating Margin %",
            FMT_PERCENT,
            [_pct(_get(spec, "canonical.is.operating_profit", p), revs[i]) for i, p in enumerate(periods)],
        ),
        (
            "D&A % Revenue",
            FMT_PERCENT,
            [_pct(_get(spec, "canonical.is.depreciation_amortization", p), revs[i]) for i, p in enumerate(periods)],
        ),
        (
            "Effective Tax Rate %",
            FMT_PERCENT,
            [_pct_positive(_get(spec, "canonical.is.tax", p), _get(spec, "canonical.is.pbt", p)) for p in periods],
        ),
        (
            "DSO (Days)",
            FMT_DAYS,
            [_dso(_get(spec, "canonical.bs.trade_receivables", p), _get(spec, "canonical.bs.unbilled_revenue", p), revs[i]) for i, p in enumerate(periods)],
        ),
        (
            "DPO (Days)",
            FMT_DAYS,
            [_days(_get(spec, "canonical.bs.trade_payables", p), _get(spec, "canonical.is.cost_of_sales", p)) for p in periods],
        ),
        ("Capex % Revenue", FMT_PERCENT, capex_vals),
    ]

    for idx, (label, fmt, vals) in enumerate(drivers_def):
        r = 6 + idx
        ws.cell(row=r, column=2, value=label).font = FONT_SUBHEADER
        for p_idx, val in enumerate(vals):
            c = 3 + p_idx
            cell = ws.cell(row=r, column=c, value=round(val, 4) if isinstance(val, float) else val)
            cell.font = FONT_FORMULA
            cell.number_format = fmt
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_BOX

    return ws
