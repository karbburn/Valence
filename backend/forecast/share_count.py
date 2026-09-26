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
SHARE_COUNT_SOURCE_REGISTRY = "registry metadata constant (no EPS in the ingested dataset)"
SHARE_COUNT_SOURCE_PROVIDER = "live market-data provider share count"
SHARE_COUNT_SOURCE_FCST = "last historical diluted share count held flat"

# A registry constant that disagrees with the live share count by more than this
# is not a rounding difference — it is a stale seed (a pre-bonus count, a
# pre-split count, a pre-buyback count). Resolved in favour of the live figure.
REGISTRY_VS_LIVE_TOLERANCE = 0.05


def resolve_shares_outstanding(
    company_id: str,
    market: Optional[str] = None,
) -> tuple[Optional[float], str]:
    """Authoritative diluted share count for a company, with its provenance.

    ONE resolver, used by the share-count schedule, the WACC capital weights and
    the valuation bridge, so the three can never disagree.

    Order: EPS-derived (a filing figure) -> live market-data provider -> the
    registry constant. The registry is a SEED, never an override: a hand-entered
    share count that has drifted (Infosys' 412.45 Cr against a live 405.03 Cr;
    a pre-bonus count for an Indian IT name) silently revalues every per-share
    output and the WACC equity weight.
    """
    from backend.data.providers.market_data import get_company_market_data
    from backend.models.spec.metadata import get_metadata_for_company

    live: Optional[float] = None
    try:
        live = get_company_market_data(company_id, market=market).shares_outstanding.value
    except Exception:
        live = None

    registry = get_metadata_for_company(company_id).shares_outstanding

    if live and live > 0 and registry and registry > 0:
        drift = abs(registry - live) / live
        if drift > REGISTRY_VS_LIVE_TOLERANCE:
            return live, (
                f"{SHARE_COUNT_SOURCE_PROVIDER} — registry constant {registry:,.2f} "
                f"disagrees by {drift * 100:.1f}%, so the live count wins"
            )
    if live and live > 0:
        return live, SHARE_COUNT_SOURCE_PROVIDER
    if registry and registry > 0:
        return registry, SHARE_COUNT_SOURCE_REGISTRY
    return None, "unresolved — no EPS, provider or registry share count available"


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
    historical_periods: Optional[List[str]] = None,
) -> ShareCountSchedule:
    """Build a historical + forecast share count schedule.

    Historical: derived from net_profit / eps_diluted (and net_profit / eps_basic),
    falling back to the authoritative resolver. Forecast: latest historical
    period diluted share count held flat — an explicit named assumption.
    """
    if historical_periods is None:
        historical_periods = historical_model.periods

    is_ = historical_model.income_statement
    schedule: List[ShareCountPeriod] = []

    # ------------------------------------------------------------------ #
    # Historical — derive from EPS and net profit
    # ------------------------------------------------------------------ #
    anchor_diluted: Optional[float] = None
    anchor_basic: Optional[float] = None
    anchor_source = SHARE_COUNT_SOURCE_HIST

    fallback_shares, fallback_source = resolve_shares_outstanding(
        historical_model.company_id, getattr(historical_model, "market", None)
    )

    for p in historical_periods:
        net_profit = is_.get_value("canonical.is.net_profit", p)
        eps_diluted = is_.get_value("canonical.is.eps_diluted", p)
        eps_basic = is_.get_value("canonical.is.eps_basic", p)

        diluted_cr = None
        basic_cr = None
        source = SHARE_COUNT_SOURCE_HIST

        if net_profit is not None and eps_diluted not in (None, 0):
            diluted_cr = round(net_profit / eps_diluted, 4)
        elif fallback_shares:
            diluted_cr = fallback_shares
            source = fallback_source

        if net_profit is not None and eps_basic not in (None, 0):
            basic_cr = round(net_profit / eps_basic, 4)
        elif diluted_cr is not None:
            basic_cr = diluted_cr

        schedule.append(ShareCountPeriod(
            period=p,
            shares_basic_cr=basic_cr,
            shares_diluted_cr=diluted_cr,
            source=source,
        ))

        # Track the most recent period's values for the forecast anchor
        if diluted_cr is not None:
            anchor_diluted = diluted_cr
            anchor_source = source
        if basic_cr is not None:
            anchor_basic = basic_cr

    # ------------------------------------------------------------------ #
    # Forecast — hold the last historical count flat
    # ------------------------------------------------------------------ #
    forecast_source = f"{SHARE_COUNT_SOURCE_FCST} ({anchor_source})"
    for p in forecast_periods:
        schedule.append(ShareCountPeriod(
            period=p,
            shares_basic_cr=anchor_basic,
            shares_diluted_cr=anchor_diluted,
            source=forecast_source,
        ))

    all_periods = list(historical_periods) + list(forecast_periods)
    return ShareCountSchedule(periods=all_periods, schedule=schedule)
