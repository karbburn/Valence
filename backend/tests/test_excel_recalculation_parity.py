"""The exported workbook must recalculate to the engine's own numbers.

A reader who opens the .xlsx and presses Ctrl+Alt+F9 should see the figures the
model published — not a different set. These tests rebuild the chain from each
workbook's own cells (NOPAT, FCFF, the bridge, working capital) and compare
against the engine.

The defects these pin:
  - 31_DCF's change-in-working-capital row built its level inline as
    (receivables - payables), dropping inventory, AND changed definition
    between year 1 and years 2-5. Recalculating moved the implied share price
    +27% (NVDA) to +57% (AWI) away from the published number.
  - 20_Operating_Model's finance cost was a live link to the debt schedule
    while the engine holds it flat at the last actual, so PBT, tax and net
    profit all silently changed on recalculation for every company.
  - 22_Cost_Build drove EBITDA and EBIT from two independent margins, so
    EBITDA - D&A did not equal EBIT and the income statement did not foot.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from backend.export.excel.exporter import export_model_to_excel
from backend.export.excel.render_fcst import (
    OPERATING_MODEL_ROW_OFFSET,
    OPERATING_MODEL_ROWS,
    render_operating_model,
    render_working_capital,
)
from backend.export.excel.render_val import render_dcf_tab
from backend.models.spec.forecast import FORECAST_PERIODS, Forecast, ForecastLineItem
from backend.models.spec.historicals import Historicals
from backend.models.spec.metadata import ModelMetadata
from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.valuation import ValuationOutput, WACCBreakdown
from backend.valuation.pipeline import run_valuation

COLS = "CDEFG"


def _model(**overrides) -> ModelSpecification:
    """A small, self-consistent model with inventory so DIO is exercised."""
    periods = ["FY24", "FY25", "FY26"]
    spec = ModelSpecification(
        metadata=ModelMetadata(
            company_id="recalc_us",
            ticker="RCL",
            name="Recalc Testco",
            market="us",
            currency="USD",
            units="millions",
            fiscal_year_end="December 31",
            shares_outstanding=100.0,
        ),
        historicals=Historicals(periods=periods, line_items=[]),
    )
    items: list[ForecastLineItem] = []

    def add(key, series, driver=None):
        for p, v in zip(FORECAST_PERIODS, series):
            items.append(
                ForecastLineItem(
                    canonical_key=key,
                    period_label=p,
                    period_end_date=__import__("datetime").date(2027, 12, 31),
                    value=v,
                    scenario="base",
                    driver_key=driver,
                )
            )

    add("canonical.is.revenue", [1000.0, 1100.0, 1200.0, 1300.0, 1400.0], "revenue_growth")
    add("canonical.is.ebitda", [300.0, 330.0, 360.0, 390.0, 420.0], "ebit_margin")
    add("canonical.is.operating_profit", [270.0, 297.0, 324.0, 351.0, 378.0], "ebit_margin")
    add("canonical.is.depreciation_amortization", [30.0, 33.0, 36.0, 39.0, 42.0], "da_pct_revenue")
    add("canonical.is.cost_of_sales", [600.0, 660.0, 720.0, 780.0, 840.0])
    add("canonical.is.gross_profit", [400.0, 440.0, 480.0, 520.0, 560.0])
    add("canonical.is.other_income", [0.0] * 5)
    add("canonical.is.finance_cost", [20.0] * 5)
    add("canonical.is.pbt", [250.0, 277.0, 304.0, 331.0, 358.0])
    add("canonical.is.tax", [50.0, 55.4, 60.8, 66.2, 71.6], "tax_rate")
    add("canonical.is.net_profit", [200.0, 221.6, 243.2, 264.8, 286.4])
    add("canonical.bs.trade_receivables", [150.0, 165.0, 180.0, 195.0, 210.0], "dso_days")
    add("canonical.bs.inventory", [80.0, 88.0, 96.0, 104.0, 112.0], "dio_days")
    add("canonical.bs.trade_payables", [40.0, 44.0, 48.0, 52.0, 56.0], "dpo_days")
    add("canonical.bs.ppe", [200.0, 210.0, 220.0, 230.0, 240.0])
    add("canonical.bs.cash_and_bank", [300.0, 320.0, 340.0, 360.0, 380.0])
    add("canonical.bs.total_equity", [500.0, 560.0, 620.0, 680.0, 740.0])
    add("canonical.bs.total_assets", [900.0, 980.0, 1060.0, 1140.0, 1220.0])
    add("canonical.bs.total_liabilities", [400.0, 420.0, 440.0, 460.0, 480.0])
    add("canonical.bs.total_liabilities_and_equity", [900.0, 980.0, 1060.0, 1140.0, 1220.0])
    add("canonical.cf.capex", [-50.0, -55.0, -60.0, -65.0, -70.0], "capex_pct_revenue")
    add("canonical.cf.investing_activities", [-50.0, -55.0, -60.0, -65.0, -70.0])
    add("canonical.cf.delta_working_capital", [30.0, 27.0, 27.0, 27.0, 27.0])
    add("canonical.cf.operating_activities", [200.0, 227.6, 252.2, 276.8, 301.4])
    add("canonical.cf.dividends_paid", [-40.0, -44.3, -48.6, -53.0, -57.3])
    add("canonical.cf.financing_activities", [-40.0, -44.3, -48.6, -53.0, -57.3])

    spec.forecast = Forecast(line_items=items)
    spec.valuation = [
        ValuationOutput(
            scenario=sc,
            wacc=WACCBreakdown(
                risk_free_rate=5.0, beta=1.0, equity_risk_premium=4.5,
                cost_of_equity=9.5, pre_tax_cost_of_debt=7.5, tax_rate=20.0,
                cost_of_debt=6.0, equity_weight=0.95, debt_weight=0.05, wacc=9.325,
            ),
        )
        for sc in ("base", "bull", "bear")
    ]
    for key, value in overrides.items():
        setattr(spec, key, value)
    return spec


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    """Export once; return the spec, a value view and a formula view."""
    spec = run_valuation(_model())
    path = tmp_path_factory.mktemp("xlsx") / "recalc.xlsx"
    export_model_to_excel(spec, path)
    return spec, load_workbook(path, data_only=True), load_workbook(path, data_only=False)


def _cell(wb, sheet, coord):
    v = wb[sheet][coord].value
    return float(v) if isinstance(v, (int, float)) else None


def test_working_capital_level_matches_the_engine(exported):
    """NWC = receivables + inventory - payables, on the tab and in the model."""
    spec, wb, _ = exported
    wc = wb["23_Working_Capital"]
    for i, col in enumerate(COLS):
        period = FORECAST_PERIODS[i]
        level = _cell(wb, "23_Working_Capital", f"{col}12")
        if level is None:
            level = (
                (_cell(wb, "23_Working_Capital", f"{col}7") or 0)
                + (_cell(wb, "23_Working_Capital", f"{col}11") or 0)
                - (_cell(wb, "23_Working_Capital", f"{col}9") or 0)
            )
        engine = (
            spec.forecast.get_value("canonical.bs.trade_receivables", period, "base")
            + spec.forecast.get_value("canonical.bs.inventory", period, "base")
            - spec.forecast.get_value("canonical.bs.trade_payables", period, "base")
        )
        assert level == pytest.approx(engine, abs=0.05), f"{period} NWC level"

    # The tab must actually carry an inventory row, or the DCF level
    # difference cannot express the engine's definition.
    assert wc["B10"].value and "DIO" in str(wc["B10"].value)
    assert wc["B11"].value and "Inventory" in str(wc["B11"].value)


def test_fcff_rebuilds_from_the_workbook_cells(exported):
    """NOPAT and FCFF must recompute to the engine's figures from sheet cells."""
    spec, wb, _ = exported
    base = spec.get_valuation("base")
    for i, col in enumerate(COLS):
        ebit = _cell(wb, "31_DCF", f"{col}6")
        tax_dec = _cell(wb, "31_DCF", f"{col}7")
        nopat = _cell(wb, "31_DCF", f"{col}8")
        da = _cell(wb, "31_DCF", f"{col}9")
        capex = _cell(wb, "31_DCF", f"{col}10")
        dwc = _cell(wb, "31_DCF", f"{col}11")
        sbc = _cell(wb, "31_DCF", f"{col}15") or 0.0
        period = FORECAST_PERIODS[i]
        engine = base.fcff_by_period[i]

        assert nopat == pytest.approx(ebit * (1 - tax_dec), abs=0.05), f"{period} NOPAT identity"
        assert nopat == pytest.approx(engine.nopat, abs=0.05), f"{period} NOPAT vs engine"
        assert (nopat + da - capex - dwc - sbc) == pytest.approx(engine.fcff, abs=0.05), (
            f"{period} FCFF vs engine — the working-capital row in the workbook "
            f"({dwc}) disagrees with the engine ({engine.delta_working_capital})"
        )


