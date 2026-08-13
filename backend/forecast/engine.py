from __future__ import annotations

"""
Forecast Engine: period-by-period 3-statement roll-forward.

Build order per period (each column is independent given prior-period actuals):
  1. Revenue
  2. EBITDA, EBIT (operating_profit), D&A
  3. Other income, Finance cost (carried forward from last historical)
  4. PBT = EBIT + other_income − finance_cost
  5. Tax = PBT × tax_rate
  6. Net Profit = PBT − Tax
    7. Working capital: trade_receivables (DSO), inventory (DIO), trade_payables (DPO)
  8. Capex
  9. Operating CF = Net Profit + D&A − ΔWWC
 10. Balance sheet: non-cash assets grown by capex−D&A; equity grown by retained profit;
     cash is the plug (assets = liabilities + equity by construction).

Balance sheet closure convention:
  - Total assets = prior total assets + capex − D&A + Δ_working_capital_assets
  - Total equity = prior equity + net_profit − dividends_est
  - Cash = total_assets − (total_assets − cash_and_bank) → solved as plug
"""

from datetime import date
from typing import Dict, List, Optional

from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.forecast import FORECAST_PERIODS, Forecast, ForecastLineItem


def _yr(period_label: str) -> int:
    yr = period_label[2:]
    return 2000 + int(yr) if len(yr) == 2 else int(yr)


def _get(assumptions: List[AssumptionObject], driver_key: str, period: str, scenario: str) -> Optional[float]:
    """Return the assumption value for a driver/period/scenario, falling back to 'all'."""
    for a in assumptions:
        if a.driver_key == driver_key and a.period == period and a.scenario == scenario:
            return a.value
    for a in assumptions:
        if a.driver_key == driver_key and a.period == "all" and a.scenario == scenario:
            return a.value
    return None


def _item(canonical_key: str, period: str, value: float, scenario: str, driver_key: Optional[str] = None) -> ForecastLineItem:
    return ForecastLineItem(
        canonical_key=canonical_key,
        period_label=period,
        period_end_date=date(_yr(period), 3, 31),
        value=round(value, 2),
        scenario=scenario,
        driver_key=driver_key,
    )


