from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from backend.models.statements.balance_sheet import BalanceSheet
from backend.models.statements.cash_flow import CashFlowStatement
from backend.models.statements.income_statement import IncomeStatement


class RatioSeries(BaseModel):
    metric_key: str
    display_label: str
    values_by_period: Dict[str, float] = Field(default_factory=dict)
    unit: str
    formula_reference: str


class HistoricalRatios(BaseModel):
    company_id: str
    periods: List[str]
    ratio_series: List[RatioSeries]

    def get_series(self, metric_key: str) -> Optional[RatioSeries]:
        for s in self.ratio_series:
            if s.metric_key == metric_key:
                return s
        return None

    def get_value(self, metric_key: str, period: str) -> Optional[float]:
        s = self.get_series(metric_key)
        if s:
            return s.values_by_period.get(period)
        return None


def compute_historical_ratios(
    income_statement: IncomeStatement,
    balance_sheet: BalanceSheet,
    cash_flow: CashFlowStatement,
) -> HistoricalRatios:
    """Computes historical margins, growth rates, working capital, and driver ratios."""
    periods = income_statement.periods
    company_id = income_statement.company_id

    # Helper lambda to compute safe percentage or ratio
    def pct(num: Optional[float], den: Optional[float]) -> Optional[float]:
        if num is not None and den is not None and den != 0:
            return round((num / den) * 100.0, 2)
        return None

    def ratio_days(num: Optional[float], den: Optional[float]) -> Optional[float]:
        if num is not None and den is not None and den != 0:
            return round((num / den) * 365.0, 1)
        return None

    # Ratio definitions & containers
    series_defs = [
        ("gross_margin_pct", "Gross Margin %", "%", "gross_profit / revenue * 100"),
        ("ebitda_margin_pct", "EBITDA Margin %", "%", "ebitda / revenue * 100"),
        ("operating_margin_pct", "Operating Margin %", "%", "operating_profit / revenue * 100"),
        ("net_margin_pct", "Net Margin %", "%", "net_profit / revenue * 100"),
        ("effective_tax_rate_pct", "Effective Tax Rate %", "%", "tax / pbt * 100"),
        ("revenue_growth_yoy", "Revenue Growth YoY %", "%", "(revenue[t] - revenue[t-1]) / revenue[t-1] * 100"),
        ("ebitda_growth_yoy", "EBITDA Growth YoY %", "%", "(ebitda[t] - ebitda[t-1]) / ebitda[t-1] * 100"),
        ("net_profit_growth_yoy", "Net Profit Growth YoY %", "%", "(net_profit[t] - net_profit[t-1]) / net_profit[t-1] * 100"),
        ("dso_days", "Days Sales Outstanding (DSO)", "days", "(trade_receivables + unbilled_revenue) / revenue * 365"),
        ("dpo_days", "Days Payables Outstanding (DPO)", "days", "trade_payables / cost_of_sales * 365"),
        ("da_pct_revenue", "D&A % of Revenue", "%", "depreciation_amortization / revenue * 100"),
        ("da_pct_ppe", "D&A % of PPE", "%", "depreciation_amortization / ppe * 100"),
    ]

    ratios_dict: Dict[str, Dict[str, float]] = {m_key: {} for m_key, _, _, _ in series_defs}

    for idx, p in enumerate(periods):
        rev = income_statement.get_value("canonical.is.revenue", p)
        cos = income_statement.get_value("canonical.is.cost_of_sales", p)
        gp = income_statement.get_value("canonical.is.gross_profit", p)
        op = income_statement.get_value("canonical.is.operating_profit", p)
        da = income_statement.get_value("canonical.is.depreciation_amortization", p)
        ebitda = income_statement.get_value("canonical.is.ebitda", p)
        pbt = income_statement.get_value("canonical.is.pbt", p)
        tax = income_statement.get_value("canonical.is.tax", p)
        np = income_statement.get_value("canonical.is.net_profit", p)

        receivables = balance_sheet.get_value("canonical.bs.trade_receivables", p) or 0.0
        unbilled = balance_sheet.get_value("canonical.bs.unbilled_revenue", p) or 0.0
        payables = balance_sheet.get_value("canonical.bs.trade_payables", p)
        ppe = balance_sheet.get_value("canonical.bs.ppe", p)

        # 1. Margins
        if gp is None and rev is not None and cos is not None:
            gp = rev - cos
        val_gm = pct(gp, rev)
        if val_gm is not None:
            ratios_dict["gross_margin_pct"][p] = val_gm

        val_ebitda_m = pct(ebitda, rev)
        if val_ebitda_m is not None:
            ratios_dict["ebitda_margin_pct"][p] = val_ebitda_m

        val_op_m = pct(op, rev)
        if val_op_m is not None:
            ratios_dict["operating_margin_pct"][p] = val_op_m

        val_np_m = pct(np, rev)
        if val_np_m is not None:
            ratios_dict["net_margin_pct"][p] = val_np_m

        val_tax = pct(tax, pbt)
        if val_tax is not None:
            ratios_dict["effective_tax_rate_pct"][p] = val_tax

        # 2. Growth Rates (YoY)
        if idx > 0:
            prev_p = periods[idx - 1]
            prev_rev = income_statement.get_value("canonical.is.revenue", prev_p)
            prev_ebitda = income_statement.get_value("canonical.is.ebitda", prev_p)
            prev_np = income_statement.get_value("canonical.is.net_profit", prev_p)

            if rev is not None and prev_rev is not None and prev_rev != 0:
                ratios_dict["revenue_growth_yoy"][p] = round(((rev - prev_rev) / prev_rev) * 100.0, 2)
            if ebitda is not None and prev_ebitda is not None and prev_ebitda != 0:
                ratios_dict["ebitda_growth_yoy"][p] = round(((ebitda - prev_ebitda) / prev_ebitda) * 100.0, 2)
            if np is not None and prev_np is not None and prev_np != 0:
                ratios_dict["net_profit_growth_yoy"][p] = round(((np - prev_np) / prev_np) * 100.0, 2)

        # 3. Working Capital & Capital Ratios
        total_rec = receivables + unbilled
        if total_rec is not None:
            val_dso = ratio_days(total_rec, rev)
            if val_dso is not None:
                ratios_dict["dso_days"][p] = val_dso

        if payables is not None:
            val_dpo = ratio_days(payables, cos)
            if val_dpo is not None:
                ratios_dict["dpo_days"][p] = val_dpo

        val_da_rev = pct(da, rev)
        if val_da_rev is not None:
            ratios_dict["da_pct_revenue"][p] = val_da_rev

        val_da_ppe = pct(da, ppe)
        if val_da_ppe is not None:
            ratios_dict["da_pct_ppe"][p] = val_da_ppe

    result_series: List[RatioSeries] = []
    for m_key, label, unit, ref in series_defs:
        vals = ratios_dict.get(m_key, {})
        if vals:
            result_series.append(
                RatioSeries(
                    metric_key=m_key,
                    display_label=label,
                    values_by_period=vals,
                    unit=unit,
                    formula_reference=ref,
                )
            )

    return HistoricalRatios(
        company_id=company_id,
        periods=periods,
        ratio_series=result_series,
    )