def test_bridge_recalculates_to_the_published_price(exported):
    spec, wb, _ = exported
    bridge = spec.get_valuation("base").dcf_bridge
    ev = (_cell(wb, "31_DCF", "H17") or 0) + (_cell(wb, "31_DCF", "H18") or 0)
    equity = (_cell(wb, "31_DCF", "H19") or 0) - (_cell(wb, "31_DCF", "H25") or 0)
    price = equity / (_cell(wb, "31_DCF", "H27") or 1)

    assert ev == pytest.approx(bridge.enterprise_value, rel=0.001)
    assert equity == pytest.approx(bridge.equity_value, rel=0.001)
    assert price == pytest.approx(bridge.implied_share_price, abs=0.02)


def test_finance_cost_is_not_a_contradicting_formula(exported):
    """Finance cost must be a literal, not a link that recomputes another number."""
    _, _, wb_formulas = exported
    om = wb_formulas["20_Operating_Model"]
    for i, col in enumerate(COLS):
        cell = om[f"{col}13"]
        assert not (isinstance(cell.value, str) and cell.value.startswith("=")), (
            f"finance cost {FORECAST_PERIODS[i]} is a live formula; the engine holds it "
            "flat at the last historical actual, so the link recomputes a different number"
        )


def test_income_statement_foots(exported):
    """EBITDA - D&A must equal EBIT in the workbook, as it does in the engine."""
    _, wb, _ = exported
    for i, col in enumerate(COLS):
        ebitda = _cell(wb, "20_Operating_Model", f"{col}9")
        da = _cell(wb, "20_Operating_Model", f"{col}10")
        ebit = _cell(wb, "20_Operating_Model", f"{col}11")
        assert ebitda - da == pytest.approx(ebit, abs=0.05), (
            f"{FORECAST_PERIODS[i]}: EBITDA - D&A != EBIT"
        )


