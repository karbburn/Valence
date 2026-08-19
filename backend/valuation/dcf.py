from __future__ import annotations

"""
FCFF & DCF computation module.

Calculates Free Cash Flow to Firm (FCFF), discounts to present value, computes
dual terminal values (Gordon Growth and Exit Multiple), and completes the EV -> Equity Value -> Implied Share Price bridge.
"""

from typing import List, Literal, Optional, Tuple

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

# Default effective tax rate used ONLY for the implied-ROIC quality check when the
# caller does not supply an explicit terminal tax rate (US statutory rate).
DEFAULT_TERMINAL_TAX_RATE = 0.21


def compute_fcff_periods(
    forecast: Forecast,
    wacc_pct: float,
    scenario: str = "base",
    timing_convention: Literal["mid_year", "end_year"] = "mid_year",
) -> List[FCFFPeriod]:
    """Compute FCFF and discounted PV for each forecast period using mid-year discounting."""
    periods_fcff: List[FCFFPeriod] = []
    wacc_frac = wacc_pct / 100.0

    for idx, p in enumerate(FORECAST_PERIODS):
        t = (idx + 1) - 0.5 if timing_convention == "mid_year" else (idx + 1)
        ebit = forecast.get_value("canonical.is.operating_profit", p, scenario) or 0.0
        pbt = forecast.get_value("canonical.is.pbt", p, scenario) or ebit
        tax = forecast.get_value("canonical.is.tax", p, scenario) or 0.0
        # Effective tax rate: only a positive PBT creates taxable income. A breakeven
        # (PBT == 0) or loss-making (PBT < 0) period carries a 0% effective rate.
        if pbt is not None and pbt > 0:
            tax_rate = round((tax / pbt * 100.0), 4)
        else:
            tax_rate = 0.0
        nopat = ebit * (1.0 - tax_rate / 100.0)
        da = forecast.get_value("canonical.is.depreciation_amortization", p, scenario) or 0.0

        # Real capex from canonical.cf.capex, falling back to D&A as conservative maintenance proxy.
        # NOTE: Do NOT use total investing activities — they include M&A which inflates capex significantly.
        capex_val = forecast.get_value("canonical.cf.capex", p, scenario)
        if capex_val is not None:
            capex = abs(capex_val)
        else:
            # Conservative fallback: maintenance capex ≈ D&A (standard assumption for large-cap tech)
            capex = abs(da)

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
                timing_convention=timing_convention,
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
    last_ebit: Optional[float] = None,
    terminal_tax_rate: Optional[float] = None,
    timing_convention: Literal["mid_year", "end_year"] = "mid_year",
) -> TerminalValue:
    """Compute dual terminal value (Gordon Growth & Exit Multiple) with quality checks.

    Validates terminal_growth_rate < WACC.
    Computes implied terminal ROIC & reinvestment rate.
    """
    if terminal_growth_rate >= wacc_pct:
        raise ValueError(
            f"Invalid Terminal Growth Rate ({terminal_growth_rate:.2f}%): "
            f"must be strictly less than WACC ({wacc_pct:.2f}%)."
        )

    wacc_frac = wacc_pct / 100.0
    g_frac = terminal_growth_rate / 100.0
    # Standard Wall Street convention: terminal value is discounted from the END of the
    # final forecast year, so the exponent equals the number of forecast periods.
    df5 = 1.0 / ((1.0 + wacc_frac) ** len(FORECAST_PERIODS))

    # 1. Gordon Growth
    gg_undiscounted = (last_fcff * (1.0 + g_frac)) / (wacc_frac - g_frac)
    gg_pv = gg_undiscounted * df5

    # Quality & Reinvestment Check (ValueDriver formula: g = ROIC * Reinvestment Rate)
    terminal_nopat: Optional[float] = None
    reinvestment_rate: Optional[float] = None
    implied_roic: Optional[float] = None

    if last_ebit is not None and last_ebit > 0:
        eff_tax = (terminal_tax_rate / 100.0) if terminal_tax_rate is not None else DEFAULT_TERMINAL_TAX_RATE
        terminal_nopat = (last_ebit * (1.0 + g_frac)) * (1.0 - eff_tax)
        terminal_fcff = last_fcff * (1.0 + g_frac)
        reinvest = max(0.0, terminal_nopat - terminal_fcff)
        reinvestment_rate = (reinvest / terminal_nopat * 100.0) if terminal_nopat > 0 else None
        if reinvestment_rate and reinvestment_rate > 0:
            implied_roic = terminal_growth_rate / (reinvestment_rate / 100.0)

    # 2. Exit Multiple
    em_undiscounted = last_ebitda * exit_multiple
    em_pv = em_undiscounted * df5

    # Primary PV depends on active method
    primary_pv = gg_pv if active_method == "gordon_growth" else em_pv

    return TerminalValue(
        method=active_method,  # type: ignore
        timing_convention=timing_convention,
        terminal_growth_rate=round(terminal_growth_rate, 4),
        final_year_fcff=round(last_fcff, 2),
        terminal_value_undiscounted=round(gg_undiscounted, 2),
        terminal_nopat=round(terminal_nopat, 2) if terminal_nopat is not None else None,
        reinvestment_rate=round(reinvestment_rate, 2) if reinvestment_rate is not None else None,
        implied_roic=round(implied_roic, 2) if implied_roic is not None else None,
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
    marketable_securities_cr: float = 0.0,
    non_current_investments_cr: float = 0.0,
    minority_interest_cr: float = 0.0,
    preferred_stock_cr: float = 0.0,
) -> Tuple[DCFBridge, TerminalValue]:
    """Compute EV -> Equity Value -> Implied Share Price bridge with full non-operating breakdown."""
    sum_pv_fcff = sum(p.pv_fcff for p in fcff_periods if p.pv_fcff is not None)
    pv_tv = terminal_value.terminal_value_pv or 0.0
    ev = sum_pv_fcff + pv_tv

    # Comprehensive Non-Operating Assets & Liabilities Bridge:
    # Net Debt = (Borrowings + Minority Interest + Preferred Stock) - (Cash + Marketable Sec + Non-Current Inv)
    total_liquid_and_investments = cash_cr + marketable_securities_cr + non_current_investments_cr
    total_obligations = debt_cr + minority_interest_cr + preferred_stock_cr
    net_debt = total_obligations - total_liquid_and_investments

    equity_value = ev - net_debt

    implied_price = (equity_value / shares_cr) if shares_cr > 0 else 0.0

    # Update tv_pct_of_ev on TerminalValue object
    tv_pct = (pv_tv / ev * 100.0) if ev > 0 else 0.0
    updated_tv = terminal_value.model_copy(update={"tv_pct_of_ev": round(tv_pct, 2)})

    bridge = DCFBridge(
        sum_pv_fcff=round(sum_pv_fcff, 2),
        pv_terminal_value=round(pv_tv, 2),
        enterprise_value=round(ev, 2),
        cash_and_equivalents=round(cash_cr, 2),
        marketable_securities=round(marketable_securities_cr, 2),
        non_current_investments=round(non_current_investments_cr, 2),
        total_debt=round(debt_cr, 2),
        minority_interest=round(minority_interest_cr, 2),
        preferred_stock=round(preferred_stock_cr, 2),
        less_net_debt=round(net_debt, 2),
        equity_value=round(equity_value, 2),
        shares_outstanding=round(shares_cr, 4),
        implied_share_price=round(implied_price, 2),
    )

    return bridge, updated_tv
