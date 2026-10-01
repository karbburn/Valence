from __future__ import annotations

"""
FCFF & DCF computation module.

Calculates Free Cash Flow to Firm (FCFF), discounts to present value, computes
dual terminal values (Gordon Growth and Exit Multiple), and completes the EV -> Equity Value -> Implied Share Price bridge.
"""

from datetime import date
from typing import Dict, List, Literal, Optional, Tuple

from backend.valuation import claims

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

# Balance-sheet lines that make up operating working capital. The forecast
# engine moves exactly these three, so a spec missing the explicit
# delta_working_capital line can be reconstructed from them without guessing.
_WC_ASSET_KEYS = (
    "canonical.bs.trade_receivables",
    "canonical.bs.inventory",
)
_WC_LIABILITY_KEYS = ("canonical.bs.trade_payables",)


def _wc_level(forecast: Forecast, period: str, scenario: str) -> float:
    """Operating working capital at `period`: receivables + inventory − payables."""
    total = 0.0
    for key in _WC_ASSET_KEYS:
        total += forecast.get_value(key, period, scenario) or 0.0
    for key in _WC_LIABILITY_KEYS:
        total -= forecast.get_value(key, period, scenario) or 0.0
    return total


def _delta_wc_from_balance_sheet(
    forecast: Forecast,
    period: str,
    scenario: str,
    prior: Optional[float] = None,
) -> float:
    """Change in working capital for `period`, derived from balance-sheet levels.

    `prior` is the opening level carried in from the previous period; when it is
    None the first forecast year falls back to zero, which is the correct
    reading when the opening balance is genuinely absent from the spec.
    """
    if prior is None:
        return 0.0
    return _wc_level(forecast, period, scenario) - prior


def _valuation_date(forecast: Forecast, historicals=None):
    """The date the model's cash and debt are struck on: its balance sheet date.

    Every discount factor is measured from here rather than from an assumed
    half-year, because the model's own cash and debt belong to this date and a cash
    flow discounted from anywhere else is not consistent with them.

    Taken from the HISTORICALS, not from the forecast. The earliest forecast line
    is the first forecast year, and measuring from that put every first year's cash
    flow at roughly zero years out — a discount factor of 1.0, i.e. no discounting
    at all on the year the whole terminal argument leans on.
    """
    for source in (historicals, forecast):
        items = getattr(source, "line_items", None) or []
        dates = [
            item.period_end_date
            for item in items
            if getattr(item, "period_end_date", None)
        ]
        if dates:
            return max(dates)
    return None


