from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel

from backend.data.store import RawDatapoint
from backend.models.statements.balance_sheet import BalanceSheet, assemble_balance_sheet
from backend.models.statements.cash_flow import (
    CashFlowStatement,
    assemble_cash_flow,
    derive_net_change_in_cash,
)
from backend.models.statements.income_statement import IncomeStatement, assemble_income_statement
from backend.models.statements.ratios import HistoricalRatios, compute_historical_ratios
from backend.normalization.taxonomy.models import CanonicalDatapoint


class HistoricalModel(BaseModel):
    company_id: str
    periods: List[str]
    income_statement: IncomeStatement
    balance_sheet: BalanceSheet
    cash_flow_statement: CashFlowStatement
    ratios: HistoricalRatios

    def get_period_summary(self, period: str) -> dict:
        """Returns key financial summary for a given period."""
        return {
            "period": period,
            "revenue": self.income_statement.get_value("canonical.is.revenue", period),
            "ebitda": self.income_statement.get_value("canonical.is.ebitda", period),
            "net_profit": self.income_statement.get_value("canonical.is.net_profit", period),
            "total_assets": self.balance_sheet.get_value("canonical.bs.total_assets", period),
            "total_equity": self.balance_sheet.get_value("canonical.bs.total_equity", period),
            "ebitda_margin_pct": self.ratios.get_value("ebitda_margin_pct", period),
            "net_margin_pct": self.ratios.get_value("net_margin_pct", period),
            "is_bs_balanced": self.balance_sheet.is_balanced_by_period.get(period, True),
        }


def build_historical_model(
    canonical_datapoints: list[CanonicalDatapoint],
    target_periods: list[str] | None = None,
    raw_datapoints: list[RawDatapoint] | None = None,
) -> HistoricalModel:
    """Builds unified HistoricalModel from canonical datapoints."""
    if not canonical_datapoints:
        raise ValueError("No canonical datapoints provided to build_historical_model.")

    company_id = canonical_datapoints[0].company_id
    raw_map: Dict[str, RawDatapoint] = {d.id: d for d in raw_datapoints} if raw_datapoints else {}

    # 1. Assemble Income Statement
    is_model = assemble_income_statement(
        canonical_datapoints,
        target_periods=target_periods,
        raw_datapoints_map=raw_map,
    )

    # 2. Assemble Balance Sheet
    bs_model = assemble_balance_sheet(
        canonical_datapoints,
        target_periods=target_periods,
        raw_datapoints_map=raw_map,
    )

    # 3. Assemble Cash Flow Statement
    cf_model = assemble_cash_flow(
        canonical_datapoints,
        target_periods=target_periods,
    )
    # Net change in cash is the sum of the three sections by definition, not a
    # fourth reported figure. Left as read, it published as zero for every
    # company while the balance sheet's cash line moved.
    derive_net_change_in_cash(cf_model)

    # Reconcile Cash Flow Statement to Balance Sheet cash change
    reconciles_dict = {}
    for idx, p in enumerate(cf_model.periods):
        if idx == 0:
            reconciles_dict[p] = True
        else:
            prev_p = cf_model.periods[idx - 1]
            cash_curr = bs_model.get_value("canonical.bs.cash_and_bank", p)
            cash_prev = bs_model.get_value("canonical.bs.cash_and_bank", prev_p)
            net_change = cf_model.get_value("canonical.cf.net_change_in_cash", p)
            if cash_curr is not None and cash_prev is not None and net_change is not None:
                reconciles_dict[p] = abs((cash_curr - cash_prev) - net_change) < 1.0
            else:
                reconciles_dict[p] = True
    cf_model.reconciles_to_bs_by_period = reconciles_dict

    # Combine common periods
    common_periods = [p for p in is_model.periods if p in bs_model.periods and p in cf_model.periods]
    if not common_periods:
        common_periods = is_model.periods

    # 4. Compute Historical Ratios & Driver Base
    ratios_model = compute_historical_ratios(is_model, bs_model, cf_model)

    return HistoricalModel(
        company_id=company_id,
        periods=common_periods,
        income_statement=is_model,
        balance_sheet=bs_model,
        cash_flow_statement=cf_model,
        ratios=ratios_model,
    )
