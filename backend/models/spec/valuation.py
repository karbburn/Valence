from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ScenarioLabel = Literal["base", "bull", "bear", "custom"]
TerminalValueMethod = Literal["gordon_growth", "exit_multiple"]


class WACCBreakdown(BaseModel):
    """Full WACC computation chain — all inputs exposed so Excel can reconstruct formulas.

    The Excel renderer needs every intermediate value, not just the final WACC figure.
    CAPM is used for the cost of equity.
    """
    risk_free_rate: Optional[float] = None          # % e.g. 7.1 for India 10Y Gsec
    beta: Optional[float] = None                   # the beta actually USED
    # The beta as published, before any adjustment, and whether one was applied.
    #
    # `beta` alone is not enough to describe itself. A Blume-adjusted beta is
    # defensible, but publishing 1.449 under a note crediting a source that says
    # 1.67 leaves a reader checking the page against the source and finding a
    # discrepancy with nothing on the sheet to explain it. Carrying the raw value
    # and the flag lets the workbook show both figures and name the method.
    raw_beta: Optional[float] = None                # before adjustment
    beta_adjusted: bool = False                     # True when Blume was applied
    beta_adjustment: str = ""                       # the method, in words
    equity_risk_premium: Optional[float] = None     # country + market ERP, e.g. Damodaran
    cost_of_equity: Optional[float] = None          # CAPM = rfr + beta * erp
    pre_tax_cost_of_debt: Optional[float] = None    # % — debt schedule rate (after-tax applied)
    tax_rate: Optional[float] = None                # % — for after-tax cost of debt
    cost_of_debt: Optional[float] = None            # pre_tax * (1 - tax_rate)
    # True when no cost of debt could be measured for this company and the
    # published rate is a floor rather than an observation. A rate of zero is
    # never published against an outstanding borrowing: it is not what the
    # company pays and it understates the discount rate by the whole after-tax
    # cost of the debt. The workbook must say which of the two it is showing.
    cost_of_debt_estimated: bool = False
    equity_weight: Optional[float] = None           # mkt_cap / (mkt_cap + debt)
    debt_weight: Optional[float] = None             # debt / (mkt_cap + debt)
    wacc: Optional[float] = None                    # final WACC %
    source_notes: str = ""                          # provenance for rate inputs


class FCFFPeriod(BaseModel):
    """FCFF build-up for a single forecast period — full intermediate chain.

    Formula:
    NOPAT = EBIT × (1 − tax_rate)
    FCFF  = NOPAT + D&A − Capex − ΔWorking Capital − Stock Compensation

    Each field is a distinct Excel cell in the DCF tab.
    """
    period: str
    ebit: Optional[float] = None
    tax_rate: Optional[float] = None                # %
    nopat: Optional[float] = None                   # EBIT × (1 − tax_rate)
    da: Optional[float] = None
    capex: Optional[float] = None
    delta_working_capital: Optional[float] = None   # increase in WC = cash outflow
    stock_compensation: Optional[float] = None      # SBC treated as a cash operating cost
    fcff: Optional[float] = None                    # free cash flow to firm
    discount_factor: Optional[float] = None         # 1 / (1 + WACC)^(t - 0.5) for mid-year
    pv_fcff: Optional[float] = None                 # FCFF × discount_factor
    timing_convention: Literal["mid_year", "end_year"] = "mid_year"


