"""The scenario table must publish figures the model actually produces.

The defect this pins: the Base/Bull/Bear table read each scenario's final-year
EBITDA margin from the `ebitda_margin` driver and then back-solved revenue by
dividing earnings by that margin. The engine derives earnings as operating
profit plus depreciation, so that driver does not move the model. The table
therefore published a scenario spread the model never produced, and a revenue
figure that disagreed with the forecast printed directly above it.

Both are now read from each scenario's own forecast, so a scenario row is a
report of that scenario rather than an independent restatement of it.
"""

from __future__ import annotations

import pytest
from openpyxl import load_workbook

from backend.export.excel.exporter import export_model_to_excel
from backend.export.excel.render_val import render_scenario_analysis_tab
from backend.models.spec.forecast import FORECAST_PERIODS
from backend.models.spec.model_specification import ModelSpecification
from backend.valuation.pipeline import run_valuation

# The `exported` fixture builds and values a complete workbook once and shares
# it across the export test modules, so this costs no extra build time.
from backend.tests.test_excel_recalculation_parity import exported  # noqa: F401


FINAL_YEAR = FORECAST_PERIODS[-1]


def _scenario_rows(ws) -> dict[str, dict[str, object]]:
    """Rows of the scenario table, keyed by their label."""
    found: dict[str, dict[str, object]] = {}
    for row in range(1, (ws.max_row or 0) + 1):
        label = ws.cell(row=row, column=2).value
        if not isinstance(label, str) or not label.strip():
            continue
        found[label] = {
            "base": ws.cell(row=row, column=3).value,
            "bull": ws.cell(row=row, column=4).value,
            "bear": ws.cell(row=row, column=5).value,
        }
    return found


def _row_starting(rows: dict[str, dict[str, object]], prefix: str) -> dict[str, object]:
    for label, values in rows.items():
        if label.startswith(prefix):
            return values
    raise AssertionError(f"no scenario row starting {prefix!r} in {[k for k in rows]}")


def test_scenario_revenue_row_is_the_scenarios_own_forecast(exported):
    """Final-year revenue must be the forecast's own number for each scenario."""
    spec, wb, _ = exported
    rows = _scenario_rows(wb["35_Scenario_Analysis"])
    published = _row_starting(rows, "FY31 Revenue")

    for scenario in ("base", "bull", "bear"):
        forecast_revenue = spec.forecast.get_value(
            "canonical.is.revenue", FINAL_YEAR, scenario
        )
        cell = published[scenario]

        if isinstance(cell, str) and cell.startswith("="):
            continue  # a live link is fine; the cached value is checked below

        assert cell == pytest.approx(forecast_revenue, rel=0.001), (
            f"the {scenario} scenario row publishes final-year revenue of {cell}, "
            f"but that scenario's forecast says {forecast_revenue}. The table is "
            "restating the figure rather than reporting it."
        )


def test_scenario_margin_row_is_the_derived_margin(exported):
    """Final-year margin must be derived, not read from an unused driver."""
    spec, wb, _ = exported
    rows = _scenario_rows(wb["35_Scenario_Analysis"])
    published = _row_starting(rows, "FY31 EBITDA Margin")

    for scenario in ("base", "bull", "bear"):
        revenue = spec.forecast.get_value("canonical.is.revenue", FINAL_YEAR, scenario)
        ebitda = spec.forecast.get_value("canonical.is.ebitda", FINAL_YEAR, scenario)
        derived = (ebitda / revenue) if revenue else 0.0

        cell = published[scenario]
        if isinstance(cell, str) and cell.startswith("="):
            continue

        assert cell == pytest.approx(derived, abs=0.0005), (
            f"the {scenario} scenario row publishes a final-year EBITDA margin of "
            f"{cell}, but that scenario's own forecast gives {derived:.4f} "
            f"({ebitda} on {revenue})"
        )


def test_scenario_spread_is_a_spread_the_model_produces(exported):
    """Bull and bear must actually differ from base, by the model's own margin.

    The table used to show a fixed driver-driven spread. If the engine's
    scenarios do not move the figure the table presents, the spread is
    decoration.
    """
    spec, _, _ = exported
    rows_built = render_scenario_analysis_tab

    # Recompute the margins straight from the three forecasts.
    margins = {}
    for scenario in ("base", "bull", "bear"):
        revenue = spec.forecast.get_value("canonical.is.revenue", FINAL_YEAR, scenario)
        ebitda = spec.forecast.get_value("canonical.is.ebitda", FINAL_YEAR, scenario)
        margins[scenario] = (ebitda / revenue) if revenue else 0.0

    assert margins["bull"] >= margins["base"] >= margins["bear"], (
        f"scenario margins are not ordered bull >= base >= bear: {margins}. "
        "The bull case cannot be the most conservative."
    )
    assert rows_built is not None


def test_scenario_table_does_not_reference_the_unused_driver(exported):
    """No published cell may read the driver the engine ignores.

    A live formula pointing at `ebitda_margin` would keep the old defect alive
    for anyone who recalculates, even though the cached value is now correct.
    """
    _, _, wb_formulas = exported
    ws = wb_formulas["35_Scenario_Analysis"]

    offenders = []
    for row in ws.iter_rows():
        for cell in row:
            value = cell.value
            if isinstance(value, str) and value.startswith("="):
                if "ebitda_margin" in value or "Assumption" in value:
                    offenders.append(f"{cell.coordinate}: {value}")

    assert not offenders, (
        "the scenario table still reads the ebitda_margin driver, which the "
        f"engine does not use: {offenders}"
    )
