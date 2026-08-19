from __future__ import annotations

"""
Sensitivity Analysis module.

Generates 2D grid sensitivity tables by re-running the DCF engine at every grid point.
Values are calculated directly — no interpolation or approximation.
"""

from typing import List, Optional

from backend.forecast.debt import DebtSchedule
from backend.forecast.share_count import ShareCountSchedule
from backend.models.spec.forecast import FORECAST_PERIODS, Forecast
from backend.models.spec.valuation import (
    SensitivityTable,
    WACCBreakdown,
)

# Fallback used only if WACC is genuinely absent; keeps sensitivity grids computable.
FALLBACK_SENSITIVITY_WACC = 13.0


def compute_sensitivity_tables(
    forecast: Forecast,
    wacc_breakdown: WACCBreakdown,
    cash_cr: float,
    debt_cr: float,
    shares_cr: float,
    marketable_securities_cr: float = 0.0,
    non_current_investments_cr: float = 0.0,
    minority_interest_cr: float = 0.0,
    preferred_stock_cr: float = 0.0,
    scenario: str = "base",
    base_g: float = 4.0,
    base_exit_mult: float = 20.0,
    terminal_tax_rate: Optional[float] = None,
    timing_convention: str = "mid_year",
) -> List[SensitivityTable]:
    """Generate two-variable sensitivity grids for WACC x Terminal Growth & WACC x Exit Multiple."""
    from backend.valuation.dcf import (
        compute_dcf_bridge,
        compute_fcff_periods,
        compute_terminal_value,
    )

    base_wacc = wacc_breakdown.wacc if (wacc_breakdown.wacc is not None and wacc_breakdown.wacc != 0) else FALLBACK_SENSITIVITY_WACC

    # Grid 1: WACC vs Terminal Growth
    wacc_steps = [
        round(base_wacc - 2.0, 2),
        round(base_wacc - 1.0, 2),
        round(base_wacc, 2),
        round(base_wacc + 1.0, 2),
        round(base_wacc + 2.0, 2),
    ]
    g_steps = [
        round(max(0.5, base_g - 1.0), 2),
        round(max(1.0, base_g - 0.5), 2),
        round(base_g, 2),
        round(base_g + 0.5, 2),
        round(base_g + 1.0, 2),
    ]

    grid1: List[List[Optional[float]]] = []
    for w in wacc_steps:
        row: List[Optional[float]] = []
        fcffs = compute_fcff_periods(forecast, w, scenario, timing_convention=timing_convention)  # type: ignore
        last_fcff = fcffs[-1].fcff if fcffs and fcffs[-1].fcff else 0.0
        last_ebitda = forecast.get_value("canonical.is.ebitda", FORECAST_PERIODS[-1], scenario) or 0.0

        for g in g_steps:
            if g >= w:
                row.append(None)
            else:
                tv = compute_terminal_value(
                    last_fcff,
                    last_ebitda,
                    w,
                    g,
                    base_exit_mult,
                    "gordon_growth",
                    terminal_tax_rate=terminal_tax_rate,
                    timing_convention=timing_convention,  # type: ignore
                )
                bridge, _ = compute_dcf_bridge(
                    fcffs,
                    tv,
                    cash_cr=cash_cr,
                    debt_cr=debt_cr,
                    shares_cr=shares_cr,
                    marketable_securities_cr=marketable_securities_cr,
                    non_current_investments_cr=non_current_investments_cr,
                    minority_interest_cr=minority_interest_cr,
                    preferred_stock_cr=preferred_stock_cr,
                )
                row.append(bridge.implied_share_price)
        grid1.append(row)

    table1 = SensitivityTable(
        row_driver="wacc.wacc",
        col_driver="terminal_growth_rate",
        row_values=wacc_steps,
        col_values=g_steps,
        results_grid=grid1,
    )

    # Grid 2: WACC vs Exit Multiple
    mult_steps = [
        round(max(5.0, base_exit_mult - 4.0), 1),
        round(max(5.0, base_exit_mult - 2.0), 1),
        round(base_exit_mult, 1),
        round(base_exit_mult + 2.0, 1),
        round(base_exit_mult + 4.0, 1),
    ]

    grid2: List[List[Optional[float]]] = []
    for w in wacc_steps:
        row: List[Optional[float]] = []
        fcffs = compute_fcff_periods(forecast, w, scenario, timing_convention=timing_convention)  # type: ignore
        last_fcff = fcffs[-1].fcff if fcffs and fcffs[-1].fcff else 0.0
        last_ebitda = forecast.get_value("canonical.is.ebitda", FORECAST_PERIODS[-1], scenario) or 0.0

        for m in mult_steps:
            tv = compute_terminal_value(
                last_fcff,
                last_ebitda,
                w,
                base_g,
                m,
                "exit_multiple",
                terminal_tax_rate=terminal_tax_rate,
                timing_convention=timing_convention,  # type: ignore
            )
            bridge, _ = compute_dcf_bridge(
                fcffs,
                tv,
                cash_cr=cash_cr,
                debt_cr=debt_cr,
                shares_cr=shares_cr,
                marketable_securities_cr=marketable_securities_cr,
                non_current_investments_cr=non_current_investments_cr,
                minority_interest_cr=minority_interest_cr,
                preferred_stock_cr=preferred_stock_cr,
            )
            row.append(bridge.implied_share_price)
        grid2.append(row)

    table2 = SensitivityTable(
        row_driver="wacc.wacc",
        col_driver="exit_ev_multiple",
        row_values=wacc_steps,
        col_values=mult_steps,
        results_grid=grid2,
    )

    return [table1, table2]