class TerminalValue(BaseModel):
    """Terminal value computation — both Gordon Growth and Exit Multiple.

    Both methods are computed and stored side-by-side. The active method determines
    which feeds into the DCF bridge.
    """
    method: TerminalValueMethod = "gordon_growth"
    timing_convention: Literal["mid_year", "end_year"] = "mid_year"
    # Gordon growth inputs
    terminal_growth_rate: Optional[float] = None    # % — must be < WACC (QA check)
    final_year_fcff: Optional[float] = None
    terminal_value_undiscounted: Optional[float] = None   # TV = FCFF_n*(1+g) / (WACC-g)
    # Quality & Reinvestment Metrics
    terminal_nopat: Optional[float] = None          # EBIT_5 * (1+g) * (1 - tax)
    reinvestment_rate: Optional[float] = None       # % — Reinvestment / Terminal NOPAT
    implied_roic: Optional[float] = None            # % — g / Reinvestment Rate
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
    # Comprehensive Non-Operating Components
    cash_and_equivalents: Optional[float] = None    # cash & bank
    marketable_securities: Optional[float] = None   # current investments
    non_current_investments: Optional[float] = None # LT financial investments / equity stakes
    total_debt: Optional[float] = None              # total interest-bearing debt
    operating_lease_liabilities: Optional[float] = None  # shown, not deducted (see note)
    minority_interest: Optional[float] = None       # non-controlling interests
    preferred_stock: Optional[float] = None         # preferred equity
    # Redeemable preferred and redeemable noncontrolling interest: a claim
    # ranking ahead of common equity, so it is deducted before the implied share
    # price is computed.
    mezzanine_equity: Optional[float] = None

    # Any further claim class declared in `backend.valuation.claims` that has no
    # field of its own here. Without this, a claim added to the declaration would be
    # deducted from enterprise value and then vanish: the workbook, the frontend and
    # the export self-check all read named fields, so they would each show zero for a
    # charge the bridge had genuinely applied. The regression test found exactly
    # that, which is why this exists rather than another explicit field.
    other_claims: Dict[str, float] = Field(default_factory=dict)
    less_net_debt: Optional[float] = None           # (Debt + NCI + Pref) - (Cash + MktSec + NonCurrInv)
    equity_value: Optional[float] = None            # EV - less_net_debt
    shares_outstanding: Optional[float] = None      # diluted, in units
    implied_share_price: Optional[float] = None     # equity_value / shares

    # Date of the balance sheet the bridge was struck on, and how it was
    # obtained. A net debt figure without its date is unreadable: the same
    # company at the same price carries a different enterprise value depending
    # on whether the balance sheet is three months old or two years old, and
    # that is exactly the difference a reader cannot see unless it is published.
    balance_sheet_as_of: Optional[str] = None       # ISO date or period label
    balance_sheet_source: Optional[str] = None      # reported_quarter | filed_annual_balance_sheet
    debt_basis_note: Optional[str] = None           # what counts as debt, in words

    # Whether `marketable_securities` is a REPORTED balance or a residual, and how
    # the residual was struck.
    #
    # When a feed does not break short-term investments out of its liquid-assets
    # total, the platform takes the difference between that total and cash so the
    # liquid-assets figure still reconciles. That difference is not a measured
    # balance of investments — it is whatever the feed folded into the total and
    # did not name. Publishing it under the label "Marketable Securities" claims
    # a filing was read that never was, and it is a figure a reader checking
    # against the accounts will not find. When it is a residual the line says so
    # and shows the arithmetic.
    marketable_securities_derived: bool = False
    marketable_securities_derivation: str = ""


class ReverseDCF(BaseModel):
    """Reverse DCF: given market price, solve for implied growth/margins."""
    market_price: Optional[float] = None
    market_price_date: Optional[str] = None       # fetch date of the market quote (ISO)
    market_price_source: Optional[str] = None     # yfinance | twelvedata | registry | stale_cache:* | market_default
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
    timing_convention: Literal["mid_year", "end_year"] = "mid_year"
    wacc: WACCBreakdown = WACCBreakdown()
    fcff_by_period: List[FCFFPeriod] = []
    terminal_value: TerminalValue = TerminalValue()
    dcf_bridge: DCFBridge = DCFBridge()
    reverse_dcf: ReverseDCF = ReverseDCF()
    sensitivity_tables: List[SensitivityTable] = []

    class Config:
        pass
