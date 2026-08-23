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

from backend.data.providers.market_data import get_company_market_data
from backend.forecast.debt import DebtSchedule
from backend.forecast.share_count import ShareCountSchedule
from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.valuation import WACCBreakdown


def _get_assumption_val(
    assumptions: List[AssumptionObject],
    driver_key: str,
    scenario: str = "base",
    default: Optional[float] = None,
) -> Optional[float]:
    for a in assumptions:
        if a.driver_key == driver_key and a.scenario == scenario:
            return a.value
    for a in assumptions:
        if a.driver_key == driver_key and a.scenario == "base":
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
    # Raw betas are systematically biased high (Blume 1971); shrink toward 1.0 whenever
    # the beta is provider-sourced. An explicit analyst override passes through untouched.
    blume_applied = beta is None
    b = round(0.67 * raw_b + 0.33, 3) if blume_applied else raw_b
    erp = equity_risk_premium if equity_risk_premium is not None else mdata.equity_risk_premium.value

    ke_override = _get_assumption_val(assumptions, "wacc.cost_of_equity", scenario, None)
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

    # Effective tax rate: use the model's assumption when present; otherwise fall back
    # to the market-aware default. The explicit None check (not `or 25.17`) preserves a
    # legitimate 0% tax rate instead of silently overriding it.
    tax_rate = _get_assumption_val(assumptions, "tax_rate", scenario, 25.17)
    if tax_rate is None:
        tax_rate = 25.17
    cost_of_debt_after_tax = pre_tax_cost_of_debt * (1.0 - tax_rate / 100.0)

    # 3. Capital Weighting
    price = current_share_price if (current_share_price is not None and current_share_price > 0) else mdata.price.value

    shares_val: Optional[float] = None
    if share_count_schedule:
        latest_p = share_count_schedule.periods[0] if (share_count_schedule and share_count_schedule.periods) else "FY26"
        shares_val = (
            share_count_schedule.get_diluted(latest_p)
            or share_count_schedule.get_diluted("FY26")
            or share_count_schedule.get_diluted("FY27")
        )
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
        + (", Blume-adjusted" if blume_applied else ", analyst override")
        + f"), ERP={erp:.2f}% ({mdata.equity_risk_premium.provenance_note}). "
        f"Pre-tax Cost of Debt={pre_tax_cost_of_debt:.2f}% (after-tax {cost_of_debt_after_tax:.2f}%). "
        f"Capital Weights: Equity={equity_weight*100:.1f}%, Debt={debt_weight*100:.1f}%."
    )

    return WACCBreakdown(
        risk_free_rate=round(rfr, 4),
        beta=round(b, 4),
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
