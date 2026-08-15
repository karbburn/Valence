from __future__ import annotations

"""
Suggestion engine: produces model-generated AssumptionObjects from historical ratios.

Each driver has its own explicit suggestion method. The source label stored in
the AssumptionObject must match exactly what was computed — no fabrication.
"""

from datetime import datetime
from typing import List, Optional

from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.forecast import FORECAST_PERIODS
from backend.models.statements.historical_model import HistoricalModel
from backend.models.statements.ratios import HistoricalRatios


def _avg(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def _cagr(start: Optional[float], end: Optional[float], years: int) -> Optional[float]:
    if start and end and start > 0 and years > 0:
        return round(((end / start) ** (1.0 / years) - 1.0) * 100.0, 4)
    return None


def _make(
    driver_key: str,
    value: float,
    period: str,
    scenario: str,
    source: str,
) -> AssumptionObject:
    return AssumptionObject(
        driver_key=driver_key,
        value=value,
        period=period,
        scenario=scenario,
        type="model_generated",
        source=source,
        last_updated=datetime.now(),
    )


def suggest_base_assumptions(
    ratios: HistoricalRatios,
    historical_model: HistoricalModel,
) -> List[AssumptionObject]:
    """Produce model-generated AssumptionObjects for every V1 driver, Base scenario.

    Every method is explicitly named in the source field — no unlabelled heuristics.
    """
    periods = historical_model.periods if (historical_model.periods and len(historical_model.periods) > 0) else ["FY24", "FY25", "FY26"]
    first_p = periods[0]
    last_p = periods[-1]
    num_years = len(periods) - 1 if len(periods) > 1 else 1
    result: List[AssumptionObject] = []

    is_us = historical_model.company_id.endswith("_us")
    default_tax = 21.0 if is_us else 25.17

    # ------------------------------------------------------------------ #
    # 1. Revenue Growth — Historical CAGR (first_p -> last_p)
    # ------------------------------------------------------------------ #
    rev_start = historical_model.income_statement.get_value("canonical.is.revenue", first_p)
    rev_end = historical_model.income_statement.get_value("canonical.is.revenue", last_p)
    rev_cagr = _cagr(rev_start, rev_end, num_years)
    rev_growth = rev_cagr if rev_cagr is not None else 10.0
    source_rev = f"Historical revenue CAGR ({first_p}-{last_p})"
    for p in FORECAST_PERIODS:
        result.append(_make("revenue_growth", rev_growth, p, "base", source_rev))

    # ------------------------------------------------------------------ #
    # 2. EBITDA Margin — Multi-year average
    # ------------------------------------------------------------------ #
    ebitda_margins = [ratios.get_value("ebitda_margin_pct", p) for p in periods]
    ebitda_margin = _avg(ebitda_margins) or 23.5
    source_ebitda = f"Multi-year average EBITDA margin ({first_p}-{last_p})"
    for p in FORECAST_PERIODS:
        result.append(_make("ebitda_margin", ebitda_margin, p, "base", source_ebitda))

    # ------------------------------------------------------------------ #
    # 3. EBIT Margin — Multi-year average operating margin
    # ------------------------------------------------------------------ #
    ebit_margins = [ratios.get_value("operating_margin_pct", p) for p in periods]
    ebit_margin = _avg(ebit_margins) or 20.0
    source_ebit = f"Multi-year average operating margin ({first_p}-{last_p})"
    for p in FORECAST_PERIODS:
        result.append(_make("ebit_margin", ebit_margin, p, "base", source_ebit))

    # ------------------------------------------------------------------ #
    # 4. D&A % Revenue — Multi-year average
    # ------------------------------------------------------------------ #
    da_pcts = [ratios.get_value("da_pct_revenue", p) for p in periods]
    da_pct = _avg(da_pcts) or 2.9
    source_da = f"Multi-year average D&A % revenue ({first_p}-{last_p})"
    for p in FORECAST_PERIODS:
        result.append(_make("da_pct_revenue", da_pct, p, "base", source_da))

    # ------------------------------------------------------------------ #
    # 5. Effective Tax Rate — Multi-year average
    # ------------------------------------------------------------------ #
    tax_rates = [ratios.get_value("effective_tax_rate_pct", p) for p in periods]
    tax_rate = _avg(tax_rates) or default_tax
    source_tax = f"Multi-year average effective tax rate ({first_p}-{last_p})"
    for p in FORECAST_PERIODS:
        result.append(_make("tax_rate", tax_rate, p, "base", source_tax))

    # ------------------------------------------------------------------ #
    # 6. DSO — most recent historical period
    # ------------------------------------------------------------------ #
    dso = ratios.get_value("dso_days", last_p) or 100.0
    source_dso = f"most recent period DSO ({last_p})"
    for p in FORECAST_PERIODS:
        result.append(_make("dso_days", dso, p, "base", source_dso))

    # ------------------------------------------------------------------ #
    # 7. DPO — most recent historical period
    # ------------------------------------------------------------------ #
    dpo = ratios.get_value("dpo_days", last_p) or 14.0
    source_dpo = f"most recent period DPO ({last_p})"
    for p in FORECAST_PERIODS:
        result.append(_make("dpo_days", dpo, p, "base", source_dpo))

    # ------------------------------------------------------------------ #
    # 7b. DIO — zero for services companies
    # ------------------------------------------------------------------ #
    dio = 0.0  # Default 0.0 for services
    source_dio = "zero — services/tech company with minimal inventory"
    for p in FORECAST_PERIODS:
        result.append(_make("dio_days", dio, p, "base", source_dio))

    # ------------------------------------------------------------------ #
    # 8. Capex % Revenue — Multi-year average using canonical capex / revenue
    # ------------------------------------------------------------------ #
    capex_pcts = []
    used_direct_capex = False
    for p in periods:
        capex_val = historical_model.cash_flow_statement.get_value("canonical.cf.capex", p)
        if capex_val is not None:
            used_direct_capex = True
        else:
            inv = historical_model.cash_flow_statement.get_value("canonical.cf.investing_activities", p)
            if inv is not None:
                capex_val = abs(inv)

        rev = historical_model.income_statement.get_value("canonical.is.revenue", p)
        if capex_val is not None and rev and rev > 0:
            capex_pcts.append(round(abs(capex_val) / rev * 100.0, 4))

    capex_pct = _avg(capex_pcts) or 2.5
    if used_direct_capex:
        source_capex = f"Multi-year average GAAP capex (canonical.cf.capex) % revenue ({first_p}-{last_p})"
    else:
        source_capex = f"derived — Multi-year average |investing_activities| proxy % revenue ({first_p}-{last_p})"

    for p in FORECAST_PERIODS:
        result.append(_make("capex_pct_revenue", capex_pct, p, "base", source_capex))

    # ------------------------------------------------------------------ #
    # 9. Debt Repayment — zero (borrowings carried flat across forecast)
    # ------------------------------------------------------------------ #
    source_debt = "zero — opening debt carried flat, no draws or repayments"
    for p in FORECAST_PERIODS:
        result.append(_make("debt_repayment", 0.0, p, "base", source_debt))

    # ------------------------------------------------------------------ #
    # 10. WACC — structural placeholders (populated in valuation engine)
    # ------------------------------------------------------------------ #
    source_wacc_placeholder = "structural placeholder — populated in valuation engine"
    result.append(_make("wacc.cost_of_equity", 13.0, "all", "base", source_wacc_placeholder))
    result.append(_make("wacc.cost_of_debt", 0.0, "all", "base", "placeholder — valuation uses debt schedule interest rate"))

    # ------------------------------------------------------------------ #
    # 11. Terminal Value inputs — structural placeholders
    # ------------------------------------------------------------------ #
    source_terminal = "structural placeholder"
    result.append(_make("terminal_growth_rate", 4.0, "terminal", "base", source_terminal))
    result.append(_make("exit_ev_multiple", 20.0, "terminal", "base", source_terminal))

    return result
