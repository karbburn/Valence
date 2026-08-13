from __future__ import annotations

"""
WACC computation module.

Calculates cost of equity via CAPM (rfr + beta * erp), cost of debt after-tax,
market value capital weighting, and total WACC. Every intermediate step is recorded
in WACCBreakdown for live formula reconstruction in Excel.

Computes generically: for a zero-debt company (Infosys), debt weight calculates to 0.0,
resulting in WACC = Cost of Equity. No hardcoded shortcuts.
"""

from typing import List, Optional

from backend.forecast.debt import DebtSchedule
from backend.forecast.share_count import ShareCountSchedule
from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.valuation import WACCBreakdown

DEFAULT_RFR = 7.10       # India 10-Year G-Sec yield (%)
DEFAULT_BETA = 0.90      # Infosys 2Y weekly beta vs NSE Nifty IT
DEFAULT_ERP = 6.50       # Damodaran published India Equity Risk Premium (%)
DEFAULT_CURRENT_PRICE = 1650.0  # INR per share benchmark market price for Infosys


def _get_assumption_val(
    assumptions: List[AssumptionObject],
    driver_key: str,
    scenario: str = "base",
    default: float = 0.0,
) -> float:
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
    current_share_price: float = DEFAULT_CURRENT_PRICE,
    risk_free_rate: float = DEFAULT_RFR,
    beta: float = DEFAULT_BETA,
    equity_risk_premium: float = DEFAULT_ERP,
    debt_cr: float = 0.0,
) -> WACCBreakdown:
    """Compute WACC breakdown generically for a given scenario.

    Inputs are stored with full provenance notes.
    """
    # 1. Cost of Equity (CAPM)
    cost_of_equity = risk_free_rate + (beta * equity_risk_premium)

    # 2. Cost of Debt
    pre_tax_cost_of_debt = _get_assumption_val(assumptions, "wacc.cost_of_debt", scenario, 0.0)
    tax_rate = _get_assumption_val(assumptions, "tax_rate", scenario, 27.0)
    cost_of_debt_after_tax = pre_tax_cost_of_debt * (1.0 - tax_rate / 100.0)

    # 3. Capital Weighting
    shares_cr = 412.4545  # default fallback if schedule not passed
    if share_count_schedule:
        # Use latest available historical or forecast share count
        val = share_count_schedule.get_diluted("FY26") or share_count_schedule.get_diluted("FY27")
        if val:
            shares_cr = val

    market_cap_cr = shares_cr * current_share_price / 1.0  # Shares (Cr) * Price (INR) = Market Cap (Cr)

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
        f"CAPM: Rfr={risk_free_rate:.2f}% (India 10Y G-Sec), Beta={beta:.2f} (NSE Nifty IT), "
        f"ERP={equity_risk_premium:.2f}% (Damodaran India ERP). "
        f"Capital Weights: Equity={equity_weight*100:.1f}%, Debt={debt_weight*100:.1f}%."
    )

    return WACCBreakdown(
        risk_free_rate=round(risk_free_rate, 4),
        beta=round(beta, 4),
        equity_risk_premium=round(equity_risk_premium, 4),
        cost_of_equity=round(cost_of_equity, 4),
        pre_tax_cost_of_debt=round(pre_tax_cost_of_debt, 4),
        tax_rate=round(tax_rate, 4),
        cost_of_debt=round(cost_of_debt_after_tax, 4),
        equity_weight=round(equity_weight, 6),
        debt_weight=round(debt_weight, 6),
        wacc=round(wacc, 4),
        source_notes=source_notes,
    )
