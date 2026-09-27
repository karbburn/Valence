from __future__ import annotations

"""
WACC computation module.

Calculates cost of equity via CAPM (rfr + beta * erp), cost of debt after-tax,
market value capital weighting, and total WACC. Every intermediate step is recorded
in WACCBreakdown for live formula reconstruction in Excel.

Computes generically and market-aware: cost of equity inputs (RFR, Beta, ERP) resolve per market
and per company from live market data (or registry/default fallback chain). Capital weights derive
from the company's actual debt schedule and market cap. No Infosys-specific share/cash hardcodes.
"""

from typing import List, Optional

from backend.constants import MIN_CARRYING_RATE
from backend.data.providers.market_data import get_company_market_data
from backend.forecast.debt import DebtSchedule
from backend.forecast.share_count import ShareCountSchedule
from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.forecast import FORECAST_PERIODS
from backend.models.spec.valuation import WACCBreakdown


def _get_assumption_val(
    assumptions: List[AssumptionObject],
    driver_key: str,
    scenario: str = "base",
    default: Optional[float] = None,
    *,
    only_overrides: bool = False,
    period: Optional[str] = None,
) -> Optional[float]:
    """Resolve a driver value from the assumption layer.

    only_overrides=True ignores model_generated values. Used for drivers whose
    model_generated value is a build-time snapshot of live market data
    (e.g. wacc.cost_of_equity): honouring that snapshot would silently pin the
    discount rate to whatever the risk-free rate was when the model was cached,
    while the Excel workbook recomputes CAPM from today's rf/beta/ERP — the two
    would disagree with no visible cause.

    period= pins the lookup to one period. Required for period-varying drivers:
    without it a five-year tax-rate fade resolves to the FIRST year, so the
    after-tax cost of debt in WACC is struck at FY27 while the DCF discounts at
    the terminal rate.
    """
    if period is not None:
        for a in assumptions:
            if a.driver_key != driver_key or a.period != period:
                continue
            if only_overrides and a.type != "user_override":
                continue
            if a.scenario == scenario:
                return a.value
        for a in assumptions:
            if a.driver_key != driver_key or a.period != period:
                continue
            if only_overrides and a.type != "user_override":
                continue
            if a.scenario == "base":
                return a.value

    for a in assumptions:
        if a.driver_key != driver_key:
            continue
        if only_overrides and a.type != "user_override":
            continue
        if a.scenario == scenario:
            return a.value
    for a in assumptions:
        if a.driver_key != driver_key:
            continue
        if only_overrides and a.type != "user_override":
            continue
        if a.scenario == "base":
            return a.value
    return default


