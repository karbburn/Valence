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
        ("dio_days", "Days Inventory Outstanding (DIO)", "days", "inventory / cost_of_sales * 365"),
        ("da_pct_revenue", "D&A % of Revenue", "%", "depreciation_amortization / revenue * 100"),
        ("da_pct_ppe", "D&A % of PPE", "%", "depreciation_amortization / ppe * 100"),
        ("roe_pct", "Return on Equity (ROE) %", "%", "net_profit / total_equity * 100"),
        ("roce_pct", "Return on Capital Employed (ROCE) %", "%", "operating_profit / (total_assets - total_current_liabilities) * 100"),
        ("de_ratio", "Debt-to-Equity", "x", "borrowings / total_equity"),
        ("current_ratio", "Current Ratio", "x", "total_current_assets / total_current_liabilities"),
        ("quick_ratio", "Quick Ratio", "x", "(total_current_assets - inventory) / total_current_liabilities"),
        ("interest_coverage", "Interest Coverage", "x", "operating_profit / finance_cost"),
        ("inventory_turnover", "Inventory Turnover", "x", "cost_of_sales / inventory"),
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
        total_equity = balance_sheet.get_value("canonical.bs.total_equity", p)
        borrowings = balance_sheet.get_value("canonical.bs.borrowings", p)
        total_current_assets = balance_sheet.get_value("canonical.bs.total_current_assets", p)
        total_current_liab = balance_sheet.get_value("canonical.bs.total_current_liabilities", p)
        total_assets = balance_sheet.get_value("canonical.bs.total_assets", p)
        inventory = balance_sheet.get_value("canonical.bs.inventory", p)
        finance_cost = income_statement.get_value("canonical.is.finance_cost", p)

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

        # Effective tax rate is only meaningful for profitable, undistorted
        # years: a loss year or a one-time exceptional gain makes tax/pbt
        # meaningless (negative or near-zero), which would poison downstream
        # forecast tax averages. Skip those; callers fall back to statutory.
        val_tax = pct(tax, pbt)
        if val_tax is not None and pbt is not None and pbt > 0 and 0.0 < val_tax <= 50.0:
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

        if inventory is not None and inventory > 0:
            val_dio = ratio_days(inventory, cos)
            if val_dio is not None:
                ratios_dict["dio_days"][p] = val_dio

        val_da_rev = pct(da, rev)
        if val_da_rev is not None:
            ratios_dict["da_pct_revenue"][p] = val_da_rev

        val_da_ppe = pct(da, ppe)
        if val_da_ppe is not None:
            ratios_dict["da_pct_ppe"][p] = val_da_ppe

        # 4. Returns, Leverage & Liquidity Ratios
        # ROE / ROCE use period-end equity/capital employed (avg-2yr refinement not
        # applied here to keep the series simple and consistent with other ratios).
        val_roe = pct(np, total_equity)
        if val_roe is not None:
            ratios_dict["roe_pct"][p] = val_roe

        capital_employed = (
            (total_assets or 0.0) - (total_current_liab or 0.0)
        ) if (total_assets is not None and total_current_liab is not None) else None
        val_roce = pct(op, capital_employed)
        if val_roce is not None:
            ratios_dict["roce_pct"][p] = val_roce

        val_de = None
        if borrowings is not None and total_equity not in (None, 0):
            val_de = round(borrowings / total_equity, 2)
        if val_de is not None:
            ratios_dict["de_ratio"][p] = val_de

        val_current = None
        if total_current_assets is not None and total_current_liab not in (None, 0):
            val_current = round(total_current_assets / total_current_liab, 2)
        if val_current is not None:
            ratios_dict["current_ratio"][p] = val_current

        val_quick = None
        if total_current_assets is not None and total_current_liab not in (None, 0):
            inv_val = inventory or 0.0
            val_quick = round((total_current_assets - inv_val) / total_current_liab, 2)
        if val_quick is not None:
            ratios_dict["quick_ratio"][p] = val_quick

        # Interest coverage only meaningful with real finance costs.
        if op is not None and finance_cost not in (None, 0):
            ratios_dict["interest_coverage"][p] = round(op / finance_cost, 2)

        # Inventory turnover is meaningful only for companies that carry inventory.
        if cos not in (None, 0) and inventory not in (None, 0):
            ratios_dict["inventory_turnover"][p] = round(cos / inventory, 2)

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