def compute_fcff_periods(
    forecast: Forecast,
    wacc_pct: float,
    scenario: str = "base",
    timing_convention: Literal["mid_year", "end_year"] = "mid_year",
    opening_working_capital: Optional[float] = None,
    historicals=None,
) -> List[FCFFPeriod]:
    """Compute FCFF and discounted PV for each forecast period using mid-year discounting.

    `opening_working_capital` is the operating working-capital level carried in
    from the last historical period. It is only consulted when the forecast is
    missing its explicit `canonical.cf.delta_working_capital` line, so that a
    spec cached by an older engine still produces the engine's own working
    capital movement rather than a guess.
    """
    periods_fcff: List[FCFFPeriod] = []
    wacc_frac = wacc_pct / 100.0
    prior_wc = opening_working_capital

    # How long each period's cash flow is actually away, from the dates on the
    # forecast itself rather than from its position in a list.
    #
    # It was `(idx + 1) - 0.5`, which places every company's first forecast year at
    # exactly half a year out regardless of when that year closes. NVIDIA's FY2027
    # cash flow arrives at the end of January 2027 and Microsoft theirs at the end of
    # June 2027, and a December filer's is five and a half months away where a
    # January filer's is not — so the same discount was applied to cash flows that
    # are six months apart. The error is in the discounting, not in a label, so it
    # moves every price and is invisible in any reconciliation of the model.
    #
    # Measured from the last reported balance sheet, which is the date the model's
    # own cash and debt are struck on and therefore the only self-consistent
    # starting point. A period with no date falls back to the index, which is the
    # old behaviour rather than a worse one.
    valuation_date = _valuation_date(forecast, historicals)
    period_ends = {
        item.period_label: item.period_end_date
        for item in (getattr(forecast, "line_items", None) or [])
    }

    def _years_to(period_label: str, index: int) -> float:
        end = period_ends.get(period_label)
        if valuation_date is None or end is None:
            return (index + 1) - 0.5 if timing_convention == "mid_year" else (index + 1)
        elapsed = (end - valuation_date).days / 365.25
        # A period ending before the balance sheet date cannot be discounted by a
        # negative length, and mid-year still applies to it.
        if elapsed <= 0:
            elapsed = (index + 1) - 0.5 if timing_convention == "mid_year" else (index + 1)
        if timing_convention == "mid_year":
            elapsed -= 0.5
        return max(elapsed, 0.0)

    # The periods the forecast actually contains, not the platform default. They
    # differ by company now that the horizon is derived from the last reported year.
    forecast_periods = list(getattr(forecast, "periods", None) or []) or list(FORECAST_PERIODS)

    for idx, p in enumerate(forecast_periods):
        t = _years_to(p, idx)
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

        # Working Capital delta.
        #
        # The engine defines it as a balance-sheet movement:
        #   ΔWC = (AR_t − AR_{t−1}) + (Inv_t − Inv_{t−1}) − (AP_t − AP_{t−1})
        # which is a cash OUTFLOW when working capital grows. Never back it out
        # of net profit / D&A / CFO: that identity only holds if CFO was itself
        # built from the same ΔWC, so on a spec cached by an older engine it
        # silently returns a different — and wrong — number instead of missing.
        delta_wc_val = forecast.get_value("canonical.cf.delta_working_capital", p, scenario)
        if delta_wc_val is not None:
            delta_wc = delta_wc_val
        else:
            delta_wc = _delta_wc_from_balance_sheet(forecast, p, scenario, prior=prior_wc)
        prior_wc = _wc_level(forecast, p, scenario)

        # Stock-based compensation is a real economic cost even though non-cash under
        # accounting rules — treat it as a cash operating outflow for valuation.
        sbc_val = forecast.get_value("canonical.cf.stock_compensation", p, scenario)
        stock_comp = abs(sbc_val) if sbc_val else 0.0

        fcff = nopat + da - capex - delta_wc - stock_comp
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
                stock_compensation=round(stock_comp, 2),
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
    terminal_period_end: Optional[date] = None,
    valuation_date: Optional[date] = None,
) -> TerminalValue:
    """Compute dual terminal value (Gordon Growth & Exit Multiple) with quality checks.

    Validates terminal_growth_rate < WACC.
    Computes implied terminal ROIC & reinvestment rate.

    `terminal_period_end` and `valuation_date` are the dates the discounting is
    measured between. Without them the terminal is discounted by the LENGTH of the
    forecast rather than by how long it actually runs, which was five years for
    every company: a January filer's five-year forecast reaches into January and a
    December filer's into December, and both were discounted as if they ended at
    the same moment five years out.
    """
    if terminal_growth_rate >= wacc_pct:
        raise ValueError(
            f"Invalid Terminal Growth Rate ({terminal_growth_rate:.2f}%): "
            f"must be strictly less than WACC ({wacc_pct:.2f}%)."
        )

    wacc_frac = wacc_pct / 100.0
    g_frac = terminal_growth_rate / 100.0
    # Standard Wall Street convention: the terminal value is struck at the END of the
    # final forecast year, so the exponent is the length of the whole forecast. From
    # the company's own dates where they are known, and from the horizon length where
    # they are not.
    if terminal_period_end is not None and valuation_date is not None:
        years = (terminal_period_end - valuation_date).days / 365.25
        if years <= 0:
            years = float(len(FORECAST_PERIODS))
    else:
        years = float(len(FORECAST_PERIODS))
    df5 = 1.0 / ((1.0 + wacc_frac) ** years)

    # 1. Gordon Growth
    # Standard Valuation Practice (McKinsey / Damodaran): If final year FCFF is non-positive due to
    # heavy explicit expansion CapEx, normalize steady-state terminal FCFF as NOPAT * (1 - Reinvestment Rate)
    # assuming CapEx fades to Maintenance CapEx (≈ D&A) in perpetuity.
    if last_fcff <= 0 and last_ebit is not None and last_ebit > 0:
        eff_tax = (terminal_tax_rate / 100.0) if terminal_tax_rate is not None else DEFAULT_TERMINAL_TAX_RATE
        steady_nopat = last_ebit * (1.0 - eff_tax)
        reinvest_rate = min(0.50, max(0.10, g_frac / max(0.01, wacc_frac)))
        normalized_terminal_fcff = steady_nopat * (1.0 - reinvest_rate)
        gg_undiscounted = (normalized_terminal_fcff * (1.0 + g_frac)) / (wacc_frac - g_frac)
    else:
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
        raw_rate = (reinvest / terminal_nopat * 100.0) if terminal_nopat > 0 else None
        # A reinvestment rate above 100% means the business must fund growth with
        # more capital than it earns, indefinitely. That is not a steady state, it
        # is a company that either raises capital forever or does not grow, so the
        # ratio carries no meaning above 100 and is reported as absent rather than
        # published as a number.
        #
        # It was reached whenever the final-year free cash flow went negative:
        # NOPAT minus a negative FCFF exceeds NOPAT. One railway reported 117.94%
        # on this line, and the implied ROIC derived from it, 3.39%, was published
        # in the workbook as though it were a finding about the business. The
        # terminal itself was fine, because the terminal's own reinvestment rate
        # is clamped separately; this was a diagnostic reporting a value it had no
        # way to compute.
        reinvestment_rate = raw_rate if raw_rate is not None and raw_rate <= 100.0 else None
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
    mezzanine_equity_cr: float = 0.0,
    operating_lease_liabilities_cr: float = 0.0,
    **other_claims_cr: float,
) -> Tuple[DCFBridge, TerminalValue]:
    """Compute EV -> Equity Value -> Implied Share Price bridge with full non-operating breakdown.

    `debt_cr` must be total interest-bearing debt: non-current borrowings plus
    current borrowings including the current portion of long-term debt, plus
    finance and capital lease liabilities.

    `operating_lease_liabilities_cr` is reported on the bridge but NOT deducted.
    Rent is an operating expense in EBIT under US GAAP, so the lease obligation
    is already reflected in the cash flows being discounted; deducting the
    liability as well would charge for it twice. It is carried here so a reader
    who prefers the capitalised-lease convention can see the amount and apply
    it deliberately.
    """
    sum_pv_fcff = sum(p.pv_fcff for p in fcff_periods if p.pv_fcff is not None)
    pv_tv = terminal_value.terminal_value_pv or 0.0
    ev = sum_pv_fcff + pv_tv

    # Comprehensive Non-Operating Assets & Liabilities Bridge:
    # Net Debt = (Borrowings + Minority Interest + Preferred Stock) - (Cash + Marketable Sec + Non-Current Inv)
    total_liquid_and_investments = cash_cr + marketable_securities_cr + non_current_investments_cr
    # Mezzanine equity belongs here for the same reason minority interest and
    # preferred stock do: it is a claim on the enterprise that ranks AHEAD of
    # common equity, so value attributable to common shareholders is what is
    # left after it. Uxin filed 48,056 of it and the bridge was overstating
    # equity value by that amount, because the balance sheet had started
    # carrying the line and the bridge had not started deducting it.
    # Walked from the shared declaration, so a claim class is added in one place.
    #
    # This list was restated here, in the workbook's bridge row, and in the workbook
    # self-check's independent re-derivation of net debt. Mezzanine equity was
    # missing from all three, so Uxin's equity value was overstated by its filed
    # 48,056 and the self-check -- whose entire job is catching a bridge that does
    # not reconcile -- agreed with the wrong answer, because the omission sat in
    # both places at once.
    _known_params = {
        c.bridge_field + "_cr" for c in claims.CLAIMS_AHEAD_OF_COMMON_EQUITY
    }
    # Diagnosed before the loop below, so a mistyped claim name names itself instead
    # of being reported as a claim that "has no amount".
    _unknown = sorted(set(other_claims_cr) - _known_params)
    if _unknown:
        raise ValueError(
            f"the bridge was given amounts that match no declared claim: "
            f"{', '.join(_unknown)}. Add the claim to "
            f"backend.valuation.claims.CLAIMS_AHEAD_OF_COMMON_EQUITY, or correct the "
            f"name. Deducting nothing while appearing to have charged is the failure "
            f"mode this refuses."
        )

    _locals = locals()
    claims_amount = 0.0
    _unnamed: Dict[str, float] = {}
    for _c in claims.CLAIMS_AHEAD_OF_COMMON_EQUITY:
        _param = _c.bridge_field + "_cr"
        _v = _locals.get(_param)
        if _v is None:
            _v = other_claims_cr.get(_param)
        if _v is None:
            # Declared but not supplied. Defaulting to zero here would reproduce the
            # mezzanine defect exactly: the claim exists, the arithmetic runs, and
            # the reader is simply never charged. Refusing is the point.
            raise ValueError(
                f"claim '{_c.bridge_field}' is declared in backend.valuation.claims "
                f"but no amount reached the bridge. Pass {_param}=, or remove it "
                f"from the declaration."
            )
        claims_amount += _v
        if _c.bridge_field not in DCFBridge.model_fields:
            # A claim with no field of its own must still be PUBLISHED, or the
            # workbook and the frontend -- which read named fields -- would each
            # show a reader that nothing stands ahead of them, while the arithmetic
            # had charged it.
            _unnamed[_c.bridge_field] = _v

    total_obligations = debt_cr + claims_amount
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
        operating_lease_liabilities=round(operating_lease_liabilities_cr, 2),
        minority_interest=round(minority_interest_cr, 2),
        preferred_stock=round(preferred_stock_cr, 2),
        mezzanine_equity=round(mezzanine_equity_cr, 2),
        other_claims={k: round(v, 2) for k, v in _unnamed.items()},
        less_net_debt=round(net_debt, 2),
        equity_value=round(equity_value, 2),
        shares_outstanding=round(shares_cr, 4),
        implied_share_price=round(implied_price, 2),
    )

    return bridge, updated_tv
