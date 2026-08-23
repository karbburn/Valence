"""Football field ranges are genuinely re-priced, not fixed multipliers."""

import pytest

from backend.models.spec.valuation import (
    DCFBridge,
    FCFFPeriod,
    TerminalValue,
    ValuationOutput,
    WACCBreakdown,
)
from backend.valuation.comps import compute_trading_comps
from backend.valuation.football_field import (
    FootballFieldSummary,
    _reprice_dcf,
    compute_football_field,
)


def _base_output() -> ValuationOutput:
    fcffs = []
    for i, p in enumerate(["FY27", "FY28", "FY29", "FY30", "FY31"]):
        fcff = 100.0 + 10 * i
        w = 0.12
        df = 1.0 / ((1.0 + w) ** (i + 0.5))
        fcffs.append(
            FCFFPeriod(period=p, ebit=150.0, tax_rate=25.0, nopat=112.5, da=20.0,
                       capex=30.0, delta_working_capital=5.0, fcff=fcff,
                       discount_factor=df, pv_fcff=fcff * df)
        )
    return ValuationOutput(
        scenario="base",
        wacc=WACCBreakdown(wacc=12.0),
        fcff_by_period=fcffs,
        terminal_value=TerminalValue(terminal_growth_rate=4.0, exit_multiple=18.0,
                                     final_year_fcff=140.0, final_year_ebitda=400.0),
        dcf_bridge=DCFBridge(less_net_debt=-500.0, shares_outstanding=50.0),
    )


def test_reprice_matches_hand_computed_bridge():
    out = _base_output()
    price = _reprice_dcf(out, wacc_pct=12.0, terminal_growth_rate=4.0)
    w, g = 0.12, 0.04
    stream = [100.0, 110.0, 120.0, 130.0, 140.0]
    sum_pv = sum(f / ((1 + w) ** (i + 0.5)) for i, f in enumerate(stream))
    tv = 140.0 * (1 + g) / (w - g) / ((1 + w) ** 5)
    expected = (sum_pv + tv + 500.0) / 50.0
    assert price == pytest.approx(expected, rel=1e-9)


def test_perturbed_ranges_move_in_the_right_direction():
    out = _base_output()
    base_price = _reprice_dcf(out, 12.0, 4.0)
    low = _reprice_dcf(out, 11.0, 3.5)
    high = _reprice_dcf(out, 13.0, 4.5)
    # Cheaper discounting lifts value; the paired shifts need not bracket base
    # monotonically, but each extreme must move in its WACC's direction vs the other.
    assert low > high


def test_summary_bars_are_ordered_and_consensus_is_gone():
    out = _base_output()
    base_price = _reprice_dcf(out, 12.0, 4.0)
    ff = compute_football_field(
        ticker="T", currency="INR", current_price=900.0,
        dcf_base_price=base_price, dcf_bull_price=base_price * 1.2, dcf_bear_price=base_price * 0.8,
        comps_pe_price=950.0, comps_ev_ebitda_price=1050.0,
        base_valuation_output=out,
        comps_pe_low=810.0, comps_pe_high=1140.0,
        comps_ev_ebitda_low=924.0, comps_ev_ebitda_high=1281.0,
    )
    assert isinstance(ff, FootballFieldSummary)
    methodologies = [b.methodology for b in ff.valuation_bars]
    assert len(methodologies) == 5
    assert not any("Consensus" in m for m in methodologies)
    for bar in ff.valuation_bars:
        assert bar.low_value <= bar.mid_value <= bar.high_value
        assert bar.spread == pytest.approx(bar.high_value - bar.low_value, abs=0.02)
    mids = [b.mid_value for b in ff.valuation_bars]
    assert ff.mean_fair_value == pytest.approx(sum(mids) / len(mids), abs=0.01)


def test_comps_quartile_prices_flow_into_analysis():
    res = compute_trading_comps(
        target_ticker="INFY", target_sector="IT Services",
        target_revenue_fy27=50000.0, target_ebitda_fy27=12000.0,
        target_net_profit_fy27=8000.0, net_debt=-20000.0, shares_outstanding=412.45,
    )
    q = res.quartile_implied_prices
    assert set(q) == {"ev_ebitda", "pe_ratio"}
    for kind in ("ev_ebitda", "pe_ratio"):
        assert q[kind]["p25"] <= q[kind]["median"] <= q[kind]["p75"]