def test_executive_summary_is_live_not_a_dead_end(exported):
    """02_Executive_Summary must resolve to the DCF chain, not to static literals.

    It used to point at 35_Scenario_Analysis, which contained no formulas at
    all, so editing the DCF moved nothing on the summary page and any error
    inside 31_DCF stayed invisible.
    """
    _, _, wb_formulas = exported
    summary = wb_formulas["02_Executive_Summary"]
    assert str(summary["C6"].value or "").startswith("="), (
        "Executive Summary base price must be a live formula"
    )
    scenario = wb_formulas["35_Scenario_Analysis"]
    live = [
        scenario[f"C{r}"].value
        for r in range(6, 15)
        if isinstance(scenario[f"C{r}"].value, str) and str(scenario[f"C{r}"].value).startswith("=")
    ]
    assert len(live) >= 6, (
        f"35_Scenario_Analysis base column must be live, found {len(live)} formula cells"
    )


# ---------------------------------------------------------------------------
# Cross-sheet references must point at the LINE they claim to read.
#
# Row numbers on 20_Operating_Model used to be written as literals inside
# formulas on other tabs. Inserting a line then silently re-pointed them at
# whatever moved into the vacated row: the capex line began reading operating
# cash flow, and the balance-sheet total began reading the cash line. Nothing
# on the page showed it — the cached values were right, so the error only
# appeared when a reader pressed recalculate.
#
# These tests resolve each cross-sheet reference and assert the target row's
# own LABEL says it is the quantity the formula claims, which is the only
# check that survives a row being inserted.
# ---------------------------------------------------------------------------

_REF = re.compile(r"'([^']+)'!\$?([A-Z]+)\$?(\d+)")


def _referenced_row_label(wb, formula: str) -> tuple[str, str]:
    """Label of the row a cross-sheet reference points at."""
    match = _REF.search(formula or "")
    assert match, f"expected a cross-sheet reference in {formula!r}"
    sheet, _col, row = match.group(1), match.group(2), int(match.group(3))
    label = wb[sheet].cell(row=row, column=2).value
    return sheet, str(label or "")


def test_dcf_capex_row_references_the_capex_schedule(exported):
    _, wb, wb_formulas = exported
    for col in COLS:
        formula = wb_formulas["31_DCF"][f"{col}10"].value
        sheet, label = _referenced_row_label(wb, formula)
        assert "capex" in label.lower(), (
            f"31_DCF capex row points at {sheet} row labelled {label!r}; it must "
            "reference a capital expenditure line, not a cash flow line"
        )


