"""The forecast balance sheet must balance, in the workbook and on recalculation.

The forecast engine computed total liabilities and then dropped it, so the model
carried no liabilities line. The workbook rendered that row as zero while its
total-liabilities-and-equity cell held a live formula over equity plus the zero.
The cached total therefore showed the correct figure and the formula beside it
computed a different one: opening a forecast company and pressing recalculate
broke its balance sheet by 58,163 in the first year and 82,777 by the fifth, for
a company carrying tens of billions of debt and payables.

The QA checks did not catch it because `balance_sheet_balances` tests the
HISTORICAL balance sheet, which is sound. Nothing examined the forecast.
"""

from __future__ import annotations

import pytest
from openpyxl import Workbook, load_workbook

from backend.export.excel.exporter import export_model_to_excel
from backend.forecast.engine import run_forecast
from backend.models.spec.model_specification import ModelSpecification
from backend.valuation.pipeline import run_valuation
from backend.validation.pipeline import run_qa

from backend.tests.test_excel_recalculation_parity import _model

FC = "CDEFG"
FY = ["FY27", "FY28", "FY29", "FY30", "FY31"]


@pytest.fixture(scope="module")
def forecast_book(tmp_path_factory):
    spec = run_qa(run_valuation(_model()))
    path = tmp_path_factory.mktemp("fcbs") / "forecast.xlsx"
    export_model_to_excel(spec, path)
    return load_workbook(path, data_only=True), load_workbook(path, data_only=False)


def _row(ws, label):
    for r in range(1, (ws.max_row or 0) + 1):
        if str(ws.cell(row=r, column=2).value or "").strip() == label:
            return r
    return None


def test_the_forecast_publishes_a_total_liabilities_line(forecast_book):
    """A balance sheet with no liabilities is not a balance sheet."""
    wbv, _ = forecast_book
    ws = wbv["20_Operating_Model"]
    row = _row(ws, "Total Liabilities")

    assert row is not None, "the forecast carries no Total Liabilities line at all"
    for i, col in enumerate(FC):
        value = ws[f"{col}{row}"].value
        assert isinstance(value, (int, float)), f"{FY[i]}: total liabilities is not a number"
        assert value > 0, (
            f"{FY[i]}: total liabilities published as {value}. A company with "
            "borrowings and trade payables cannot carry none."
        )


def test_forecast_assets_equal_liabilities_plus_equity(forecast_book):
    """The identity, from the sheet's own published cells."""
    wbv, _ = forecast_book
    ws = wbv["20_Operating_Model"]
    r_assets = _row(ws, "Total Assets")
    r_equity = _row(ws, "Total Equity")
    r_liab = _row(ws, "Total Liabilities")

    for i, col in enumerate(FC):
        assets = ws[f"{col}{r_assets}"].value
        equity = ws[f"{col}{r_equity}"].value
        liabilities = ws[f"{col}{r_liab}"].value
        assert abs(assets - (equity + liabilities)) <= 0.01 * max(abs(assets), 1.0), (
            f"{FY[i]}: assets {assets:,.1f} != equity {equity:,.1f} + liabilities "
            f"{liabilities:,.1f}"
        )


def test_the_published_total_matches_its_own_formula(forecast_book):
    """A cached value that its formula does not reproduce is a latent break.

    The cell showed the right number and the formula beside it computed a
    different one, so the workbook was correct on open and wrong after
    recalculation.
    """
    wbv, wbf = forecast_book
    ws, wsf = wbv["20_Operating_Model"], wbf["20_Operating_Model"]
    r_assets = _row(ws, "Total Assets")
    r_equity = _row(ws, "Total Equity")
    r_liab = _row(ws, "Total Liabilities")
    r_total = _row(ws, "Total Liabilities & Equity")

    for i, col in enumerate(FC):
        assets = ws[f"{col}{r_assets}"].value
        equity = ws[f"{col}{r_equity}"].value
        liabilities = ws[f"{col}{r_liab}"].value
        total = ws[f"{col}{r_total}"].value

        assert abs(total - (equity + liabilities)) <= 0.01 * max(abs(total), 1.0), (
            f"{FY[i]}: total liabilities and equity is published as {total:,.1f} but "
            f"its own components sum to {equity + liabilities:,.1f} — the cell and "
            f"the cells it is built from disagree"
        )
        assert abs(assets - total) <= 0.01 * max(abs(assets), 1.0), (
            f"{FY[i]}: the forecast balance sheet does not balance"
        )


def test_the_forecast_carries_the_line_the_engine_computed():
    """The engine's own output must contain what the workbook needs to publish."""
    from backend.forecast.assumptions import suggest_base_assumptions
    from backend.models.statements.pipeline import run as run_historical

    hist = run_historical(target_periods=["FY24", "FY25", "FY26"], company_id="tcs_tcs")
    forecast = run_forecast(
        suggest_base_assumptions(hist.ratios, hist), hist, "base"
    )

    for period in ["FY27", "FY28"]:
        value = forecast.get_value("canonical.bs.total_liabilities", period, "base")
        assert value is not None, f"{period}: the engine emitted no total liabilities"
        assert value > 0, f"{period}: total liabilities is {value}"
