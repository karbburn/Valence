from __future__ import annotations

"""
Share count module.

Derives historical diluted share count from canonical EPS and net profit,
then holds the most recent period flat across forecast years as an explicit,
named assumption.

Units: shares in Crores (INR Crores for net profit / INR per share for EPS → shares in Crores).
Consistency rule: the single diluted share count stored here is what the valuation engine
must use for equity value → per-share calculation — no divergence.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel

from backend.models.spec.forecast import FORECAST_PERIODS
from backend.models.statements.historical_model import HistoricalModel

SHARE_COUNT_SOURCE_HIST = "derived: net_profit / eps_diluted from canonical dataset"
SHARE_COUNT_SOURCE_FCST = "FY26 diluted share count held flat"


class ShareCountPeriod(BaseModel):
    period: str
    shares_basic_cr: Optional[float]    # in Crores
    shares_diluted_cr: Optional[float]  # in Crores — primary figure used in valuation
    source: str


class ShareCountSchedule(BaseModel):
    periods: List[str]
    schedule: List[ShareCountPeriod]

    def get_diluted(self, period: str) -> Optional[float]:
        for p in self.schedule:
            if p.period == period:
                return p.shares_diluted_cr
        return None


def build_share_count(
    historical_model: HistoricalModel,
    forecast_periods: List[str] = FORECAST_PERIODS,
    historical_periods: List[str] = ("FY24", "FY25", "FY26"),
) -> ShareCountSchedule:
    """Build a historical + forecast share count schedule.

    Historical: derived from net_profit / eps_diluted (and net_profit / eps_basic).
    Forecast: FY26 diluted share count held flat — explicit named assumption.
    """
    is_ = historical_model.income_statement
    schedule: List[ShareCountPeriod] = []

    # ------------------------------------------------------------------ #
    # Historical — derive from EPS and net profit
    # ------------------------------------------------------------------ #
    anchor_diluted: Optional[float] = None
    anchor_basic: Optional[float] = None

    for p in historical_periods:
        net_profit = is_.get_value("canonical.is.net_profit", p)
        eps_diluted = is_.get_value("canonical.is.eps_diluted", p)
        eps_basic = is_.get_value("canonical.is.eps_basic", p)

        diluted_cr = None
        basic_cr = None

        if net_profit is not None and eps_diluted and eps_diluted != 0:
            diluted_cr = round(net_profit / eps_diluted, 4)
        if net_profit is not None and eps_basic and eps_basic != 0:
            basic_cr = round(net_profit / eps_basic, 4)

        schedule.append(ShareCountPeriod(
            period=p,
            shares_basic_cr=basic_cr,
            shares_diluted_cr=diluted_cr,
            source=SHARE_COUNT_SOURCE_HIST,
        ))

        # Track the most recent period's values for the forecast anchor
        if diluted_cr is not None:
            anchor_diluted = diluted_cr
        if basic_cr is not None:
            anchor_basic = basic_cr

    # ------------------------------------------------------------------ #
    # Forecast — hold FY26 flat
    # ------------------------------------------------------------------ #
    for p in forecast_periods:
        schedule.append(ShareCountPeriod(
            period=p,
            shares_basic_cr=anchor_basic,
            shares_diluted_cr=anchor_diluted,
            source=SHARE_COUNT_SOURCE_FCST,
        ))

    all_periods = list(historical_periods) + list(forecast_periods)
    return ShareCountSchedule(periods=all_periods, schedule=schedule)
