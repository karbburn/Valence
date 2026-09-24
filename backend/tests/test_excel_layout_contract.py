"""Contract between rendered Excel layouts and every formula that references them.

These tests fail loudly when a renderer shifts a row/column that live formulas
in other tabs depend on — the class of silent breakage this suite exists to stop.
"""

from openpyxl import Workbook

from backend.export.excel.links import AUTHOR_URL, VALENCE_URL
from backend.export.excel.render_fcst import render_debt_schedule
from backend.export.excel.render_front import render_cover
from backend.export.excel.render_hist import (
    render_historical_balance_sheet,
    render_historical_cash_flow,
)
from backend.export.excel.render_qa import render_model_checks_tab
from backend.export.excel.render_val import render_sensitivity_tab
from backend.models.spec.historicals import HistoricalLineItem, Historicals
from backend.models.spec.metadata import ModelMetadata
from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import ModelCheckResult, QAResults

PERIODS = ["FY24", "FY25", "FY26"]


def _hist_line(key: str, value: float) -> HistoricalLineItem:
    return HistoricalLineItem(
        canonical_key=key,
        period_label=PERIODS[-1],
        period_end_date=__import__("datetime").date(2026, 3, 31),
        value=value,
        currency="INR",
        units="crores",
        status="reported",
        source_datapoint_ids=["fixture"],
        values_by_period={p: value for p in PERIODS},
    )


def _spec_with_historicals(bs_keys, cf_keys) -> ModelSpecification:
    lines = [_hist_line(k, 100.0) for k in bs_keys + cf_keys]
    return ModelSpecification(
        metadata=ModelMetadata(
            company_id="contract_in",
            ticker="CTRT",
            name="Contract Testco",
            market="india",
            currency="INR",
            units="crores",
            fiscal_year_end="March 31",
            shares_outstanding=10.0,
        ),
        historicals=Historicals(periods=PERIODS, line_items=lines),
    )


BS_KEYS = [
    "canonical.bs.ppe",
    "canonical.bs.cwip",
    "canonical.bs.goodwill",
    "canonical.bs.intangible_assets",
    "canonical.bs.non_current_investments",
    "canonical.bs.deferred_tax_assets",
    "canonical.bs.total_non_current_assets",
    "canonical.bs.trade_receivables",
    "canonical.bs.unbilled_revenue",
    "canonical.bs.inventory",
    "canonical.bs.cash_and_bank",
    "canonical.bs.current_investments",
    "canonical.bs.total_current_assets",
    "canonical.bs.total_assets",
    "canonical.bs.equity_capital",
    "canonical.bs.total_equity",
    "canonical.bs.trade_payables",
    "canonical.bs.total_liabilities_and_equity",
]

CF_KEYS = [
    "canonical.cf.operating_activities",
    "canonical.cf.taxes_paid",
    "canonical.cf.investing_activities",
    "canonical.cf.business_acquisitions",
    "canonical.cf.financing_activities",
    "canonical.cf.dividends_paid",
    "canonical.cf.other_adjustments",
    "canonical.cf.net_change_in_cash",
]


def _row_of(ws, label: str) -> int:
    for r in range(1, ws.max_row + 1):
        if str(ws.cell(row=r, column=2).value) == label:
            return r
    raise AssertionError(f"Label not found on sheet: {label}")


def test_cover_links_match_current_public_urls():
    ws = render_cover(Workbook(), _spec_with_historicals([], []))

    assert ws["B20"].value == "By Sourabh"
    assert ws["B20"].hyperlink is not None
    assert ws["B20"].hyperlink.target == AUTHOR_URL
    assert ws["B3"].hyperlink is not None
    assert ws["B3"].hyperlink.target == VALENCE_URL


def test_balance_sheet_layout_matches_formula_references():
    ws = render_historical_balance_sheet(Workbook(), _spec_with_historicals(BS_KEYS, []))
    assert _row_of(ws, "Trade Receivables") == 13
    assert _row_of(ws, "Unbilled Revenue") == 14
    assert _row_of(ws, "Inventory") == 15
    assert _row_of(ws, "Cash & Cash Equivalents") == 16
    assert _row_of(ws, "TOTAL ASSETS") == 19
    assert _row_of(ws, "TOTAL LIABILITIES & EQUITY") == 23


def test_cash_flow_layout_keeps_net_change_on_row_12():
    ws = render_historical_cash_flow(Workbook(), _spec_with_historicals([], CF_KEYS))
    assert _row_of(ws, "NET CHANGE IN CASH & CASH EQUIVALENTS") == 12
    assert _row_of(ws, "Memo: Stock-Based Compensation") == 13


def test_debt_schedule_rows_support_internal_reconciliation_formula():
    ws = render_debt_schedule(Workbook(), _spec_with_historicals([], []))
    assert _row_of(ws, "Opening Debt Balance (INR Cr)") == 6
    assert _row_of(ws, "Debt Drawdowns (INR Cr)") == 7
    assert _row_of(ws, "Scheduled Repayments (INR Cr)") == 8
    assert _row_of(ws, "Optional Repayments (INR Cr)") == 9
    closing_formula = ws.cell(row=10, column=3).value
    assert closing_formula == "=C6+C7-C8-C9"


def test_sensitivity_formulas_rediscount_the_full_fcff_stream():
    ws = render_sensitivity_tab(Workbook(), _spec_with_historicals([], []))

    growth_cell = ws.cell(row=6, column=3).value  # first WACC row x first growth col
    assert isinstance(growth_cell, str) and growth_cell.startswith("=IF(")
    for t in ("0.5", "1.5", "2.5", "3.5", "4.5"):
        assert f"(1+$B6)^{t}" in growth_cell, f"missing trial-WACC exponent {t}"
    assert "'31_DCF'!C12" in growth_cell and "'31_DCF'!G12/(1+$B6)^4.5" in growth_cell

    multiple_cell = ws.cell(row=14, column=3).value
    assert isinstance(multiple_cell, str) and multiple_cell.startswith("=(")
    assert "(1+$B14)^0.5" in multiple_cell and "'20_Operating_Model'!G9*C$13" in multiple_cell


def test_model_check_formulas_point_at_rendered_cells():
    spec = _spec_with_historicals(BS_KEYS, CF_KEYS)
    spec.qa = QAResults(
        checks=[
            ModelCheckResult(check_name="balance_sheet_balances", category="accounting", passed=True),
            ModelCheckResult(check_name="cash_flow_reconciles", category="accounting", passed=True),
            ModelCheckResult(check_name="debt_schedule_reconciles", category="accounting", passed=True),
        ]
    )
    ws = render_model_checks_tab(Workbook(), spec)

    formulas = {}
    for r in range(1, ws.max_row + 1):
        name = ws.cell(row=r, column=2).value
        val = ws.cell(row=r, column=4).value or ws.cell(row=r, column=5).value
        if isinstance(val, str) and val.startswith("=IF"):
            formulas[str(name)] = val

    bs_formula = formulas["balance_sheet_balances"]
    assert "'11_Balance_Sheet'!E19" in bs_formula and "'11_Balance_Sheet'!E23" in bs_formula

    cf_formula = formulas["cash_flow_reconciles"]
    assert "'12_Cash_Flow'!E12" in cf_formula
    assert "'11_Balance_Sheet'!E16" in cf_formula and "'11_Balance_Sheet'!D16" in cf_formula

    debt_formula = formulas["debt_schedule_reconciles"]
    for col in "CDEFG":
        assert f"'25_Debt_Schedule'!{col}10" in debt_formula
