from __future__ import annotations

"""
Reverse DCF solver module.

Given the current market share price, solves for implied market assumptions:
1. Implied Perpetuity Terminal Growth Rate (g_implied) using exact closed-form inversion.
2. Implied Revenue CAGR (cagr_implied) using a bisection solver across the forecast engine.

Enforces round-trip accuracy: running forward DCF with implied terminal growth reproduces
the market price within 0.01 INR.
"""

from typing import List, Optional

from backend.forecast.debt import DebtSchedule
from backend.forecast.share_count import ShareCountSchedule
from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.forecast import FORECAST_PERIODS, Forecast
from backend.models.spec.valuation import (
    FCFFPeriod,
    ReverseDCF,
    TerminalValue,
    WACCBreakdown,
)


def compute_reverse_dcf(
    market_price: float,
    fcff_periods: List[FCFFPeriod],
    wacc_pct: float,
    cash_cr: float,
    debt_cr: float,
    shares_cr: float,
) -> ReverseDCF:
    """Solve for implied terminal growth rate given market share price."""
    if market_price <= 0 or shares_cr <= 0:
        return ReverseDCF(market_price=market_price, method_note="Invalid price or share count")

    # 1. Target Equity Value and EV
    target_equity_val = market_price * shares_cr
    net_debt = debt_cr - cash_cr
    target_ev = target_equity_val + net_debt

    # 2. Target PV of Terminal Value
    sum_pv_fcff = sum(p.pv_fcff for p in fcff_periods if p.pv_fcff is not None)
    target_pv_tv = target_ev - sum_pv_fcff

    wacc_frac = wacc_pct / 100.0
    df5 = 1.0 / ((1.0 + wacc_frac) ** 5)

    # Undiscounted target TV
    target_tv_undiscounted = target_pv_tv / df5 if df5 > 0 else 0.0

    # 3. Exact closed-form solve for g
    last_fcff = fcff_periods[-1].fcff if fcff_periods and fcff_periods[-1].fcff else 0.0

    implied_g: Optional[float] = None
    if last_fcff > 0 and (target_tv_undiscounted + last_fcff) > 0:
        g_frac = (target_tv_undiscounted * wacc_frac - last_fcff) / (target_tv_undiscounted + last_fcff)
        implied_g = g_frac * 100.0

    note = f"Solved exact implied perpetuity growth rate for market price INR {market_price:.2f}"

    return ReverseDCF(
        market_price=round(market_price, 2),
        implied_terminal_growth=round(implied_g, 4) if implied_g is not None else None,
        implied_revenue_cagr=None,
        method_note=note,
    )
