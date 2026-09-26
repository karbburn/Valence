from __future__ import annotations

"""
Valuation Football Field Summary Module.

Synthesizes multiple valuation methodologies into a unified comparative range structure.
Intrinsic ranges are genuinely re-priced (WACC / growth / exit-multiple perturbations run
through the same discounting math as the base case); relative ranges use peer quartile
implied prices rather than fixed multipliers. Bars: 52-week market band, DCF perpetuity
growth, DCF exit multiple, comps P/E, comps EV/EBITDA.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class ValuationRangeBar(BaseModel):
    methodology: str
    category: str  # "Market", "Intrinsic (DCF)", "Relative (Comps)"
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
    mean_fair_value: float


def _reprice_dcf(base_val, wacc_pct: float, terminal_growth_rate: Optional[float] = None,
                 exit_multiple: Optional[float] = None) -> float:
    """Implied share price from the base FCFF stream at a perturbed WACC/TV input.

    Mirrors engine conventions exactly: explicit-period flows at mid-year factors,
    terminal value discounted end-of-year-five, same net-debt bridge and share count.
    """
    w = max(0.005, wacc_pct) / 100.0
    fcffs = [p.fcff or 0.0 for p in base_val.fcff_by_period]
    sum_pv = sum(f / ((1.0 + w) ** (i + 0.5)) for i, f in enumerate(fcffs))

    tv = base_val.terminal_value
    g_frac = (terminal_growth_rate if terminal_growth_rate is not None else tv.terminal_growth_rate or 4.0) / 100.0
    last_fcff = fcffs[-1] if fcffs else 0.0

    if exit_multiple is not None:
        tv_undisc = (base_val.terminal_value.final_year_ebitda or 0.0) * exit_multiple
    elif last_fcff > 0:
        tv_undisc = last_fcff * (1.0 + g_frac) / (w - g_frac)
    else:
        # Non-positive terminal FCFF: steady-state normalization on final-year EBIT.
        ebit5 = base_val.fcff_by_period[-1].ebit if base_val.fcff_by_period else 0.0
        tax = (base_val.fcff_by_period[-1].tax_rate or 21.0) / 100.0 if base_val.fcff_by_period else 0.21
        nopat = ebit5 * (1.0 - tax)
        reinvest = min(0.50, max(0.10, g_frac / w))
        tv_undisc = (nopat * (1.0 - reinvest)) * (1.0 + g_frac) / (w - g_frac)

    pv_tv = tv_undisc / ((1.0 + w) ** len(fcffs)) if fcffs else 0.0
    equity = (sum_pv + pv_tv) - (base_val.dcf_bridge.less_net_debt or 0.0)
    shares = base_val.dcf_bridge.shares_outstanding or 1.0
    return max(0.0, equity / shares)


def compute_football_field(
    ticker: str,
    currency: str,
    current_price: float,
    dcf_base_price: float,
    dcf_bull_price: float,
    dcf_bear_price: float,
    comps_pe_price: float,
    comps_ev_ebitda_price: float,
    base_valuation_output=None,
    comps_pe_low: Optional[float] = None,
    comps_pe_high: Optional[float] = None,
    comps_ev_ebitda_low: Optional[float] = None,
    comps_ev_ebitda_high: Optional[float] = None,
) -> FootballFieldSummary:
    """Construct football field valuation summary ranges.

    When ``base_valuation_output`` is supplied, both intrinsic DCF bars are genuinely
    re-priced around the base case (WACC ±1pp with growth ±0.5pp for the perpetuity
    bar; exit multiple ±2.0x for the multiple bar). Peer quartile prices are used for
    the comps bars when provided. Fixed-band fallbacks keep the function total when
    upstream inputs are missing.
    """
    cp = max(0.01, current_price)
    dcf_mid = max(0.01, dcf_base_price)
    # 1. 52-week trading band approximated from the live quote when history is unavailable.
    mkt_low = round(cp * 0.78, 2)
    mkt_high = round(cp * 1.28, 2)

    # 2. DCF Perpetuity Growth — re-priced at WACC ±1.0pp, g ±0.5pp.
    pg_notes = "Re-priced at WACC ±1.0pp, Terminal Growth ±0.5pp"
    em_notes = "Terminal EV/EBITDA multiple ±2.0x, re-priced"
    if base_valuation_output is not None:
        w0 = base_valuation_output.wacc.wacc or 12.0
        tv = base_valuation_output.terminal_value
        g0 = tv.terminal_growth_rate or 4.0
        m0 = tv.exit_multiple or 20.0
        # Each bar's midpoint is its own method's base re-price; the paired shifts are
        # not guaranteed monotone around base (a cheaper WACC can dominate a lower g),
        # so the perpetuity bar spans both re-pricings and its base case.
        dcf_pg_mid = round(max(0.01, _reprice_dcf(base_valuation_output, w0, g0)), 2)
        candidates = [
            _reprice_dcf(base_valuation_output, w0 - 1.0, g0 - 0.5),
            _reprice_dcf(base_valuation_output, w0 + 1.0, g0 + 0.5),
            dcf_pg_mid,
        ]
        dcf_pg_low = round(max(0.01, min(candidates)), 2)
        dcf_pg_high = round(max(0.01, max(candidates)), 2)
        dcf_em_mid = round(max(0.01, _reprice_dcf(base_valuation_output, w0, exit_multiple=m0)), 2)
        dcf_em_low = round(max(0.01, _reprice_dcf(base_valuation_output, w0, exit_multiple=m0 - 2.0)), 2)
        dcf_em_high = round(max(0.01, _reprice_dcf(base_valuation_output, w0, exit_multiple=m0 + 2.0)), 2)
    else:
        dcf_pg_low = round(max(0.01, min(dcf_bear_price, dcf_mid)), 2)
        dcf_pg_high = round(max(0.01, max(dcf_bull_price, dcf_mid)), 2)
        pg_notes = "Scenario anchors (bear/base/bull)"
        dcf_em_low = round(max(0.01, dcf_mid * 0.85), 2)
        dcf_em_high = round(max(0.01, dcf_mid * 1.25), 2)
        em_notes = "Fixed band fallback — no valuation output supplied"

    # 4/5. Comps ranges from peer quartiles when available.
    #
    # A company whose peer set could not be sourced has no comparables price at
    # all. That used to arrive here as None and raise a TypeError comparing it
    # with a float, which cost the company its whole workbook. A method with no
    # inputs contributes no bar to the range: the football field is a synthesis
    # of what can be valued, and an unsourceable method is absent from it rather
    # than fatal to the page.
    #
    # `mid` is None when the method is unavailable, and the bar is skipped below.
    pe_mid = max(0.01, comps_pe_price) if comps_pe_price is not None else None
    pe_low = round(max(0.01, comps_pe_low), 2) if comps_pe_low else (round(pe_mid * 0.85, 2) if pe_mid else None)
    pe_high = round(max(0.01, comps_pe_high), 2) if comps_pe_high else (round(pe_mid * 1.20, 2) if pe_mid else None)

    ev_mid = max(0.01, comps_ev_ebitda_price) if comps_ev_ebitda_price is not None else None
    ev_low = round(max(0.01, comps_ev_ebitda_low), 2) if comps_ev_ebitda_low else (round(ev_mid * 0.88, 2) if ev_mid else None)
    ev_high = round(max(0.01, comps_ev_ebitda_high), 2) if comps_ev_ebitda_high else (round(ev_mid * 1.22, 2) if ev_mid else None)

    bars = [
        ValuationRangeBar(
            methodology="52-Week Market Trading Range",
            category="Market",
            low_value=mkt_low,
            mid_value=round(cp, 2),
            high_value=mkt_high,
            spread=round(mkt_high - mkt_low, 2),
            notes="Approximated from current price when trading history is unavailable",
        ),
        ValuationRangeBar(
            methodology="DCF Perpetuity Growth (Gordon Growth)",
            category="Intrinsic (DCF)",
            low_value=dcf_pg_low,
            mid_value=dcf_pg_mid if base_valuation_output is not None else round(dcf_mid, 2),
            high_value=dcf_pg_high,
            spread=round(dcf_pg_high - dcf_pg_low, 2),
            notes=pg_notes,
        ),
        ValuationRangeBar(
            methodology="DCF Exit Multiple (EV/EBITDA)",
            category="Intrinsic (DCF)",
            low_value=dcf_em_low,
            mid_value=dcf_em_mid if base_valuation_output is not None else round(dcf_mid, 2),
            high_value=dcf_em_high,
            spread=round(dcf_em_high - dcf_em_low, 2),
            notes=em_notes,
        ),
    ]

    # Comps bars are added only when a peer benchmark was actually published. A
    # bar built from a missing price would carry None into the range arithmetic
    # and into the synthesis below, which is how an unsourceable method turned
    # into a failed export rather than an absent one.
    if pe_mid is not None and pe_low is not None and pe_high is not None:
        bars.append(
            ValuationRangeBar(
                methodology="Public Comps — P/E Multiples",
                category="Relative (Comps)",
                low_value=pe_low,
                mid_value=round(pe_mid, 2),
                high_value=pe_high,
                spread=round(pe_high - pe_low, 2),
                notes="Peer universe 25th to 75th percentile implied prices",
            )
        )
    if ev_mid is not None and ev_low is not None and ev_high is not None:
        bars.append(
            ValuationRangeBar(
                methodology="Public Comps — EV/EBITDA Multiples",
                category="Relative (Comps)",
                low_value=ev_low,
                mid_value=round(ev_mid, 2),
                high_value=ev_high,
                spread=round(ev_high - ev_low, 2),
                notes="Peer universe 25th to 75th percentile implied prices",
            )
        )

    all_lows = [b.low_value for b in bars if b.low_value is not None]
    all_highs = [b.high_value for b in bars if b.high_value is not None]
    all_mids = [b.mid_value for b in bars if b.mid_value is not None]

    return FootballFieldSummary(
        ticker=ticker,
        currency=currency,
        current_market_price=round(cp, 2),
        valuation_bars=bars,
        overall_low=min(all_lows),
        overall_high=max(all_highs),
        mean_fair_value=round(sum(all_mids) / len(all_mids), 2),
    )