def compute_wacc(
    assumptions: List[AssumptionObject],
    debt_schedule: Optional[DebtSchedule] = None,
    share_count_schedule: Optional[ShareCountSchedule] = None,
    scenario: str = "base",
    current_share_price: Optional[float] = None,
    risk_free_rate: Optional[float] = None,
    beta: Optional[float] = None,
    equity_risk_premium: Optional[float] = None,
    debt_cr: float = 0.0,
    company_id: str = "infy_infy",
    market: Optional[str] = None,
    latest_period: Optional[str] = None,
) -> WACCBreakdown:
    """Compute WACC breakdown generically and market-aware for a given scenario.

    Inputs are resolved via market_data provider (live fetch -> registry -> per-market defaults)
    and stored with full provenance notes.
    """
    # Fetch market data for company
    mdata = get_company_market_data(company_id, market=market)  # type: ignore

    # 1. Cost of Equity (CAPM) with Blume's Adjusted Beta
    rfr = risk_free_rate if risk_free_rate is not None else mdata.risk_free_rate.value
    raw_b = beta if beta is not None else mdata.beta.value
    # Blume (1971): raw betas are biased high, so shrink toward the market beta
    # of 1.0. This is the ONLY place the adjustment is applied — the market-data
    # provider publishes the raw provider beta so the two shrinks cannot compose.
    # An explicit analyst override passes through untouched.
    blume_applied = beta is None
    b = round(0.67 * raw_b + 0.33, 3) if blume_applied else raw_b
    beta_adjustment = (
        "Blume adjusted toward the market: 0.67 x "
        f"{raw_b:.2f} + 0.33 x 1.00 = {b:.2f}. Raw published betas are biased high."
        if blume_applied else ""
    )
    erp = equity_risk_premium if equity_risk_premium is not None else mdata.equity_risk_premium.value

    # Only an ANALYST override may pin the cost of equity. The model_generated
    # value is a CAPM snapshot taken when the model was cached, so honouring it
    # would freeze the discount rate against a risk-free rate that has since
    # moved — and would contradict the live CAPM chain the Excel workbook shows.
    ke_override = _get_assumption_val(
        assumptions, "wacc.cost_of_equity", scenario, None, only_overrides=True
    )
    if ke_override is not None:
        cost_of_equity = ke_override
    else:
        cost_of_equity = rfr + (b * erp)

    # 2. Cost of Debt
    pre_tax_cost_of_debt = _get_assumption_val(assumptions, "wacc.cost_of_debt", scenario, None)
    if (pre_tax_cost_of_debt is None or pre_tax_cost_of_debt == 0.0) and debt_schedule is not None:
        pre_tax_cost_of_debt = debt_schedule.interest_rate
    if pre_tax_cost_of_debt is None:
        pre_tax_cost_of_debt = 0.0

    # A measured rate of 0% is not a rate. The carrying rate is taken from the
    # company's own finance cost over its own debt, and a company that does not
    # break that cost out of its income statement yields no rate to measure — so
    # the measurement came back as zero and the workbook published "Pre-Tax Cost
    # of Debt 0.00%" beside a debt balance in the tens of billions. Zero is not
    # defensible in either direction: it is not what the company pays, and it
    # understates WACC by the whole after-tax cost of the debt.
    #
    # Where the rate is unmeasurable and debt is outstanding, the floor is the
    # company's OWN sovereign yield, already sourced for the risk-free rate. No
    # borrower pays less than the long bond of its own government, so this is the
    # one bound that is true by construction rather than assumed, and it comes
    # from the same market the rest of the discount rate does. It is an estimate
    # and is labelled as one on the page; it is not presented as measured.
    cost_of_debt_is_estimated = False
    if not pre_tax_cost_of_debt and debt_cr > 0:
        pre_tax_cost_of_debt = max(rfr, MIN_CARRYING_RATE)
        cost_of_debt_is_estimated = True

    # Effective tax rate for the after-tax cost of debt.
    #
    # Two corrections: the rate is taken from the TERMINAL forecast period (the
    # discount rate applies to the whole horizon, not to year one), and the
    # fallback follows the company's own market rather than India's statutory
    # rate being applied to a US filer.
    from backend.constants import statutory_tax_rate
    from backend.models.spec.metadata import resolve_market

    default_tax = statutory_tax_rate(resolve_market(company_id))
    tax_rate = _get_assumption_val(
        assumptions, "tax_rate", scenario, default_tax, period=FORECAST_PERIODS[-1]
    )
    if tax_rate is None:
        tax_rate = default_tax
    cost_of_debt_after_tax = pre_tax_cost_of_debt * (1.0 - tax_rate / 100.0)

    # 3. Capital Weighting
    price = current_share_price if (current_share_price is not None and current_share_price > 0) else mdata.price.value

    shares_val: Optional[float] = None
    if share_count_schedule and share_count_schedule.periods:
        # The schedule is ordered historicals-then-forecast, ascending, so
        # periods[0] is the OLDEST year. Market capitalisation must use the
        # LATEST count — the same one the equity bridge divides by — or the
        # capital weights and the per-share result are computed off two
        # different share counts in one valuation output.
        ordered = sorted(
            share_count_schedule.periods,
            key=lambda p: (len(p), p),
        )
        anchor = latest_period or ordered[-1]
        for candidate in (anchor, *reversed(ordered)):
            shares_val = share_count_schedule.get_diluted(candidate)
            if shares_val:
                break
    if not shares_val or shares_val <= 0:
        shares_val = mdata.shares_outstanding.value

    market_cap_cr = shares_val * price  # Shares (Cr/M) * Price (native) = Market Cap (Cr/M)

    total_capital_cr = market_cap_cr + debt_cr
    if total_capital_cr > 0:
        equity_weight = market_cap_cr / total_capital_cr
        debt_weight = debt_cr / total_capital_cr
    else:
        equity_weight = 1.0
        debt_weight = 0.0

    # 4. Total WACC
    wacc = (equity_weight * cost_of_equity) + (debt_weight * cost_of_debt_after_tax)

    source_notes = (
        f"CAPM: Rfr={rfr:.2f}% ({mdata.risk_free_rate.provenance_note}), "
        f"Beta={b:.2f} ({mdata.beta.provenance_note}"
        + (", Blume-adjusted" if blume_applied else ", analyst-set")
        + f"), ERP={erp:.2f}% ({mdata.equity_risk_premium.provenance_note}). "
        f"Cost of Equity={cost_of_equity:.2f}%"
        + (
            " (analyst override, CAPM shown for reference)"
            if ke_override is not None
            else " = Rf + Beta x ERP"
        )
        + f". Pre-tax Cost of Debt={pre_tax_cost_of_debt:.2f}% (after-tax {cost_of_debt_after_tax:.2f}%). "
        f"Capital Weights: Equity={equity_weight*100:.1f}%, Debt={debt_weight*100:.1f}%."
    )

    return WACCBreakdown(
        risk_free_rate=round(rfr, 4),
        beta=round(b, 4),
        raw_beta=round(raw_b, 4),
        beta_adjusted=blume_applied,
        beta_adjustment=beta_adjustment,
        cost_of_debt_estimated=cost_of_debt_is_estimated,
        equity_risk_premium=round(erp, 4),
        cost_of_equity=round(cost_of_equity, 4),
        pre_tax_cost_of_debt=round(pre_tax_cost_of_debt, 4),
        tax_rate=round(tax_rate, 4),
        cost_of_debt=round(cost_of_debt_after_tax, 4),
        equity_weight=round(equity_weight, 6),
        debt_weight=round(debt_weight, 6),
        wacc=round(wacc, 4),
        source_notes=source_notes,
    )
