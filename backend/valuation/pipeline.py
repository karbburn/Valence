from __future__ import annotations

"""
Valuation Pipeline Module.

Orchestrates WACC, FCFF/DCF, Terminal Value, DCF Bridge, Reverse DCF, and Sensitivity Analysis
across all scenarios (base, bull, bear) and populates spec.valuation.
"""

from typing import List, Optional

from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.valuation import ValuationOutput
from backend.valuation.dcf import (
    compute_dcf_bridge,
    compute_fcff_periods,
    compute_terminal_value,
)
from backend.valuation.reverse_dcf import compute_reverse_dcf
from backend.valuation.sensitivity import compute_sensitivity_tables
from backend.valuation.wacc import DEFAULT_CURRENT_PRICE, compute_wacc


def run_valuation(
    spec: ModelSpecification,
    current_share_price: float = DEFAULT_CURRENT_PRICE,
) -> ModelSpecification:
    """Run full valuation engine across all scenarios and populate spec.valuation."""
    valuation_outputs: List[ValuationOutput] = []

    # Sourced cash from latest historicals (FY26)
    cash_cr = spec.historicals.get_value("canonical.bs.cash_and_bank", "FY26") or 22201.0

    # Sourced diluted share count
    shares_cr = 412.4545
    if spec.share_count:
        val = spec.share_count.get_diluted("FY26") or spec.share_count.get_diluted("FY27")
        if val:
            shares_cr = val

    for scenario in ["base", "bull", "bear"]:
        # Find debt schedule for scenario
        ds = next((d for d in spec.debt_schedule if d.scenario == scenario), None)
        debt_cr = ds.closing("FY26") if ds else 0.0

        # 1. Compute WACC Breakdown
        wacc_breakdown = compute_wacc(
            assumptions=spec.assumptions,
            debt_schedule=ds,
            share_count_schedule=spec.share_count,
            scenario=scenario,
            current_share_price=current_share_price,
        )
        wacc_pct = wacc_breakdown.wacc or 12.95

        # 2. Compute FCFF Periods
        fcff_periods = compute_fcff_periods(spec.forecast, wacc_pct, scenario)

        # 3. Compute Terminal Value (Gordon Growth default)
        last_fcff = fcff_periods[-1].fcff if fcff_periods and fcff_periods[-1].fcff else 0.0
        last_ebitda = spec.forecast.get_value("canonical.is.ebitda", "FY31", scenario) or 0.0

        # Drivers for terminal value
        term_g = 4.0
        exit_mult = 20.0
        for a in spec.assumptions:
            if a.driver_key == "terminal_growth_rate" and a.scenario == scenario:
                term_g = a.value
            elif a.driver_key == "exit_ev_multiple" and a.scenario == scenario:
                exit_mult = a.value

        terminal_val = compute_terminal_value(
            last_fcff=last_fcff,
            last_ebitda=last_ebitda,
            wacc_pct=wacc_pct,
            terminal_growth_rate=term_g,
            exit_multiple=exit_mult,
            active_method="gordon_growth",
        )

        # 4. DCF Bridge (EV -> Equity Value -> Implied Share Price)
        dcf_bridge, updated_tv = compute_dcf_bridge(
            fcff_periods=fcff_periods,
            terminal_value=terminal_val,
            cash_cr=cash_cr,
            debt_cr=debt_cr,
            shares_cr=shares_cr,
        )

        # 5. Reverse DCF
        reverse_dcf = compute_reverse_dcf(
            market_price=current_share_price,
            fcff_periods=fcff_periods,
            wacc_pct=wacc_pct,
            cash_cr=cash_cr,
            debt_cr=debt_cr,
            shares_cr=shares_cr,
        )

        # 6. Sensitivity Analysis Grids
        sensitivity_tables = compute_sensitivity_tables(
            forecast=spec.forecast,
            wacc_breakdown=wacc_breakdown,
            cash_cr=cash_cr,
            debt_cr=debt_cr,
            shares_cr=shares_cr,
            scenario=scenario,
            base_g=term_g,
            base_exit_mult=exit_mult,
        )

        valuation_outputs.append(
            ValuationOutput(
                scenario=scenario,  # type: ignore
                wacc=wacc_breakdown,
                fcff_by_period=fcff_periods,
                terminal_value=updated_tv,
                dcf_bridge=dcf_bridge,
                reverse_dcf=reverse_dcf,
                sensitivity_tables=sensitivity_tables,
            )
        )

    spec.valuation = valuation_outputs
    return spec
