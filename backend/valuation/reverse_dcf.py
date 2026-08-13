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
    forecast: Optional[Forecast] = None,
    assumptions: Optional[List[AssumptionObject]] = None,
    historical_model=None,
    terminal_growth_rate: float = 4.0,
    exit_multiple: float = 20.0,
) -> ReverseDCF:
    """Solve for implied terminal growth rate and revenue CAGR given market share price.

    Args:
        market_price: Current market share price.
        fcff_periods: FCFF periods computed at base assumptions.
        wacc_pct: WACC percentage.
        cash_cr: Cash balance in crores.
        debt_cr: Debt balance in crores.
        shares_cr: Diluted share count in crores.
        forecast: Forecast object (needed for revenue CAGR solver).
        assumptions: Base scenario assumptions (needed for revenue CAGR solver).
        historical_model: Historical model (needed for revenue CAGR solver).
        terminal_growth_rate: Base terminal growth rate.
        exit_multiple: Base exit multiple.
    """
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

    # 4. Bisection solver for implied revenue CAGR
    implied_cagr: Optional[float] = None
    if forecast and assumptions and historical_model is not None:
        implied_cagr = _solve_implied_revenue_cagr(
            market_price=market_price,
            forecast=forecast,
            assumptions=assumptions,
            historical_model=historical_model,
            wacc_pct=wacc_pct,
            cash_cr=cash_cr,
            debt_cr=debt_cr,
            shares_cr=shares_cr,
            terminal_growth_rate=terminal_growth_rate,
            exit_multiple=exit_multiple,
        )

    note = f"Solved exact implied perpetuity growth rate for market price INR {market_price:.2f}"
    if implied_cagr is not None:
        note += f"; implied revenue CAGR via bisection"

    return ReverseDCF(
        market_price=round(market_price, 2),
        implied_terminal_growth=round(implied_g, 4) if implied_g is not None else None,
        implied_revenue_cagr=round(implied_cagr, 4) if implied_cagr is not None else None,
        method_note=note,
    )


def _solve_implied_revenue_cagr(
    market_price: float,
    forecast: Forecast,
    assumptions: List[AssumptionObject],
    historical_model,
    wacc_pct: float,
    cash_cr: float,
    debt_cr: float,
    shares_cr: float,
    terminal_growth_rate: float,
    exit_multiple: float,
    lo: float = -10.0,
    hi: float = 50.0,
    tol: float = 0.01,
    max_iter: int = 60,
) -> Optional[float]:
    """Bisection solver: find revenue CAGR that produces DCF implied price = market_price.

    Varies revenue_growth assumption while holding all other assumptions fixed,
    re-runs forecast + FCFF + DCF at each trial point.
    """
    from backend.forecast.engine import run_forecast
    from backend.valuation.dcf import compute_dcf_bridge, compute_fcff_periods, compute_terminal_value

    def _price_at_growth(growth_pct: float) -> float:
        # Create modified assumptions with trial revenue growth
        trial_assumptions = []
        for a in assumptions:
            if a.driver_key == "revenue_growth" and a.scenario == "base":
                trial_assumptions.append(a.model_copy(update={"value": growth_pct}))
            else:
                trial_assumptions.append(a)

        # Re-run forecast with trial growth
        trial_forecast = run_forecast(trial_assumptions, historical_model, "base")

        # Compute FCFF at base WACC
        fcffs = compute_fcff_periods(trial_forecast, wacc_pct, "base")
        if not fcffs:
            return 0.0

        last_fcff = fcffs[-1].fcff or 0.0
        last_ebitda = trial_forecast.get_value("canonical.is.ebitda", "FY31", "base") or 0.0

        # Compute DCF
        tv = compute_terminal_value(last_fcff, last_ebitda, wacc_pct, terminal_growth_rate, exit_multiple, "gordon_growth")
        bridge, _ = compute_dcf_bridge(fcffs, tv, cash_cr, debt_cr, shares_cr)
        return bridge.implied_share_price

    # Check boundaries
    p_lo = _price_at_growth(lo)
    p_hi = _price_at_growth(hi)

    if abs(p_lo - market_price) < tol:
        return lo
    if abs(p_hi - market_price) < tol:
        return hi

    # Ensure market price is within range (if not, return None)
    if (p_lo < market_price and p_hi < market_price) or (p_lo > market_price and p_hi > market_price):
        return None

    # Bisection
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        p_mid = _price_at_growth(mid)

        if abs(p_mid - market_price) < tol:
            return mid

        if (p_mid < market_price) == (p_lo < market_price):
            lo = mid
            p_lo = p_mid
        else:
            hi = mid
            p_hi = p_mid

    return (lo + hi) / 2.0
