from __future__ import annotations

from typing import List

from pydantic import BaseModel


class DriverDefinition(BaseModel):
    """Defines a driver that feeds into the forecast and valuation engine.

    Every driver listed here must flow through the full chain:
    Driver → 3 statements → FCFF → EV → Equity Value → Implied Share Price.
    No driver is a dead-end UI control.
    """
    driver_key: str                         # unique key, e.g. "revenue_growth"
    display_name: str                       # human-readable, for renderers only
    feeds_canonical_keys: List[str]         # which canonical keys this driver populates
    applicable_periods: List[str]           # e.g. ["FY27","FY28","FY29","FY30","FY31"]
    unit: str = "%"                         # "%" | "days" | "x" | "INR" etc.
    description: str = ""


# Driver registry.
FORECAST_PERIODS = ["FY27", "FY28", "FY29", "FY30", "FY31"]

V1_DRIVERS: List[DriverDefinition] = [
    DriverDefinition(
        driver_key="revenue_growth",
        display_name="Revenue Growth Rate",
        feeds_canonical_keys=["canonical.is.revenue"],
        applicable_periods=FORECAST_PERIODS,
        unit="%",
        description="YoY revenue growth applied to prior period revenue.",
    ),
    DriverDefinition(
        driver_key="ebitda_margin",
        display_name="EBITDA Margin %",
        feeds_canonical_keys=["canonical.is.ebitda", "canonical.is.operating_profit"],
        applicable_periods=FORECAST_PERIODS,
        unit="%",
        description="EBITDA as % of revenue.",
    ),
    DriverDefinition(
        driver_key="ebit_margin",
        display_name="EBIT / Operating Profit Margin %",
        feeds_canonical_keys=["canonical.is.operating_profit"],
        applicable_periods=FORECAST_PERIODS,
        unit="%",
        description="EBIT as % of revenue. Implied by EBITDA margin minus D&A % revenue.",
    ),
    DriverDefinition(
        driver_key="da_pct_revenue",
        display_name="D&A % of Revenue",
        feeds_canonical_keys=["canonical.is.depreciation_amortization"],
        applicable_periods=FORECAST_PERIODS,
        unit="%",
        description="Depreciation & amortization as % of revenue.",
    ),
    DriverDefinition(
        driver_key="tax_rate",
        display_name="Effective Tax Rate %",
        feeds_canonical_keys=["canonical.is.tax"],
        applicable_periods=FORECAST_PERIODS,
        unit="%",
        description="Income tax expense as % of PBT.",
    ),
    DriverDefinition(
        driver_key="dso_days",
        display_name="Days Sales Outstanding (DSO)",
        feeds_canonical_keys=["canonical.bs.trade_receivables", "canonical.bs.unbilled_revenue"],
        applicable_periods=FORECAST_PERIODS,
        unit="days",
        description="(Trade receivables + unbilled revenue) / Revenue × 365.",
    ),
    DriverDefinition(
        driver_key="dio_days",
        display_name="Days Inventory Outstanding (DIO)",
        feeds_canonical_keys=["canonical.bs.inventory"],
        applicable_periods=FORECAST_PERIODS,
        unit="days",
        description="Inventory / Cost of Sales × 365. Zero for services companies; material for manufacturing.",
    ),
    DriverDefinition(
        driver_key="dpo_days",
        display_name="Days Payables Outstanding (DPO)",
        feeds_canonical_keys=["canonical.bs.trade_payables"],
        applicable_periods=FORECAST_PERIODS,
        unit="days",
        description="Trade payables / Cost of sales × 365.",
    ),
    DriverDefinition(
        driver_key="capex_pct_revenue",
        display_name="Capex % of Revenue",
        feeds_canonical_keys=["canonical.cf.capex", "canonical.cf.investing_activities"],
        applicable_periods=FORECAST_PERIODS,
        unit="%",
        description="Capital expenditure as % of revenue. Drives the canonical.cf.capex line item (the investing-activities line also reflects net other investing flows).",
    ),
    DriverDefinition(
        driver_key="debt_repayment",
        display_name="Debt Repayment / Drawdown (INR Cr)",
        feeds_canonical_keys=["canonical.bs.borrowings"],
        applicable_periods=FORECAST_PERIODS,
        unit="INR",
        description="Net change in borrowings. ~0 when the company carries no forecast debt; present for generality.",
    ),
    DriverDefinition(
        driver_key="wacc.cost_of_equity",
        display_name="Cost of Equity (CAPM) %",
        feeds_canonical_keys=[],
        applicable_periods=["all"],
        unit="%",
        description="Risk-free rate + beta × equity risk premium (CAPM).",
    ),
    DriverDefinition(
        driver_key="wacc.cost_of_debt",
        display_name="Pre-tax Cost of Debt %",
        feeds_canonical_keys=[],
        applicable_periods=["all"],
        unit="%",
        description="Pre-tax cost of debt. Falls back to the debt schedule interest rate when unset.",
    ),
    DriverDefinition(
        driver_key="terminal_growth_rate",
        display_name="Terminal Growth Rate (Gordon Growth) %",
        feeds_canonical_keys=[],
        applicable_periods=["terminal"],
        unit="%",
        description="Perpetuity growth rate. Must be < WACC (QA check).",
    ),
    DriverDefinition(
        driver_key="exit_ev_multiple",
        display_name="Exit EV/EBITDA Multiple (x)",
        feeds_canonical_keys=[],
        applicable_periods=["terminal"],
        unit="x",
        description="Alternative terminal value via exit multiple.",
    ),
]