def test_dcf_ebit_and_da_rows_reference_the_right_lines(exported):
    _, wb, wb_formulas = exported
    expectations = {
        "6": ("operating profit", "EBIT"),
        "9": ("depreciation", "D&A"),
    }
    for row, needles in expectations.items():
        formula = wb_formulas["31_DCF"][f"C{row}"].value
        _sheet, label = _referenced_row_label(wb, formula)
        assert any(n.lower() in label.lower() for n in needles), (
            f"31_DCF row {row} references a row labelled {label!r}, expected one of {needles}"
        )


def test_terminal_value_references_the_right_lines(exported):
    """Gordon growth takes final-year FCFF; the exit multiple takes EBITDA.

    Both are cross-sheet references on the same tab, and a row index drifting on
    either one silently substitutes a different terminal value.
    """
    _, wb, wb_formulas = exported
    sheet, label = _referenced_row_label(wb, wb_formulas["32_Terminal_Value"]["C7"].value)
    assert sheet == "31_DCF" and "fcff" in label.lower(), (
        f"terminal value's Gordon input references {sheet} {label!r}, expected final-year FCFF"
    )
    _sheet, label = _referenced_row_label(wb, wb_formulas["32_Terminal_Value"]["C10"].value)
    assert "ebitda" in label.lower(), (
        f"terminal value's exit-multiple input references {label!r}, expected an EBITDA line"
    )


def test_total_liabilities_and_equity_is_equity_plus_liabilities(exported):
    """The identity must be checkable, so liabilities have to be on the tab.

    Written as a copy of total assets, the balance can never fail, which makes
    the check that uses it meaningless.
    """
    _, wb, _ = exported
    om = wb["20_Operating_Model"]
    labels = {str(om.cell(row=r, column=2).value or "").lower(): r for r in range(6, 30)}

    equity_row = next((r for lbl, r in labels.items() if lbl.startswith("total equity")), None)
    liab_row = next((r for lbl, r in labels.items() if lbl.startswith("total liabilities") and "equity" not in lbl), None)
    le_row = next((r for lbl, r in labels.items() if lbl.startswith("total liabilities & equity")), None)
    assets_row = next((r for lbl, r in labels.items() if lbl == "total assets"), None)

    assert equity_row, "total equity must be on the operating model tab"
    assert liab_row, "total liabilities must be on the operating model tab, or the balance cannot be checked"
    assert le_row, "total liabilities and equity must be on the operating model tab"

    for col in COLS:
        equity = _cell(wb, "20_Operating_Model", f"{col}{equity_row}") or 0.0
        liab = _cell(wb, "20_Operating_Model", f"{col}{liab_row}") or 0.0
        total = _cell(wb, "20_Operating_Model", f"{col}{le_row}") or 0.0
        assert total == pytest.approx(equity + liab, abs=0.05), (
            f"{col}: total liabilities and equity {total} != equity {equity} + liabilities {liab}"
        )
    if assets_row:
        for col in COLS:
            assets = _cell(wb, "20_Operating_Model", f"{col}{assets_row}") or 0.0
            le = _cell(wb, "20_Operating_Model", f"{col}{le_row}") or 0.0
            assert abs(assets - le) <= 0.01 * max(abs(assets), 1.0), (
                f"{col}: the forecast balance sheet does not balance "
                f"(assets {assets} vs liabilities and equity {le})"
            )


def test_operating_model_row_map_covers_every_rendered_line(exported):
    """The shared row map must not drift from what the tab actually renders.

    A map that lists a line the tab no longer draws, or misses one it does, is
    how a formula ends up pointing at the wrong row with no error raised.
    """
    _, _, wb_formulas = exported
    om = wb_formulas["20_Operating_Model"]
    rendered = {
        str(om.cell(row=row, column=2).value or "").strip()
        for row in range(OPERATING_MODEL_ROW_OFFSET, OPERATING_MODEL_ROW_OFFSET + len(OPERATING_MODEL_ROWS))
    }
    assert len(rendered) == len(OPERATING_MODEL_ROWS), (
        "the operating model's line list and the shared row map disagree on length"
    )
    for key, row in OPERATING_MODEL_ROWS.items():
        assert str(om.cell(row=row, column=2).value or "").strip(), (
            f"{key} is mapped to row {row} but that row carries no label"
        )
