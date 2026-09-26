# -*- coding: utf-8 -*-
"""
Forecast Engine: period-by-period 3-statement roll-forward.

Build order per period (each column is independent given prior-period actuals):
  1. Revenue
  2. EBITDA, EBIT (operating_profit), D&A
  3. Other income, Finance cost (held flat from last historical)
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

import calendar
from datetime import date
from typing import Dict, List, Optional

from backend import constants
from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.forecast import FORECAST_PERIODS, Forecast, ForecastLineItem
from backend.models.spec.metadata import ModelMetadata, parse_fiscal_year_end


def _yr(period_label: str) -> int:
    yr = period_label[2:]
    return 2000 + int(yr) if len(yr) == 2 else int(yr)


def _resolve_metadata(historical_model) -> ModelMetadata:
    """The company's own metadata, which carries its fiscal calendar and market.

    The fiscal year end and the reporting market must come from the registry,
    never from the company_id suffix: infy_us is a US-listed ADR that reports on
    a 31 March Indian fiscal year, and nvda_us closes its books on 31 January.
    """
    existing = getattr(historical_model, "metadata", None)
    if isinstance(existing, ModelMetadata):
        return existing

    from backend.models.spec.metadata import get_metadata_for_company

    try:
        return get_metadata_for_company(historical_model.company_id)
    except Exception:
        from backend.models.spec.metadata import resolve_market

        market = resolve_market(historical_model.company_id)
        return ModelMetadata(
            company_id=historical_model.company_id,
            ticker=historical_model.company_id.split("_")[0].upper(),
            name=historical_model.company_id,
            market=market,
            currency="USD" if market == "us" else "INR",
            units="millions" if market == "us" else "crores",
            fiscal_year_end="December 31" if market == "us" else "March 31",
        )


def _get(assumptions: List[AssumptionObject], driver_key: str, period: str, scenario: str) -> Optional[float]:
    """Return the assumption value for a driver/period/scenario, falling back to 'all'."""
    for a in assumptions:
        if a.driver_key == driver_key and a.period == period and a.scenario == scenario:
            return a.value
    for a in assumptions:
        if a.driver_key == driver_key and a.period == "all" and a.scenario == scenario:
            return a.value
    return None


def _period_end(year: int, month: int, day: int) -> date:
    """Clamp a fiscal year-end to a real calendar date.

    A February 29 fiscal year end does not exist in a common year, and a
    company's stated year end can be the 30th of a 31-day month. Clamping to
    the last valid day keeps every emitted period_end_date constructible
    without changing the company being modelled.
    """
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _item(
    canonical_key: str,
    period: str,
    value: float,
    scenario: str,
    driver_key: Optional[str] = None,
    fiscal_end_month: int = 3,
    fiscal_end_day: int = 31,
) -> ForecastLineItem:
    return ForecastLineItem(
        canonical_key=canonical_key,
        period_label=period,
        period_end_date=_period_end(_yr(period), fiscal_end_month, fiscal_end_day),
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

    # Seed prior-period values from last available historical period
    last_p = historical_model.periods[-1] if (historical_model.periods and len(historical_model.periods) > 0) else "FY26"
    hist_is = historical_model.income_statement
    hist_bs = historical_model.balance_sheet
    hist_cf = historical_model.cash_flow_statement

    prior_rev = constants.resolve(hist_is.get_value("canonical.is.revenue", last_p), 0.0)
    prior_total_assets = constants.resolve(hist_bs.get_value("canonical.bs.total_assets", last_p), 0.0)
    prior_total_equity = constants.resolve(hist_bs.get_value("canonical.bs.total_equity", last_p), 0.0)
    prior_total_liabilities = constants.resolve(
        hist_bs.get_value("canonical.bs.total_liabilities", last_p), 0.0
    )
    # Total equity is a REQUIRED opening anchor: the roll-forward grows it by
    # retained profit, so seeding it from zero silently deletes the entire
    # opening equity base (a 93% error on a steelmaker). Where the filings do
    # not report it directly, derive it from the accounting identity.
    if prior_total_equity == 0.0 and prior_total_assets > 0.0:
        if prior_total_liabilities > 0.0:
            prior_total_equity = prior_total_assets - prior_total_liabilities
        else:
            total_liab_and_equity = hist_bs.get_value(
                "canonical.bs.total_liabilities_and_equity", last_p
            )
            if total_liab_and_equity is not None and abs(total_liab_and_equity - prior_total_assets) < 1.0:
                raise ValueError(
                    f"{historical_model.company_id}: opening total_equity is unresolvable — the "
                    "filings report neither total equity nor total liabilities, so the "
                    "roll-forward would start from a zero equity base."
                )
    prior_trade_rec = (
        constants.resolve(hist_bs.get_value("canonical.bs.trade_receivables", last_p), 0.0) +
        constants.resolve(hist_bs.get_value("canonical.bs.unbilled_revenue", last_p), 0.0)
    )
    prior_trade_pay = constants.resolve(hist_bs.get_value("canonical.bs.trade_payables", last_p), 0.0)
    prior_inventory = constants.resolve(hist_bs.get_value("canonical.bs.inventory", last_p), 0.0)
    prior_ppe = constants.resolve(hist_bs.get_value("canonical.bs.ppe", last_p), 0.0)
    prior_cash = constants.resolve(hist_bs.get_value("canonical.bs.cash_and_bank", last_p), 0.0)
    # Total interest-bearing opening debt, matching the definition the valuation
    # bridge deducts: non-current borrowings + current borrowings (which include
    # the current portion of long-term debt) + finance leases. Lease
    # liabilities carry no cash cost in the modelled periods because finance
    # cost is held flat at the last actual, so they are not compounded into the
    # debt schedule either.
    prior_borrowings = sum(
        constants.resolve(hist_bs.get_value(key, last_p), 0.0)
        for key in (
            "canonical.bs.borrowings",
            "canonical.bs.short_term_borrowings",
            "canonical.bs.finance_lease_liabilities",
        )
    )

    # Carry forward quasi-stable items from last historical period (no hardcoded Infosys 4000/416 fallbacks)
    # Non-operating items are held flat in absolute terms: other income does not compound
    # with trading revenue, and finance cost tracks the (flat) debt schedule balance.
    other_income = constants.resolve(hist_is.get_value("canonical.is.other_income", last_p), 0.0)
    finance_cost = constants.resolve(hist_is.get_value("canonical.is.finance_cost", last_p), 0.0)

    # Compute historical gross margin from last historical period
    hist_gp = hist_is.get_value("canonical.is.gross_profit", last_p)
    hist_rev = hist_is.get_value("canonical.is.revenue", last_p)
    gross_margin_hist = (
        (hist_gp / hist_rev * 100.0)
        if hist_gp is not None and hist_rev is not None and hist_rev > 0
        else constants.DEFAULT_GROSS_MARGIN
    )

    # Dividend payout. Absent a reported dividend line the company has not been
    # observed to pay one, so the neutral reading is 0 — NOT a 40% payout, which
    # would book a phantom dividend against cash for a company that has never
    # declared one.
    hist_div = hist_cf.get_value("canonical.cf.dividends_paid", last_p) if hasattr(hist_cf, "get_value") else None
    hist_np = hist_is.get_value("canonical.is.net_profit", last_p)
    if hist_div is None or hist_np is None or hist_np <= 0:
        dividend_payout_pct = 0.0
    else:
        dividend_payout_pct = min(abs(hist_div / hist_np), 1.0)

    # Stock-based compensation is projected at its last historical % of revenue
    # (unlike other income it scales with the operating business).
    hist_sbc = hist_cf.get_value("canonical.cf.stock_compensation", last_p) if hasattr(hist_cf, "get_value") else None
    sbc_pct_rev = (
        (abs(hist_sbc) / prior_rev * 100.0)
        if hist_sbc is not None and prior_rev > 0
        else 0.0
    )

    # Fiscal calendar comes from the company's own metadata. Deriving it from the
    # company_id suffix is wrong for any listing whose slug and calendar differ
    # — infy_us is a US-listed ADR on a 31 March Indian fiscal year.
    metadata = _resolve_metadata(historical_model)
    market = metadata.market
    default_tax_rate = constants.statutory_tax_rate(market)
    try:
        fiscal_end_month, fiscal_end_day = parse_fiscal_year_end(metadata.fiscal_year_end)
    except ValueError:
        fiscal_end_month, fiscal_end_day = (12, 31) if market == "us" else (3, 31)

    for period in FORECAST_PERIODS:
        # --- Driver lookups ---
        # `constants.resolve`, never `or`: a driver whose real value is 0.0 (no
        # inventory, no payables, a nil tax rate) must not be replaced by the
        # platform default.
        rev_growth = constants.resolve(_get(assumptions, "revenue_growth", period, scenario), 10.0)
        ebitda_margin = constants.resolve(
            _get(assumptions, "ebitda_margin", period, scenario), constants.DEFAULT_EBITDA_MARGIN
        )
        ebit_margin = constants.resolve(
            _get(assumptions, "ebit_margin", period, scenario), constants.DEFAULT_EBIT_MARGIN
        )
        da_pct_rev = constants.resolve(
            _get(assumptions, "da_pct_revenue", period, scenario), constants.DEFAULT_DA_PCT_REVENUE
        )
        tax_rate = constants.resolve(
            _get(assumptions, "tax_rate", period, scenario), default_tax_rate
        )
        dso = constants.resolve(
            _get(assumptions, "dso_days", period, scenario), constants.DEFAULT_DSO_DAYS
        )
        dio = constants.resolve(_get(assumptions, "dio_days", period, scenario), 0.0)
        dpo = constants.resolve(
            _get(assumptions, "dpo_days", period, scenario), constants.DEFAULT_DPO_DAYS
        )
        capex_pct = constants.resolve(
            _get(assumptions, "capex_pct_revenue", period, scenario),
            constants.DEFAULT_CAPEX_PCT_REVENUE,
        )

        # --- Income Statement ---
        revenue = prior_rev * (1.0 + rev_growth / 100.0)
        da = revenue * da_pct_rev / 100.0

        # Cost of sales and gross profit are anchored on the company's own
        # historical gross margin; gross profit can never sit below EBIT, or the
        # implied total operating expense becomes negative.
        cost_of_sales = revenue * (1.0 - gross_margin_hist / 100.0)
        gross_profit = revenue - cost_of_sales

        # EBIT is the driver; EBITDA is DERIVED as EBIT + D&A.
        #
        # Treating EBITDA as an independent third driver lets three
        # independently-averaged margin drivers disagree, and the income
        # statement then fails to foot (EBITDA − D&A ≠ EBIT) by a material
        # amount. Deriving EBITDA makes the identity structural.
        ebit = min(revenue * ebit_margin / 100.0, gross_profit)
        ebitda = ebit + da

        # PBT = EBIT + other_income − finance_cost
        # Non-operating items held flat at their last historical absolute levels.
        period_other_income = other_income
        period_finance_cost = finance_cost
        pbt = ebit + period_other_income - period_finance_cost
        tax = pbt * tax_rate / 100.0
        net_profit = pbt - tax

        items.append(_item("canonical.is.revenue", period, revenue, scenario, "revenue_growth", fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.is.ebitda", period, ebitda, scenario, "ebit_margin", fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.is.operating_profit", period, ebit, scenario, "ebit_margin", fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.is.depreciation_amortization", period, da, scenario, "da_pct_revenue", fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.is.cost_of_sales", period, cost_of_sales, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.is.gross_profit", period, gross_profit, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.is.other_income", period, period_other_income, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.is.finance_cost", period, period_finance_cost, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.is.pbt", period, pbt, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.is.tax", period, tax, scenario, "tax_rate", fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.is.net_profit", period, net_profit, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))

        # --- Working Capital (Balance Sheet) ---
        trade_receivables = revenue * dso / 365.0
        # A zero DIO/DPO means "the filings report no such balance", not "the
        # balance goes to zero". Zeroing a real opening balance deletes the
        # whole account and breaks the cash roll-forward; carry it flat.
        inventory = (cost_of_sales * dio / 365.0) if dio > 0 else prior_inventory
        trade_payables = (cost_of_sales * dpo / 365.0) if dpo > 0 else prior_trade_pay

        # PPE: prior PPE + capex − D&A
        capex = revenue * capex_pct / 100.0
        ppe = max(0.0, prior_ppe + capex - da)

        items.append(_item("canonical.bs.trade_receivables", period, trade_receivables, scenario, "dso_days", fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.bs.inventory", period, inventory, scenario, "dio_days", fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.bs.trade_payables", period, trade_payables, scenario, "dpo_days", fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.bs.ppe", period, ppe, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))

        # --- Cash Flow ---
        delta_wc = (
            (trade_receivables - prior_trade_rec)
            + (inventory - prior_inventory)
            - (trade_payables - prior_trade_pay)
        )
        operating_cf = net_profit + da - delta_wc
        investing_cf = -capex  # capex outflow

        items.append(_item("canonical.cf.operating_activities", period, operating_cf, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.cf.delta_working_capital", period, delta_wc, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.cf.capex", period, -capex, scenario, "capex_pct_revenue", fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))  # Negative = outflow
        items.append(_item("canonical.cf.investing_activities", period, investing_cf, scenario, "capex_pct_revenue", fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        if sbc_pct_rev > 0:
            items.append(_item("canonical.cf.stock_compensation", period, revenue * sbc_pct_rev / 100.0, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))

        # --- Balance Sheet Closure ---
        # Equity grows by retained profit (net_profit − dividends paid).
        dividends_est = net_profit * dividend_payout_pct
        total_equity = prior_total_equity + net_profit - dividends_est

        # Financing must be emitted, and cash must be the RESULT of the cash flow
        # statement rather than an independent plug. When dividends were deducted
        # from equity but never appeared in financing, the balance sheet and the
        # cash flow statement diverged by exactly the dividend every year — and
        # nothing reconciled them, so the model still reported MODEL VALID.
        # Borrowings are carried flat by the debt schedule, so dividends are the
        # only financing movement before any funding plug.
        financing_cf = -dividends_est

        # Non-cash assets: prior total assets − prior cash, plus capex − D&A and
        # the working-capital ASSET build (receivables AND inventory).
        non_cash_assets = (
            (prior_total_assets - prior_cash)
            + capex - da
            + (trade_receivables - prior_trade_rec)
            + (inventory - prior_inventory)
        )

        # Liabilities: trade_payables + other liabilities (kept flat).
        prior_other_liab = max(0.0, prior_total_assets - prior_total_equity - prior_trade_pay)
        base_liabilities = trade_payables + prior_other_liab

        # Cash from the cash flow statement: prior cash + CFO + CFI + CFF.
        cash_from_cf = prior_cash + operating_cf + investing_cf + financing_cf
        if cash_from_cf < 0:
            # The company cannot fund itself from operations and investment;
            # fund the shortfall on the balance sheet rather than publishing
            # negative cash.
            borrowing_plug = -cash_from_cf
            cash = 0.0
            total_liabilities = base_liabilities + borrowing_plug
            financing_cf -= borrowing_plug
        else:
            cash = cash_from_cf
            total_liabilities = base_liabilities

        total_equity_and_liab = total_equity + total_liabilities
        total_assets = non_cash_assets + cash

        items.append(_item("canonical.cf.dividends_paid", period, -dividends_est, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.cf.financing_activities", period, financing_cf, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.bs.cash_and_bank", period, cash, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.bs.total_equity", period, total_equity, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.bs.total_assets", period, total_assets, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))
        items.append(_item("canonical.bs.total_liabilities_and_equity", period, total_equity_and_liab, scenario, None, fiscal_end_month=fiscal_end_month, fiscal_end_day=fiscal_end_day))

        # Update prior-period anchors for next iteration
        prior_rev = revenue
        prior_total_assets = total_assets
        prior_total_equity = total_equity
        prior_trade_rec = trade_receivables
        prior_trade_pay = trade_payables
        prior_inventory = inventory
        prior_ppe = ppe
        prior_cash = cash

    return Forecast(line_items=items)
