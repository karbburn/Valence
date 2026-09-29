from __future__ import annotations

"""
Trading Comparables (Public Comps) Valuation Module.

Constructs industry peer comps table, calculates forward and trailing valuation multiples
(EV/Sales, EV/EBITDA, P/E, P/B, FCF Yield, ROIC), derives quartile benchmarks
(25th, Median, Mean, 75th), and computes implied share price ranges.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from backend.valuation.peer_multiples import compute_peer_multiples


class PeerComp(BaseModel):
    ticker: str
    company_name: str
    market: str
    share_price: float
    market_cap: float
    enterprise_value: float
    revenue_ltm: float
    ebitda_ltm: float
    net_income_ltm: float
    ev_revenue: float
    ev_ebitda: float
    pe_ratio: float
    fcf_yield_pct: float
    roic_pct: float
    # When the underlying figures were reported, so a reader can judge whether
    # a multiple is struck on current results or on last year's.
    financials_period: str = ""
    balance_sheet_as_of: str = ""


class CompsBenchmark(BaseModel):
    metric: str
    min_val: float
    p25: float
    median: float
    mean: float
    p75: float
    max_val: float


class ImpliedCompsValuation(BaseModel):
    methodology: str
    multiple_metric: str
    benchmark_multiple: float
    target_metric_value: float
    implied_ev: float
    net_debt: float
    implied_equity_value: float
    shares_outstanding: float
    implied_share_price: float


class TradingCompsAnalysis(BaseModel):
    peers: List[PeerComp]
    benchmarks: Dict[str, CompsBenchmark]
    implied_valuations: List[ImpliedCompsValuation]
    quartile_implied_prices: Dict[str, Dict[str, float]] = {}
    # Set when no benchmark is published, so the caller says so on the page
    # rather than rendering an empty table the reader has to interpret.
    unavailable_reason: Optional[str] = None


# Peer ROSTER by sector / industry.
#
# A roster is legitimate configuration: it says which companies belong in a peer
# group. The MULTIPLES that used to sit in this table alongside each name did
# not. They were hand-entered constants with placeholder share prices, market
# caps, revenues and EBITDA behind them, and they were presented to the reader
# as market data, then used to derive the implied valuation range and a
# football-field bar. Every multiple in a comps table is now computed live from
# the peer's own reported figures and the most recent reported balance sheet.
#
# `exchange` selects the listing a peer is priced on, because a company's two
# listings can carry different currencies and different share counts.
SECTOR_PEERS: Dict[str, List[Dict[str, str]]] = {
    "technology": [
        {"ticker": "MSFT", "name": "Microsoft Corp", "exchange": "US"},
        {"ticker": "AAPL", "name": "Apple Inc", "exchange": "US"},
        {"ticker": "GOOGL", "name": "Alphabet Inc", "exchange": "US"},
        {"ticker": "META", "name": "Meta Platforms", "exchange": "US"},
        {"ticker": "NVDA", "name": "NVIDIA Corp", "exchange": "US"},
    ],
    "automotive": [
        {"ticker": "MARUTI", "name": "Maruti Suzuki", "exchange": "NS"},
        {"ticker": "M&M", "name": "Mahindra & Mahindra", "exchange": "NS"},
        {"ticker": "HYUNDAI", "name": "Hyundai Motor", "exchange": "KR"},
        {"ticker": "TSLA", "name": "Tesla Inc", "exchange": "US"},
    ],
    "energy_utilities": [
        {"ticker": "NTPC", "name": "NTPC Limited", "exchange": "NS"},
        {"ticker": "POWERGRID", "name": "Power Grid Corp", "exchange": "NS"},
        {"ticker": "TATAPOWER", "name": "Tata Power", "exchange": "NS"},
        {"ticker": "NEE", "name": "NextEra Energy", "exchange": "US"},
    ],
    "it_services": [
        {"ticker": "TCS", "name": "Tata Consultancy Services", "exchange": "NS"},
        {"ticker": "INFY", "name": "Infosys Limited", "exchange": "NS"},
        {"ticker": "WIPRO", "name": "Wipro Limited", "exchange": "NS"},
        {"ticker": "ACN", "name": "Accenture plc", "exchange": "US"},
    ],
    "capital_goods_epc": [
        {"ticker": "SIEMENS", "name": "Siemens India", "exchange": "NS"},
        {"ticker": "ABB", "name": "ABB India", "exchange": "NS"},
        {"ticker": "BEL", "name": "Bharat Electronics", "exchange": "NS"},
        {"ticker": "KEC", "name": "KEC International", "exchange": "NS"},
        {"ticker": "CAT", "name": "Caterpillar Inc", "exchange": "US"},
    ],
}

# Below this many sourced peers a benchmark is not published at all. A median of
# two companies is not a peer benchmark, and printing one invites a reader to
# treat it as a sector consensus.
MIN_PEERS_FOR_BENCHMARK = 3


def _calc_stats(values: List[float]) -> CompsBenchmark:
    if not values:
        return CompsBenchmark(metric="", min_val=0, p25=0, median=0, mean=0, p75=0, max_val=0)
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mean_val = sum(sorted_vals) / n
    min_val = sorted_vals[0]
    max_val = sorted_vals[-1]
    median = sorted_vals[n // 2] if n % 2 != 0 else (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0
    p25 = sorted_vals[int(n * 0.25)]
    p75 = sorted_vals[int(n * 0.75)]
    return CompsBenchmark(
        metric="",
        min_val=round(min_val, 2),
        p25=round(p25, 2),
        median=round(median, 2),
        mean=round(mean_val, 2),
        p75=round(p75, 2),
        max_val=round(max_val, 2),
    )


def compute_trading_comps(
    target_ticker: str,
    target_sector: str,
    target_revenue_fy27: float,
    target_ebitda_fy27: float,
    target_net_profit_fy27: float,
    net_debt: float,
    shares_outstanding: float,
) -> TradingCompsAnalysis:
    """Compute trading comps analysis and derive implied peer valuations."""
    # Find matching peer group
    sector_key = "technology"
    sec_lower = f"{target_sector} {target_ticker}".lower()
    if "auto" in sec_lower or "motor" in sec_lower:
        sector_key = "automotive"
    elif "energy" in sec_lower or "green" in sec_lower or "power" in sec_lower or "util" in sec_lower:
        sector_key = "energy_utilities"
    elif "service" in sec_lower or "tcs" in sec_lower or "infy" in sec_lower or "hcl" in sec_lower or "wipro" in sec_lower:
        sector_key = "it_services"
    elif "epc" in sec_lower or "lt" in sec_lower or "larsen" in sec_lower or "construct" in sec_lower or "capital" in sec_lower or "infra" in sec_lower:
        sector_key = "capital_goods_epc"

    # A comparable table measures the target against its peers. The target in the
    # table measures the target against itself, and because the target is the
    # subject of the valuation it enters the statistics as an observation of its
    # own multiple rather than as a reference point. It was not cosmetic: with
    # NVIDIA in its own technology peer set at 18.16x EV/Revenue against a peer
    # median of 10.69x, it dragged the EV/EBITDA median from 21.27x to 23.60x and
    # moved the implied comps price by roughly a quarter. A median containing the
    # subject is not a peer median.
    target_key = target_ticker.strip().upper()
    peers_data = [
        entry
        for entry in SECTOR_PEERS.get(sector_key, SECTOR_PEERS["technology"])
        if entry["ticker"].strip().upper() != target_key
    ]
    if not peers_data:
        # Every name in the group is the target. Falling back to the wider roster
        # beats returning an empty table with an undefined median, and the target
        # is still excluded from it.
        peers_data = [
            entry
            for entry in SECTOR_PEERS["technology"]
            if entry["ticker"].strip().upper() != target_key
        ]

    peers: List[PeerComp] = []
    ev_revs: List[float] = []
    ev_ebitdas: List[float] = []
    pes: List[float] = []
    fcfs: List[float] = []
    roics: List[float] = []

    for entry in peers_data:
        live = compute_peer_multiples(entry["ticker"], entry["name"], entry["exchange"])
        if live is None:
            # A peer that cannot be sourced on price, share count, results and
            # balance sheet is left out. It is not filled with a placeholder,
            # because a placeholder in a peer table is indistinguishable from a
            # real observation once it is on the page.
            continue
        peers.append(
            PeerComp(
                ticker=live.ticker,
                company_name=live.company_name,
                market=live.market,
                share_price=live.share_price,
                market_cap=live.market_cap,
                enterprise_value=live.enterprise_value,
                revenue_ltm=live.revenue_ttm,
                ebitda_ltm=live.ebitda_ttm,
                net_income_ltm=live.net_income_ttm,
                ev_revenue=live.ev_revenue,
                ev_ebitda=live.ev_ebitda,
                pe_ratio=live.pe_ratio,
                fcf_yield_pct=live.fcf_yield_pct,
                roic_pct=live.roic_pct,
                financials_period=live.financials_period,
                balance_sheet_as_of=live.balance_sheet_as_of,
            )
        )
        if live.ev_revenue > 0:
            ev_revs.append(live.ev_revenue)
        if live.ev_ebitda > 0:
            ev_ebitdas.append(live.ev_ebitda)
        if live.pe_ratio > 0:
            pes.append(live.pe_ratio)
        if live.fcf_yield_pct:
            fcfs.append(live.fcf_yield_pct)
        if live.roic_pct:
            roics.append(live.roic_pct)

    # A benchmark built from too few sourced peers is not a peer benchmark, so
    # none is published and the caller is told the section is unavailable
    # rather than being handed a median of two companies.
    if len(ev_revs) < MIN_PEERS_FOR_BENCHMARK:
        return TradingCompsAnalysis(
            peers=peers,
            benchmarks={},
            implied_valuations=[],
            quartile_implied_prices={},
            unavailable_reason=(
                f"only {len(ev_revs)} of {len(peers_data)} peers could be sourced from "
                "reported figures, so no benchmark is published"
            ),
        )

    benchmarks = {
        "ev_revenue": _calc_stats(ev_revs),
        "ev_ebitda": _calc_stats(ev_ebitdas),
        "pe_ratio": _calc_stats(pes),
        "fcf_yield": _calc_stats(fcfs),
        "roic": _calc_stats(roics),
    }

    # Implied Valuation derivations
    implied_vals: List[ImpliedCompsValuation] = []
    sh = max(1.0, shares_outstanding)

    # 1. EV / EBITDA (Median & P25-P75)
    med_ebitda = benchmarks["ev_ebitda"].median
    impl_ev_ebitda = target_ebitda_fy27 * med_ebitda
    impl_eq_ebitda = impl_ev_ebitda - net_debt
    impl_price_ebitda = max(0.0, impl_eq_ebitda / sh)
    implied_vals.append(
        ImpliedCompsValuation(
            methodology="Public Comps EV/EBITDA (Median)",
            multiple_metric="EV/EBITDA",
            benchmark_multiple=med_ebitda,
            target_metric_value=round(target_ebitda_fy27, 2),
            implied_ev=round(impl_ev_ebitda, 2),
            net_debt=round(net_debt, 2),
            implied_equity_value=round(impl_eq_ebitda, 2),
            shares_outstanding=round(sh, 2),
            implied_share_price=round(impl_price_ebitda, 2),
        )
    )

    # 2. P/E Multiple (Median)
    med_pe = benchmarks["pe_ratio"].median
    impl_eq_pe = target_net_profit_fy27 * med_pe
    impl_ev_pe = impl_eq_pe + net_debt
    impl_price_pe = max(0.0, impl_eq_pe / sh)
    implied_vals.append(
        ImpliedCompsValuation(
            methodology="Public Comps P/E (Median)",
            multiple_metric="P/E",
            benchmark_multiple=med_pe,
            target_metric_value=round(target_net_profit_fy27, 2),
            implied_ev=round(impl_ev_pe, 2),
            net_debt=round(net_debt, 2),
            implied_equity_value=round(impl_eq_pe, 2),
            shares_outstanding=round(sh, 2),
            implied_share_price=round(impl_price_pe, 2),
        )
    )

    # 3. EV / Revenue (Median)
    med_rev = benchmarks["ev_revenue"].median
    impl_ev_rev = target_revenue_fy27 * med_rev
    impl_eq_rev = impl_ev_rev - net_debt
    impl_price_rev = max(0.0, impl_eq_rev / sh)
    implied_vals.append(
        ImpliedCompsValuation(
            methodology="Public Comps EV/Revenue (Median)",
            multiple_metric="EV/Revenue",
            benchmark_multiple=med_rev,
            target_metric_value=round(target_revenue_fy27, 2),
            implied_ev=round(impl_ev_rev, 2),
            net_debt=round(net_debt, 2),
            implied_equity_value=round(impl_eq_rev, 2),
            shares_outstanding=round(sh, 2),
            implied_share_price=round(impl_price_rev, 2),
        )
    )

    # Quartile-implied share prices feed the football field's relative ranges.
    sh_safe = max(1.0, shares_outstanding)
    ebitda_prices = {}
    for tag in ("p25", "median", "p75"):
        eq = target_ebitda_fy27 * getattr(benchmarks["ev_ebitda"], tag) - net_debt
        ebitda_prices[tag] = max(0.0, eq / sh_safe)
    pe_prices = {
        tag: max(0.0, target_net_profit_fy27 * getattr(benchmarks["pe_ratio"], tag) / sh_safe)
        for tag in ("p25", "median", "p75")
    }

    return TradingCompsAnalysis(
        peers=peers,
        benchmarks=benchmarks,
        implied_valuations=implied_vals,
        quartile_implied_prices={
            "ev_ebitda": {k: round(v, 2) for k, v in ebitda_prices.items()},
            "pe_ratio": {k: round(v, 2) for k, v in pe_prices.items()},
        },
    )
