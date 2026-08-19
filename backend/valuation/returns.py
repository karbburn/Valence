from __future__ import annotations

"""
Investment Returns & PE Exit Analysis Module.

Calculates prospective 3-year and 5-year investment returns for financial sponsors,
M&A professionals, and institutional fund managers:
  - Year 3 & Year 5 Exit Enterprise Value & Equity Value
  - Equity IRR (%) and MoIC (Multiple on Invested Capital)
  - 2D Returns Sensitivity Matrix (Entry Price vs Exit Multiple)
"""

from typing import Dict, List
from pydantic import BaseModel, Field


class ExitScenarioReturn(BaseModel):
    scenario: str
    exit_year: str
    exit_ebitda: float
    exit_multiple: float
    exit_ev: float
    projected_net_debt: float
    exit_equity_value: float
    entry_equity_value: float
    cumulative_dividends: float
    moic: float
    equity_irr_pct: float


class ReturnsMatrixCell(BaseModel):
    entry_price: float
    exit_multiple: float
    irr_pct: float
    moic: float


class InvestmentReturnsAnalysis(BaseModel):
    entry_share_price: float
    entry_equity_value: float
    exit_scenarios: List[ExitScenarioReturn]
    returns_matrix: List[List[ReturnsMatrixCell]]


def compute_investment_returns(
    entry_price: float,
    shares_outstanding: float,
    ebitda_fy29: float,
    ebitda_fy31: float,
    net_debt_fy29: float,
    net_debt_fy31: float,
    base_exit_multiple: float = 18.0,
    cumulative_dividends_5y: float = 0.0,
) -> InvestmentReturnsAnalysis:
    """Compute 3-year and 5-year PE / LBO exit returns and IRR waterfall."""
    ep = max(0.01, entry_price)
    sh = max(1.0, shares_outstanding)
    entry_eq = ep * sh

    # Scenarios: Base, Bull, Bear across 3Y and 5Y
    exit_cases = [
        # 3-Year Exit (FY29)
        {"scenario": "Base Case (3-Year Exit)", "yr": "FY29", "ebitda": ebitda_fy29, "mult": base_exit_multiple, "nd": net_debt_fy29, "years": 3, "divs": cumulative_dividends_5y * 0.5},
        {"scenario": "Bull Case (3-Year Exit)", "yr": "FY29", "ebitda": ebitda_fy29 * 1.10, "mult": base_exit_multiple + 2.5, "nd": net_debt_fy29, "years": 3, "divs": cumulative_dividends_5y * 0.5},
        {"scenario": "Bear Case (3-Year Exit)", "yr": "FY29", "ebitda": ebitda_fy29 * 0.90, "mult": base_exit_multiple - 2.5, "nd": net_debt_fy29, "years": 3, "divs": cumulative_dividends_5y * 0.5},
        # 5-Year Exit (FY31)
        {"scenario": "Base Case (5-Year Exit)", "yr": "FY31", "ebitda": ebitda_fy31, "mult": base_exit_multiple, "nd": net_debt_fy31, "years": 5, "divs": cumulative_dividends_5y},
        {"scenario": "Bull Case (5-Year Exit)", "yr": "FY31", "ebitda": ebitda_fy31 * 1.15, "mult": base_exit_multiple + 3.0, "nd": net_debt_fy31, "years": 5, "divs": cumulative_dividends_5y * 1.2},
        {"scenario": "Bear Case (5-Year Exit)", "yr": "FY31", "ebitda": ebitda_fy31 * 0.85, "mult": base_exit_multiple - 3.0, "nd": net_debt_fy31, "years": 5, "divs": cumulative_dividends_5y * 0.8},
    ]

    scenarios_out: List[ExitScenarioReturn] = []
    for c in exit_cases:
        exit_ev = c["ebitda"] * c["mult"]
        exit_eq = max(0.0, exit_ev - c["nd"])
        divs = c["divs"]
        total_proceeds = exit_eq + divs
        moic = total_proceeds / entry_eq if entry_eq > 0 else 0.0
        irr = (moic ** (1.0 / c["years"]) - 1.0) * 100.0 if moic > 0 else -100.0

        scenarios_out.append(
            ExitScenarioReturn(
                scenario=c["scenario"],
                exit_year=c["yr"],
                exit_ebitda=round(c["ebitda"], 2),
                exit_multiple=round(c["mult"], 1),
                exit_ev=round(exit_ev, 2),
                projected_net_debt=round(c["nd"], 2),
                exit_equity_value=round(exit_eq, 2),
                entry_equity_value=round(entry_eq, 2),
                cumulative_dividends=round(divs, 2),
                moic=round(moic, 2),
                equity_irr_pct=round(irr, 2),
            )
        )

    # 2D Returns Matrix: Entry Price (±20%) vs Exit Multiple (±4.0x)
    entry_prices = [ep * 0.80, ep * 0.90, ep, ep * 1.10, ep * 1.20]
    exit_multiples = [base_exit_multiple - 4.0, base_exit_multiple - 2.0, base_exit_multiple, base_exit_multiple + 2.0, base_exit_multiple + 4.0]

    matrix: List[List[ReturnsMatrixCell]] = []
    for p_in in entry_prices:
        row: List[ReturnsMatrixCell] = []
        eq_in = p_in * sh
        for m_out in exit_multiples:
            ev_out = ebitda_fy31 * m_out
            eq_out = max(0.0, ev_out - net_debt_fy31)
            moic_val = (eq_out + cumulative_dividends_5y) / eq_in if eq_in > 0 else 0.0
            irr_val = (moic_val ** 0.20 - 1.0) * 100.0 if moic_val > 0 else -100.0
            row.append(
                ReturnsMatrixCell(
                    entry_price=round(p_in, 2),
                    exit_multiple=round(m_out, 1),
                    irr_pct=round(irr_val, 2),
                    moic=round(moic_val, 2),
                )
            )
        matrix.append(row)

    return InvestmentReturnsAnalysis(
        entry_share_price=round(ep, 2),
        entry_equity_value=round(entry_eq, 2),
        exit_scenarios=scenarios_out,
        returns_matrix=matrix,
    )