def run_forecast(
    assumptions: List[AssumptionObject],
    historical_model,
    scenario: str,
) -> Forecast:
    """Run 3-statement roll-forward for a single scenario across 5 forecast periods."""

    items: List[ForecastLineItem] = []

    # Seed prior-period values from last historical (FY26)
    hist_is = historical_model.income_statement
    hist_bs = historical_model.balance_sheet
    hist_cf = historical_model.cash_flow_statement

    prior_rev = hist_is.get_value("canonical.is.revenue", "FY26") or 0.0
    prior_total_assets = hist_bs.get_value("canonical.bs.total_assets", "FY26") or 0.0
    prior_total_equity = hist_bs.get_value("canonical.bs.total_equity", "FY26") or 0.0
    prior_trade_rec = (
        (hist_bs.get_value("canonical.bs.trade_receivables", "FY26") or 0.0) +
        (hist_bs.get_value("canonical.bs.unbilled_revenue", "FY26") or 0.0)
    )
    prior_trade_pay = hist_bs.get_value("canonical.bs.trade_payables", "FY26") or 0.0
    prior_ppe = hist_bs.get_value("canonical.bs.ppe", "FY26") or 0.0
    prior_cash = hist_bs.get_value("canonical.bs.cash_and_bank", "FY26") or 0.0

    # Carry forward quasi-stable items from FY26
    other_income = hist_is.get_value("canonical.is.other_income", "FY26") or 4000.0
    finance_cost = hist_is.get_value("canonical.is.finance_cost", "FY26") or 416.0
    other_income_pct_rev = (other_income / prior_rev * 100.0) if prior_rev > 0 else 4.0
    finance_cost_pct_rev = (finance_cost / prior_rev * 100.0) if prior_rev > 0 else 0.4

    # Compute historical gross margin from FY26 (or default to 30% for services)
    hist_gp = hist_is.get_value("canonical.is.gross_profit", "FY26")
    hist_rev = hist_is.get_value("canonical.is.revenue", "FY26")
    gross_margin_hist = (hist_gp / hist_rev * 100.0) if (hist_gp and hist_rev and hist_rev > 0) else 30.0

    # Compute historical dividend payout ratio from FY26
    hist_div = hist_cf.get_value("canonical.cf.dividends_paid", "FY26") if hasattr(hist_cf, 'get_value') else None
    hist_np = hist_is.get_value("canonical.is.net_profit", "FY26")
    dividend_payout_pct = abs(hist_div / hist_np) if (hist_div and hist_np and hist_np > 0) else 0.65

    for period in FORECAST_PERIODS:
        # --- Driver lookups ---
        rev_growth = _get(assumptions, "revenue_growth", period, scenario) or 10.0
        ebitda_margin = _get(assumptions, "ebitda_margin", period, scenario) or 23.0
        ebit_margin = _get(assumptions, "ebit_margin", period, scenario) or 20.0
        da_pct_rev = _get(assumptions, "da_pct_revenue", period, scenario) or 2.9
        tax_rate = _get(assumptions, "tax_rate", period, scenario) or 25.17
        dso = _get(assumptions, "dso_days", period, scenario) or 100.0
        dio = _get(assumptions, "dio_days", period, scenario) or 0.0
        dpo = _get(assumptions, "dpo_days", period, scenario) or 14.0
        capex_pct = _get(assumptions, "capex_pct_revenue", period, scenario) or 2.5

        # --- Income Statement ---
        revenue = prior_rev * (1.0 + rev_growth / 100.0)
        ebitda = revenue * ebitda_margin / 100.0
        da = revenue * da_pct_rev / 100.0
        ebit = revenue * ebit_margin / 100.0       # operating_profit

        # PBT = EBIT + other_income − finance_cost (Infosys structure)
        # Grow other_income and finance_cost as % of revenue (not held flat)
        period_other_income = revenue * other_income_pct_rev / 100.0
        period_finance_cost = revenue * finance_cost_pct_rev / 100.0
        pbt = ebit + period_other_income - period_finance_cost
        tax = pbt * tax_rate / 100.0
        net_profit = pbt - tax

        # Cost of sales implied from EBIT margin (cost_of_sales ≈ revenue − gross_profit)
        # Use: cost_of_sales = revenue − ebitda (simplified; holds when opex ≈ small)
        # More accurate: cost_of_sales = revenue − gross_profit.
        # Gross profit not directly driven; estimate from historical gross margin
        cost_of_sales = revenue * (1.0 - gross_margin_hist / 100.0)
        gross_profit = revenue - cost_of_sales

        items.append(_item("canonical.is.revenue", period, revenue, scenario, "revenue_growth"))
        items.append(_item("canonical.is.ebitda", period, ebitda, scenario, "ebitda_margin"))
        items.append(_item("canonical.is.operating_profit", period, ebit, scenario, "ebit_margin"))
        items.append(_item("canonical.is.depreciation_amortization", period, da, scenario, "da_pct_revenue"))
        items.append(_item("canonical.is.cost_of_sales", period, cost_of_sales, scenario, None))
        items.append(_item("canonical.is.gross_profit", period, gross_profit, scenario, None))
        items.append(_item("canonical.is.other_income", period, period_other_income, scenario, None))
        items.append(_item("canonical.is.finance_cost", period, period_finance_cost, scenario, None))
        items.append(_item("canonical.is.pbt", period, pbt, scenario, None))
        items.append(_item("canonical.is.tax", period, tax, scenario, "tax_rate"))
        items.append(_item("canonical.is.net_profit", period, net_profit, scenario, None))

        # --- Working Capital (Balance Sheet) ---
        trade_receivables = revenue * dso / 365.0
        inventory = cost_of_sales * dio / 365.0 if dio > 0 else 0.0
        trade_payables = cost_of_sales * dpo / 365.0

        # PPE: prior PPE + capex − D&A
        capex = revenue * capex_pct / 100.0
        ppe = max(0.0, prior_ppe + capex - da)

        items.append(_item("canonical.bs.trade_receivables", period, trade_receivables, scenario, "dso_days"))
        items.append(_item("canonical.bs.inventory", period, inventory, scenario, "dio_days"))
        items.append(_item("canonical.bs.trade_payables", period, trade_payables, scenario, "dpo_days"))
        items.append(_item("canonical.bs.ppe", period, ppe, scenario, None))

        # --- Cash Flow ---
        prior_inventory = 0.0  # FY26 inventory not tracked in prior anchors; use 0 for services companies
        delta_wc = (
            (trade_receivables - prior_trade_rec)
            + (inventory - prior_inventory)
            - (trade_payables - prior_trade_pay)
        )
        operating_cf = net_profit + da - delta_wc
        investing_cf = -capex  # capex outflow

        items.append(_item("canonical.cf.operating_activities", period, operating_cf, scenario, None))
        items.append(_item("canonical.cf.investing_activities", period, investing_cf, scenario, "capex_pct_revenue"))

        # --- Balance Sheet Closure ---
        # Equity grows by retained profit (net_profit − estimated dividends)
        dividends_est = net_profit * dividend_payout_pct
        total_equity = prior_total_equity + net_profit - dividends_est

        # Non-cash assets: prior total assets − prior cash, adjusted for capex − D&A + Δtrade_rec
        non_cash_assets = (
            (prior_total_assets - prior_cash)
            + capex - da
            + (trade_receivables - prior_trade_rec)
        )

        # Liabilities: trade_payables + other liabilities (keep other liabilities constant for now)
        prior_other_liab = prior_total_assets - prior_total_equity - prior_trade_pay
        total_liabilities = trade_payables + prior_other_liab

        # Cash is the plug: assets = equity + liabilities
        total_equity_and_liab = total_equity + total_liabilities
        # non_cash_assets + cash = total_equity_and_liab
        cash = total_equity_and_liab - non_cash_assets
        cash = max(0.0, cash)  # floor at zero

        total_assets = non_cash_assets + cash

        items.append(_item("canonical.bs.cash_and_bank", period, cash, scenario, None))
        items.append(_item("canonical.bs.total_equity", period, total_equity, scenario, None))
        items.append(_item("canonical.bs.total_assets", period, total_assets, scenario, None))
        items.append(_item("canonical.bs.total_liabilities_and_equity", period, total_equity_and_liab, scenario, None))

        # Update prior-period anchors for next iteration
        prior_rev = revenue
        prior_total_assets = total_assets
        prior_total_equity = total_equity
        prior_trade_rec = trade_receivables
        prior_trade_pay = trade_payables
        prior_ppe = ppe
        prior_cash = cash

    return Forecast(line_items=items)
