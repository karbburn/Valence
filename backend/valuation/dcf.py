from __future__ import annotations

"""
FCFF & DCF computation module.

Calculates Free Cash Flow to Firm (FCFF), discounts to present value, computes
dual terminal values (Gordon Growth and Exit Multiple), and completes the EV -> Equity Value -> Implied Share Price bridge.
"""

from typing import List, Optional, Tuple

from backend.forecast.debt import DebtSchedule
from backend.forecast.share_count import ShareCountSchedule
from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.forecast import FORECAST_PERIODS, Forecast
from backend.models.spec.valuation import (
    DCFBridge,
    FCFFPeriod,
    TerminalValue,
    WACCBreakdown,
)


def compute_fcff_periods(
    forecast: Forecast,
    wacc_pct: float,
    scenario: str = "base",
) -> List[FCFFPeriod]:
    """Compute FCFF and discounted PV for each forecast period."""
    periods_fcff: List[FCFFPeriod] = []
    wacc_frac = wacc_pct / 100.0

    for idx, p in enumerate(FORECAST_PERIODS):
        t = idx + 1
        ebit = forecast.get_value("canonical.is.operating_profit", p, scenario) or 0.0
        pbt = forecast.get_value("canonical.is.pbt", p, scenario) or ebit
        tax = forecast.get_value("canonical.is.tax", p, scenario) or 0.0
        tax_rate = round((tax / pbt * 100.0), 4) if pbt and pbt > 0 else (0.0 if pbt and pbt < 0 else 27.0)
        nopat = ebit * (1.0 - tax_rate / 100.0)
        da = forecast.get_value("canonical.is.depreciation_amortization", p, scenario) or 0.0

        # Capex from investing activities (outflow is negative in CF, take absolute)
        inv_cf = forecast.get_value("canonical.cf.investing_activities", p, scenario) or 0.0
        capex = abs(inv_cf)

        # Working Capital delta: Operating CF = Net Profit + DA - delta_WC
        np_val = forecast.get_value("canonical.is.net_profit", p, scenario) or 0.0
        cfo_val = forecast.get_value("canonical.cf.operating_activities", p, scenario) or (np_val + da)
        delta_wc = np_val + da - cfo_val

        fcff = nopat + da - capex - delta_wc
        discount_factor = 1.0 / ((1.0 + wacc_frac) ** t)
        pv_fcff = fcff * discount_factor

        periods_fcff.append(
            FCFFPeriod(
                period=p,
                ebit=round(ebit, 2),
                tax_rate=round(tax_rate, 2),
                nopat=round(nopat, 2),
                da=round(da, 2),
                capex=round(capex, 2),
                delta_working_capital=round(delta_wc, 2),
                fcff=round(fcff, 2),
                discount_factor=round(discount_factor, 6),
                pv_fcff=round(pv_fcff, 2),
            )
        )

    return periods_fcff


def compute_terminal_value(
    last_fcff: float,
    last_ebitda: float,
    wacc_pct: float,
    terminal_growth_rate: float = 4.0,
    exit_multiple: float = 20.0,
    active_method: str = "gordon_growth",
) -> TerminalValue:
    """Compute dual terminal value (Gordon Growth & Exit Multiple).

    Validates terminal_growth_rate < WACC.
    """
    if terminal_growth_rate >= wacc_pct:
        raise ValueError(
            f"Invalid Terminal Growth Rate ({terminal_growth_rate:.2f}%): "
            f"must be strictly less than WACC ({wacc_pct:.2f}%)."
        )

    wacc_frac = wacc_pct / 100.0
    g_frac = terminal_growth_rate / 100.0
    df5 = 1.0 / ((1.0 + wacc_frac) ** 5)

    # 1. Gordon Growth
    gg_undiscounted = (last_fcff * (1.0 + g_frac)) / (wacc_frac - g_frac)
    gg_pv = gg_undiscounted * df5

    # 2. Exit Multiple
    em_undiscounted = last_ebitda * exit_multiple
    em_pv = em_undiscounted * df5

    # Primary PV depends on active method
    primary_pv = gg_pv if active_method == "gordon_growth" else em_pv

    return TerminalValue(
        method=active_method,  # type: ignore
        terminal_growth_rate=round(terminal_growth_rate, 4),
        final_year_fcff=round(last_fcff, 2),
        terminal_value_undiscounted=round(gg_undiscounted, 2),
        exit_multiple=round(exit_multiple, 4),
        final_year_ebitda=round(last_ebitda, 2),
        exit_multiple_tv_undiscounted=round(em_undiscounted, 2),
        discount_factor=round(df5, 6),
        terminal_value_pv=round(primary_pv, 2),
        tv_pct_of_ev=None,  # Populated in DCF bridge step
    )


def compute_dcf_bridge(
    fcff_periods: List[FCFFPeriod],
    terminal_value: TerminalValue,
    cash_cr: float,
    debt_cr: float,
    shares_cr: float,
) -> Tuple[DCFBridge, TerminalValue]:
    """Compute EV -> Equity Value -> Implied Share Price bridge."""
    sum_pv_fcff = sum(p.pv_fcff for p in fcff_periods if p.pv_fcff is not None)
    pv_tv = terminal_value.terminal_value_pv or 0.0
    ev = sum_pv_fcff + pv_tv

    net_debt = debt_cr - cash_cr  # Negative net_debt means Net Cash
    equity_value = ev - net_debt  # EV - (Debt - Cash) = EV + Cash - Debt

    implied_price = (equity_value / shares_cr) if shares_cr > 0 else 0.0

    # Update tv_pct_of_ev on TerminalValue object
    tv_pct = (pv_tv / ev * 100.0) if ev > 0 else 0.0
    updated_tv = terminal_value.model_copy(update={"tv_pct_of_ev": round(tv_pct, 2)})

    bridge = DCFBridge(
        sum_pv_fcff=round(sum_pv_fcff, 2),
        pv_terminal_value=round(pv_tv, 2),
        enterprise_value=round(ev, 2),
        less_net_debt=round(net_debt, 2),
        equity_value=round(equity_value, 2),
        shares_outstanding=round(shares_cr, 4),
        implied_share_price=round(implied_price, 2),
    )

    return bridge, updated_tv
