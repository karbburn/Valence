from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

ScenarioLabel = Literal["base", "bull", "bear", "custom"]
TerminalValueMethod = Literal["gordon_growth", "exit_multiple"]


class WACCBreakdown(BaseModel):
    """Full WACC computation chain — all inputs exposed so Excel can reconstruct formulas.

    The Excel renderer needs every intermediate value, not just the final WACC figure.
    CAPM is used for the cost of equity.
    """
    risk_free_rate: Optional[float] = None          # % e.g. 7.1 for India 10Y Gsec
    beta: Optional[float] = None
    equity_risk_premium: Optional[float] = None     # country + market ERP, e.g. Damodaran
    cost_of_equity: Optional[float] = None          # CAPM = rfr + beta * erp
    pre_tax_cost_of_debt: Optional[float] = None    # % — ~0 for Infosys
    tax_rate: Optional[float] = None                # % — for after-tax cost of debt
    cost_of_debt: Optional[float] = None            # pre_tax * (1 - tax_rate)
    equity_weight: Optional[float] = None           # mkt_cap / (mkt_cap + debt)
    debt_weight: Optional[float] = None             # debt / (mkt_cap + debt)
    wacc: Optional[float] = None                    # final WACC %
    source_notes: str = ""                          # provenance for rate inputs


class FCFFPeriod(BaseModel):
    """FCFF build-up for a single forecast period — full intermediate chain.

    Formula:
    NOPAT = EBIT × (1 − tax_rate)
    FCFF  = NOPAT + D&A − Capex − ΔWorking Capital

    Each field is a distinct Excel cell in the DCF tab.
    """
    period: str
    ebit: Optional[float] = None
    tax_rate: Optional[float] = None                # %
    nopat: Optional[float] = None                   # EBIT × (1 − tax_rate)
    da: Optional[float] = None
    capex: Optional[float] = None
    delta_working_capital: Optional[float] = None   # increase in WC = cash outflow
    fcff: Optional[float] = None                    # free cash flow to firm
    discount_factor: Optional[float] = None         # 1 / (1 + WACC)^t
    pv_fcff: Optional[float] = None                 # FCFF × discount_factor


class TerminalValue(BaseModel):
    """Terminal value computation — both Gordon Growth and Exit Multiple.

    Both methods are computed and stored side-by-side. The active method determines
    which feeds into the DCF bridge.
    """
    method: TerminalValueMethod = "gordon_growth"
    # Gordon growth inputs
    terminal_growth_rate: Optional[float] = None    # % — must be < WACC (QA check)
    final_year_fcff: Optional[float] = None
    terminal_value_undiscounted: Optional[float] = None   # TV = FCFF_n*(1+g) / (WACC-g)
    # Exit multiple inputs
    exit_multiple: Optional[float] = None           # EV/EBITDA multiple
    final_year_ebitda: Optional[float] = None
    exit_multiple_tv_undiscounted: Optional[float] = None  # ebitda * multiple
    # Shared discount
    discount_factor: Optional[float] = None
    terminal_value_pv: Optional[float] = None       # discounted to time-0
    tv_pct_of_ev: Optional[float] = None            # % of total EV — sanity gauge


class DCFBridge(BaseModel):
    """EV → Equity Value → Implied Share Price bridge — full arithmetic chain.

    Exposing every step here lets check logic verify the arithmetic exactly.
    """
    sum_pv_fcff: Optional[float] = None
    pv_terminal_value: Optional[float] = None
    enterprise_value: Optional[float] = None        # sum_pv_fcff + pv_terminal_value
    less_net_debt: Optional[float] = None           # debt - cash; negative = net cash
    equity_value: Optional[float] = None            # EV - net_debt
    shares_outstanding: Optional[float] = None      # diluted, in units
    implied_share_price: Optional[float] = None     # equity_value / shares


class ReverseDCF(BaseModel):
    """Reverse DCF: given market price, solve for implied growth/margins."""
    market_price: Optional[float] = None
    implied_terminal_growth: Optional[float] = None     # % solved for
    implied_revenue_cagr: Optional[float] = None        # alternative solve
    method_note: str = ""                               # which variable was solved for


class SensitivityTable(BaseModel):
    """Two-variable sensitivity grid — computed by re-running the DCF engine at each point.

    Values are NOT interpolated — each cell is a genuine DCF run. The results_grid
    is an NxM matrix indexed by row/col indices.
    """
    row_driver: str                             # e.g. "wacc.wacc"
    col_driver: str                             # e.g. "terminal_growth_rate"
    row_values: List[float]                     # e.g. [8.0, 9.0, 10.0, 11.0, 12.0]
    col_values: List[float]                     # e.g. [3.0, 4.0, 5.0, 6.0, 7.0]
    results_grid: List[List[Optional[float]]]   # NxM — implied share prices


class ValuationOutput(BaseModel):
    """Complete valuation output for one scenario.

    Stores the full intermediate chain so the Excel renderer can
    reconstruct live formulas — not just paste EV and share price.
    """
    scenario: ScenarioLabel
    wacc: WACCBreakdown = WACCBreakdown()
    fcff_by_period: List[FCFFPeriod] = []
    terminal_value: TerminalValue = TerminalValue()
    dcf_bridge: DCFBridge = DCFBridge()
    reverse_dcf: ReverseDCF = ReverseDCF()
    sensitivity_tables: List[SensitivityTable] = []

    class Config:
        pass
