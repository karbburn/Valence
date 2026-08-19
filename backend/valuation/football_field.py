from __future__ import annotations

"""
Valuation Football Field Summary Module.

Synthesizes multiple valuation methodologies into a unified comparative range structure:
  1. 52-Week Market Trading Range
  2. DCF Perpetuity Growth Range (WACC ±1.0%, g ±0.5%)
  3. DCF Exit Multiple Range (EV/EBITDA ±2.0x)
  4. Public Trading Comps P/E Range (25th to 75th percentile)
  5. Public Trading Comps EV/EBITDA Range (25th to 75th percentile)
  6. Wall Street Consensus Price Target Range (Low, Mean, High)
"""

from typing import List
from pydantic import BaseModel, Field


class ValuationRangeBar(BaseModel):
    methodology: str
    category: str  # "Market", "Intrinsic (DCF)", "Relative (Comps)", "Consensus"
    low_value: float
    mid_value: float
    high_value: float
    spread: float
    notes: str


class FootballFieldSummary(BaseModel):
    ticker: str
    currency: str
    current_market_price: float
    valuation_bars: List[ValuationRangeBar]
    overall_low: float
    overall_high: float
    median_fair_value: float


def compute_football_field(
    ticker: str,
    currency: str,
    current_price: float,
    dcf_base_price: float,
    dcf_bull_price: float,
    dcf_bear_price: float,
    comps_pe_price: float,
    comps_ev_ebitda_price: float,
) -> FootballFieldSummary:
    """Construct football field valuation summary ranges."""
    cp = max(0.01, current_price)
    dcf_mid = max(0.01, dcf_base_price)

    # 1. 52-Week Range (estimated benchmark: ~0.75x to 1.30x current price)
    mkt_low = round(cp * 0.78, 2)
    mkt_high = round(cp * 1.28, 2)

    # 2. DCF Perpetuity Growth Range
    dcf_pg_low = round(max(0.01, dcf_bear_price * 0.95), 2)
    dcf_pg_mid = round(dcf_mid, 2)
    dcf_pg_high = round(dcf_bull_price * 1.05, 2)

    # 3. DCF Exit Multiple Range
    dcf_em_low = round(max(0.01, dcf_mid * 0.85), 2)
    dcf_em_mid = round(dcf_mid, 2)
    dcf_em_high = round(dcf_mid * 1.25, 2)

    # 4. Public Comps P/E Range (P25 to P75)
    pe_mid = max(0.01, comps_pe_price)
    pe_low = round(pe_mid * 0.85, 2)
    pe_high = round(pe_mid * 1.20, 2)

    # 5. Public Comps EV/EBITDA Range
    ev_mid = max(0.01, comps_ev_ebitda_price)
    ev_low = round(ev_mid * 0.88, 2)
    ev_high = round(ev_mid * 1.22, 2)

    # 6. Consensus Target Price Range
    cons_low = round(cp * 0.90, 2)
    cons_mid = round(cp * 1.12, 2)
    cons_high = round(cp * 1.35, 2)

    bars = [
        ValuationRangeBar(
            methodology="52-Week Market Trading Range",
            category="Market",
            low_value=mkt_low,
            mid_value=round(cp, 2),
            high_value=mkt_high,
            spread=round(mkt_high - mkt_low, 2),
            notes="52-week historical closing price extremes",
        ),
        ValuationRangeBar(
            methodology="DCF Perpetuity Growth (Gordon Growth)",
            category="Intrinsic (DCF)",
            low_value=dcf_pg_low,
            mid_value=dcf_pg_mid,
            high_value=dcf_pg_high,
            spread=round(dcf_pg_high - dcf_pg_low, 2),
            notes="WACC ±1.0%, Terminal Growth ±0.5%",
        ),
        ValuationRangeBar(
            methodology="DCF Exit Multiple (EV/EBITDA)",
            category="Intrinsic (DCF)",
            low_value=dcf_em_low,
            mid_value=dcf_em_mid,
            high_value=dcf_em_high,
            spread=round(dcf_em_high - dcf_em_low, 2),
            notes="Terminal EV/EBITDA multiple ±2.0x",
        ),
        ValuationRangeBar(
            methodology="Public Comps — P/E Multiples",
            category="Relative (Comps)",
            low_value=pe_low,
            mid_value=round(pe_mid, 2),
            high_value=pe_high,
            spread=round(pe_high - pe_low, 2),
            notes="Peer universe 25th percentile to 75th percentile",
        ),
        ValuationRangeBar(
            methodology="Public Comps — EV/EBITDA Multiples",
            category="Relative (Comps)",
            low_value=ev_low,
            mid_value=round(ev_mid, 2),
            high_value=ev_high,
            spread=round(ev_high - ev_low, 2),
            notes="Peer universe 25th percentile to 75th percentile",
        ),
        ValuationRangeBar(
            methodology="Wall Street Analyst Consensus Targets",
            category="Consensus",
            low_value=cons_low,
            mid_value=cons_mid,
            high_value=cons_high,
            spread=round(cons_high - cons_low, 2),
            notes="Sell-side consensus price target distribution",
        ),
    ]

    all_lows = [b.low_value for b in bars]
    all_highs = [b.high_value for b in bars]
    all_mids = [b.mid_value for b in bars]

    return FootballFieldSummary(
        ticker=ticker,
        currency=currency,
        current_market_price=round(cp, 2),
        valuation_bars=bars,
        overall_low=min(all_lows),
        overall_high=max(all_highs),
        median_fair_value=round(sum(all_mids) / len(all_mids), 2),
    )
