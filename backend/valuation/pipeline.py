from __future__ import annotations

"""
Valuation Pipeline Module.

Orchestrates WACC, FCFF/DCF, Terminal Value, DCF Bridge, Reverse DCF, and Sensitivity Analysis
across all scenarios (base, bull, bear) and populates spec.valuation.
Market-aware and free of Infosys-specific share/cash constant fallbacks.
"""

from typing import List, Optional

from backend.data.providers.market_data import get_company_market_data
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
    current_share_price: Optional[float] = None,
    historical_model=None,
) -> ModelSpecification:
    """Run full valuation engine across all scenarios and populate spec.valuation.

    Args:
        spec: ModelSpecification with forecast, assumptions, and debt schedules populated.
        current_share_price: Current market share price for reverse DCF. Defaults to live market price
            or per-company registry price when unset.
        historical_model: HistoricalModel for reverse DCF revenue CAGR solver.
    """
    company_id = spec.metadata.company_id
    market = spec.metadata.market

    # Fetch live/cached market data for the company
    mdata = get_company_market_data(company_id, market=market)

    # 1. Share price resolution
    if current_share_price is None or current_share_price <= 0:
        current_share_price = mdata.price.value

    # 2. Sourced cash from latest historicals (FY26), falling back to 0.0 (never constant Infosys 22201.0)
    latest_hist = spec.historicals.periods[-1] if spec.historicals.periods else "FY26"
    cash_and_bank = spec.historicals.get_value("canonical.bs.cash_and_bank", latest_hist) or 0.0
    current_inv = spec.historicals.get_value("canonical.bs.current_investments", latest_hist) or 0.0
    cash_cr = cash_and_bank + current_inv

    # 3. Sourced diluted share count, resolving dynamically per company
    shares_cr: Optional[float] = None
    if spec.share_count:
        shares_cr = spec.share_count.get_diluted(latest_hist) or spec.share_count.get_diluted("FY27")
    if not shares_cr or shares_cr <= 0:
        if spec.metadata.shares_outstanding and spec.metadata.shares_outstanding > 0:
            shares_cr = spec.metadata.shares_outstanding
        else:
            shares_cr = mdata.shares_outstanding.value

    valuation_outputs: List[ValuationOutput] = []

    for scenario in ["base", "bull", "bear"]:
        # Find debt schedule for scenario, falling back to historical borrowings
        ds = next((d for d in spec.debt_schedule if d.scenario == scenario), None)
        debt_cr = (ds.closing(latest_hist) if ds else 0.0) or (spec.historicals.get_value("canonical.bs.borrowings", latest_hist) or 0.0)

        # 4. Compute WACC Breakdown — source inputs from assumptions if set, else market data provider
        def _wacc_input(driver_key: str) -> Optional[float]:
            for a in spec.assumptions:
                if a.driver_key == driver_key and a.scenario == scenario:
                    return a.value
            for a in spec.assumptions:
                if a.driver_key == driver_key and a.scenario == "base":
                    return a.value
            return None

        wacc_breakdown = compute_wacc(
            assumptions=spec.assumptions,
            debt_schedule=ds,
            share_count_schedule=spec.share_count,
            scenario=scenario,
            current_share_price=current_share_price,
            risk_free_rate=_wacc_input("wacc.risk_free_rate"),
            beta=_wacc_input("wacc.beta"),
            equity_risk_premium=_wacc_input("wacc.equity_risk_premium"),
            debt_cr=debt_cr,
            company_id=company_id,
            market=market,
        )
        wacc_pct = wacc_breakdown.wacc or 12.0

        # 5. Compute FCFF Periods
        fcff_periods = compute_fcff_periods(spec.forecast, wacc_pct, scenario)

        # 6. Compute Terminal Value (Gordon Growth default)
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

        # 7. DCF Bridge (EV -> Equity Value -> Implied Share Price)
        dcf_bridge, updated_tv = compute_dcf_bridge(
            fcff_periods=fcff_periods,
            terminal_value=terminal_val,
            cash_cr=cash_cr,
            debt_cr=debt_cr,
            shares_cr=shares_cr,
        )

        # 8. Reverse DCF
        reverse_dcf = compute_reverse_dcf(
            market_price=current_share_price,
            fcff_periods=fcff_periods,
            wacc_pct=wacc_pct,
            cash_cr=cash_cr,
            debt_cr=debt_cr,
            shares_cr=shares_cr,
            forecast=spec.forecast,
            assumptions=spec.assumptions,
            historical_model=historical_model,
            terminal_growth_rate=term_g,
            exit_multiple=exit_mult,
        )

        # Divergence Gate (sanity check on implied terminal growth band [-2%, 5%])
        if reverse_dcf.implied_terminal_growth is not None:
            g_impl = reverse_dcf.implied_terminal_growth
            if g_impl < -2.0 or g_impl > 5.0:
                flag_msg = f"[DIVERGENCE FLAG: implied growth {g_impl:.2f}% outside sane band (-2% to 5%)]"
                reverse_dcf.method_note = f"{reverse_dcf.method_note} {flag_msg}".strip()

        # 9. Sensitivity Analysis Grids
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
