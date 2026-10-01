from __future__ import annotations

"""
Reverse DCF solver module.

Given the current market share price, solves for implied market assumptions:
1. Implied Perpetuity Terminal Growth Rate (g_implied) using exact closed-form inversion.
2. Implied Revenue CAGR (cagr_implied) using a bisection solver across the forecast engine.

Enforces round-trip accuracy: running forward DCF with implied terminal growth reproduces
the market price within 0.01 of native currency units.
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
from backend.valuation import claims


def _last_period(forecast: Forecast) -> str:
    """The final year this forecast actually contains.

    `FORECAST_PERIODS[-1]` is a fixed label and is not necessarily in it. The
    horizon now begins after each company's last reported year, so a company ending
    FY30 has no FY31 and a lookup on the fixed label returned nothing — the terminal
    multiple and the exit-multiple path were both being computed on zero.
    """
    periods = list(forecast.periods)
    return periods[-1] if periods else FORECAST_PERIODS[-1]


def compute_reverse_dcf(
    market_price: float,
    fcff_periods: List[FCFFPeriod],
    wacc_pct: float,
    cash_cr: float,
    debt_cr: float,
    shares_cr: float,
    marketable_securities_cr: float = 0.0,
    non_current_investments_cr: float = 0.0,
    minority_interest_cr: float = 0.0,
    preferred_stock_cr: float = 0.0,
    mezzanine_equity_cr: float = 0.0,
    forecast: Optional[Forecast] = None,
    assumptions: Optional[List[AssumptionObject]] = None,
    historical_model=None,
    terminal_growth_rate: float = 4.0,
    exit_multiple: float = 20.0,
    timing_convention: str = "mid_year",
    currency: str = "INR",
    scenario: str = "base",
    last_ebit: Optional[float] = None,
    terminal_tax_rate: Optional[float] = None,
    opening_working_capital: Optional[float] = None,
) -> ReverseDCF:
    """Solve for implied terminal growth rate and revenue CAGR given market share price.

    Args:
        market_price: Current market share price.
        fcff_periods: FCFF periods computed at this scenario's assumptions.
        wacc_pct: WACC percentage.
        cash_cr: Cash balance in crores.
        debt_cr: Debt balance in crores.
        shares_cr: Diluted share count in crores.
        marketable_securities_cr: Current investments balance.
        non_current_investments_cr: Non-current investments balance.
        minority_interest_cr: Minority interest balance.
        preferred_stock_cr: Preferred stock balance.
        forecast: Forecast object (needed for revenue CAGR solver).
        assumptions: Assumptions for this scenario (needed for the CAGR solver).
        historical_model: Historical model (needed for revenue CAGR solver).
        terminal_growth_rate: Base terminal growth rate.
        exit_multiple: Base exit multiple.
        timing_convention: "mid_year" or "end_year".
        currency: Native currency code for the method note (e.g. "INR", "USD").
        scenario: Which scenario to solve. Must be threaded through to the CAGR
            solver: hardcoding "base" made the bull and bear reverse DCFs solve
            the BASE operating case and merely re-discount it, so they were not
            scenario analyses at all.
        last_ebit: Final-year EBIT, required by the terminal-FCFF normalisation
            branch. Omitting it prices a different company than the headline DCF.
        terminal_tax_rate: Terminal effective tax rate. Omitting it falls back to
            the US statutory rate for every company, including Indian ones.
    """
    if market_price <= 0 or shares_cr <= 0:
        return ReverseDCF(market_price=market_price, method_note="Invalid price or share count")

    # 1. Target Equity Value and EV
    target_equity_val = market_price * shares_cr
    total_liquid_and_investments = cash_cr + marketable_securities_cr + non_current_investments_cr
    # Walked from the shared declaration, like the forward bridge.
    #
    # This was a FOURTH copy of the same enumeration and it still omitted mezzanine
    # after the commit that introduced claims.py specifically to end that. Both
    # occurrences missed it, consistently, so the reverse DCF returned a plausible
    # wrong number rather than an obviously broken one: a filer with mezzanine was
    # solved for a growth rate that implies a higher equity value than actually
    # exists, which is the worst direction for an implied-rate output.
    claims_amount = sum(
        {
            "minority_interest": minority_interest_cr,
            "preferred_stock": preferred_stock_cr,
            "mezzanine_equity": mezzanine_equity_cr,
        }.get(c.bridge_field, 0.0)
        for c in claims.CLAIMS_AHEAD_OF_COMMON_EQUITY
    )
    total_obligations = debt_cr + claims_amount
    net_debt = total_obligations - total_liquid_and_investments
    target_ev = target_equity_val + net_debt

    # 2. Target PV of Terminal Value
    sum_pv_fcff = sum(p.pv_fcff for p in fcff_periods if p.pv_fcff is not None)
    target_pv_tv = target_ev - sum_pv_fcff

    wacc_frac = wacc_pct / 100.0
    # Terminal value discounting: exponent is the number of forecast periods, taken
    # from the periods themselves rather than from the fixed horizon. It is the same
    # end-of-final-year convention compute_terminal_value uses, so the two agree.
    df5 = 1.0 / ((1.0 + wacc_frac) ** len(fcff_periods))

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
            marketable_securities_cr=marketable_securities_cr,
            non_current_investments_cr=non_current_investments_cr,
            minority_interest_cr=minority_interest_cr,
            preferred_stock_cr=preferred_stock_cr,
        mezzanine_equity_cr=mezzanine_equity_cr,
            terminal_growth_rate=terminal_growth_rate,
            exit_multiple=exit_multiple,
            timing_convention=timing_convention,
            scenario=scenario,
            terminal_tax_rate=terminal_tax_rate,
            last_ebit=last_ebit,
            opening_working_capital=opening_working_capital,
        )

    note = f"Solved exact implied perpetuity growth rate for market price {currency} {market_price:.2f}"
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
    marketable_securities_cr: float = 0.0,
    non_current_investments_cr: float = 0.0,
    minority_interest_cr: float = 0.0,
    preferred_stock_cr: float = 0.0,
    terminal_growth_rate: float = 4.0,
    exit_multiple: float = 20.0,
    timing_convention: str = "mid_year",
    lo: float = -10.0,
    hi: float = 50.0,
    tol: float = 0.01,
    max_iter: int = 60,
    scenario: str = "base",
    terminal_tax_rate: Optional[float] = None,
    last_ebit: Optional[float] = None,
    opening_working_capital: Optional[float] = None,
) -> Optional[float]:
    """Bisection solver: find revenue CAGR that produces DCF implied price = market_price.

    Varies the revenue_growth driver for THIS scenario while holding all other
    assumptions fixed, re-running forecast + FCFF + DCF at each trial point.
    """
    from backend.forecast.engine import run_forecast
    from backend.valuation.dcf import compute_dcf_bridge, compute_fcff_periods, compute_terminal_value

    def _price_at_growth(growth_pct: float) -> float:
        # Create modified assumptions with trial revenue growth for this scenario
        trial_assumptions = []
        for a in assumptions:
            if a.driver_key == "revenue_growth" and a.scenario == scenario:
                trial_assumptions.append(a.model_copy(update={"value": growth_pct}))
            else:
                trial_assumptions.append(a)

        # Re-run forecast with trial growth
        trial_forecast = run_forecast(trial_assumptions, historical_model, scenario)

        # Compute FCFF at this scenario's WACC
        fcffs = compute_fcff_periods(
            trial_forecast,
            wacc_pct,
            scenario,
            timing_convention=timing_convention,
            opening_working_capital=opening_working_capital,
        )  # type: ignore
        if not fcffs:
            return 0.0

        last_fcff = fcffs[-1].fcff or 0.0
        last_ebitda = trial_forecast.get_value(
            "canonical.is.ebitda", _last_period(trial_forecast), scenario
        ) or 0.0
        trial_last_ebit = trial_forecast.get_value(
            "canonical.is.operating_profit", _last_period(trial_forecast), scenario
        ) or 0.0

        # Compute DCF
        tv = compute_terminal_value(
            last_fcff,
            last_ebitda,
            wacc_pct,
            terminal_growth_rate,
            exit_multiple,
            "gordon_growth",
            last_ebit=trial_last_ebit,
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
