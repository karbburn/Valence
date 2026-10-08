"""Year one of the revenue forecast opens one step down the fade curve.

The rule this pins: the first forecast year is the measured CAGR times the
band decay (88.3 x 0.55 = 48.6 year one), and the same geometric decay
continues after. Carrying the full supercycle rate one extra year was the
aggressive choice and nothing defended it, so the path opens decayed rather
than holding the peak and then stepping off it.

An earlier defect stays removed: the first year used to be halved above 25%
and left whole below it, a threshold discontinuity with no rationale. The
bands still set different decay rates, so the published year one steps across
a band boundary; inside a band the path moves smoothly with the history.

The fade is geometric from year one, and the stable band (decay 1.0) still
publishes the measured rate flat.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from backend.forecast.assumptions import suggest_base_assumptions
from backend.models.statements.balance_sheet import BalanceSheet
from backend.models.statements.cash_flow import CashFlowStatement
from backend.models.statements.historical_model import HistoricalModel
from backend.models.statements.income_statement import (
    IncomeStatement,
    IncomeStatementLineItem,
)
from backend.models.statements.ratios import HistoricalRatios
from backend.models.spec.forecast import FORECAST_PERIODS

COMPANY_ID = "fade_us"


def _income(periods: list[str], revenues: list[float]) -> IncomeStatement:
    """A company whose only reported line is revenue."""
    return IncomeStatement(
        company_id=COMPANY_ID,
        periods=periods,
        line_items=[
            IncomeStatementLineItem(
                canonical_key="canonical.is.revenue",
                display_label="Revenue",
                values_by_period=dict(zip(periods, revenues)),
            )
        ],
    )


def _model(revenues: list[float]) -> HistoricalModel:
    periods = [f"FY{20 + i}" for i in range(len(revenues))]
    empty_balance = BalanceSheet(company_id=COMPANY_ID, periods=periods, line_items=[])
    empty_cash = CashFlowStatement(company_id=COMPANY_ID, periods=periods, line_items=[])
    return HistoricalModel(
        company_id=COMPANY_ID,
        periods=periods,
        income_statement=_income(periods, revenues),
        balance_sheet=empty_balance,
        cash_flow_statement=empty_cash,
        ratios=HistoricalRatios(company_id=COMPANY_ID, periods=periods, ratio_series=[]),
    )


def _growths(revenues: list[float]) -> list[float]:
    """Published revenue-growth path for a company with the given revenue history.

    The run-rate anchor is stubbed out. It is a separate rule with its own tests,
    and leaving it live would make a test about the fade depend on a market feed.
    """
    with _no_run_rate():
        return _growths_live(revenues)


@contextmanager
def _no_run_rate():
    """Isolate the fade rule from the run-rate anchor."""
    import backend.forecast.assumptions as assumptions_module

    original = assumptions_module._run_rate_floor
    assumptions_module._run_rate_floor = lambda company_id: (None, "stubbed")
    try:
        yield
    finally:
        assumptions_module._run_rate_floor = original


def _growths_live(revenues: list[float]) -> list[float]:
    model = _model(revenues)
    assumptions = suggest_base_assumptions(model.ratios, model)
    # The horizon follows the company's last reported year, so it is read from the
    # engine rather than from the platform default. These fixtures end FY24, which
    # means the engine publishes FY25 onward.
    periods = sorted(
        a.period
        for a in assumptions
        if a.driver_key == "revenue_growth" and a.scenario == "base"
    )
    return [
        next(
            a.value
            for a in assumptions
            if a.driver_key == "revenue_growth" and a.period == period and a.scenario == "base"
        )
        for period in periods
    ]


# A steady 3-year history, so the measured CAGR is exactly the rate below,
# and the published year one is that rate times the band decay.
@pytest.mark.parametrize(
    "annual_growth_pct,decay",
    [
        (2.0, 1.0),
        (6.0, 1.0),
        (12.0, 0.82),
        (16.0, 0.82),
        (24.0, 0.82),
        (26.0, 0.55),
        (33.0, 0.55),
        (60.0, 0.55),
        (88.0, 0.55),
    ],
)
def test_first_forecast_year_opens_one_step_down_the_curve(annual_growth_pct, decay):
    """Year one equals the measured CAGR times the band decay.

    The stable band still publishes the measured rate in full; every other
    band fades from the first year. The boundary cases matter most: 24% and
    26% sit either side of the 25% band edge and publish 19.7% and 14.3%.
    """
    base = 1000.0
    factor = 1.0 + annual_growth_pct / 100.0
    revenues = [base * factor**i for i in range(3)]

    growths = _growths(revenues)
    expected = annual_growth_pct * decay

    assert growths[0] == pytest.approx(expected, abs=0.05), (
        f"a company measured at {annual_growth_pct}% was published at "
        f"{growths[0]}% for its first forecast year, expected {expected:.2f}%"
    )


def test_no_discontinuity_within_a_band():
    """Two companies measured a point apart inside one band publish a point apart.

    The bands set different decay rates, so crossing a boundary steps the
    published year one by design. Inside a band nothing may jump: the gap in
    the published year tracks the gap in the measured history times the decay.
    """
    lower = _growths([1000.0, 1320.0, 1742.4])[0]   # ~32% CAGR, high band
    upper = _growths([1000.0, 1330.0, 1768.9])[0]   # ~33% CAGR, high band

    assert upper > lower, (
        f"growth published FALLS when measured growth rises: {lower}% at 32% "
        f"CAGR but {upper}% at 33% CAGR. The fade rule has a discontinuity "
        "inside the band."
    )
    measured_gap = 1.0
    assert (upper - lower) == pytest.approx(measured_gap * 0.55, abs=0.1), (
        f"measured growth rose {measured_gap}pp inside the band but the "
        f"published year moved {upper - lower:.2f}pp"
    )


def test_high_growth_path_fades_geometrically_from_year_one():
    """An 88% grower opens at 48.4 and decays by the same factor each year.

    Year one is already faded rather than carrying 88% one extra year, and
    every later year multiplies by the same decay, so the path has no step
    change in it.
    """
    base = 1000.0
    factor = 1.0 + 88.0 / 100.0
    growths = _growths([base * factor**i for i in range(3)])

    expected = [round(88.0 * 0.55 ** (i + 1), 2) for i in range(5)]

    assert growths == pytest.approx(expected, abs=0.01), (
        f"an 88% grower published {growths} against an expected {expected}"
    )


@pytest.mark.parametrize("annual_growth_pct", [2.0, 12.0, 33.0, 88.0])
def test_fade_is_monotonic_and_never_reverses(annual_growth_pct):
    """Growth fades, but never climbs back up."""
    base = 1000.0
    factor = 1.0 + annual_growth_pct / 100.0
    growths = _growths([base * factor**i for i in range(3)])

    for earlier, later in zip(growths, growths[1:]):
        assert later <= earlier + 1e-9, (
            f"growth rose from {earlier}% to {later}% at a {annual_growth_pct}% "
            "base rate; the fade is not a fade"
        )


def test_stable_growth_is_held_flat():
    """A company measured below the fade threshold keeps its rate throughout.

    Fading a business whose growth has been flat for three years would assert a
    deceleration that the history does not show.
    """
    growths = _growths([1000.0, 1040.0, 1081.6])  # ~4% CAGR

    assert all(g == pytest.approx(4.0, abs=0.05) for g in growths), growths


def test_fade_reaches_a_mature_rate_over_the_forecast():
    """A high grower converges towards a mature rate rather than staying hot."""
    base = 1000.0
    factor = 1.0 + 88.0 / 100.0
    growths = _growths([base * factor**i for i in range(3)])

    assert growths[-1] < 20.0, (
        f"an 88% grower is still growing {growths[-1]}% in the final forecast "
        "year; the fade is not doing any work"
    )
    assert growths[-1] > 0.0, "growth faded through zero into decline"


def _year_one_source(revenues: list[float]) -> str:
    """The published source string for this company's FIRST forecast year.

    Read from the engine rather than named, because the horizon follows the last
    reported year: these fixtures end FY24, so year one is FY25.
    """
    model = _model(revenues)
    assumptions = suggest_base_assumptions(model.ratios, model)
    years = sorted(
        a.period
        for a in assumptions
        if a.driver_key == "revenue_growth" and a.scenario == "base"
    )
    return next(
        a.source
        for a in assumptions
        if a.driver_key == "revenue_growth"
        and a.period == years[0]
        and a.scenario == "base"
    )


def test_growth_source_states_the_rule():
    """The published source string must describe the rule that produced it."""
    source = _year_one_source([1000.0, 1880.0, 3534.4])

    assert "fade starts at year one" in source, (
        f"the year-one growth source does not say the fade starts at year one: "
        f"{source!r}"
    )
    assert "decays" in source, f"the year-one growth source does not state the fade: {source!r}"


def test_flat_growth_source_says_it_is_held_flat():
    """A held-flat rate is a different claim from a faded one, and says so."""
    source = _year_one_source([1000.0, 1040.0, 1081.6])

    assert "held flat" in source, (
        f"a company whose growth is held flat does not say so: {source!r}"
    )


def test_forecast_revenue_matches_the_published_growth_rate():
    """The revenue line must actually grow at the rate the assumption claims.

    The two are published side by side, so a disagreement between them is a
    visible contradiction regardless of which one is right.
    """
    from backend.forecast.pipeline import run as run_forecast_pipeline

    forecast_spec = run_forecast_pipeline(_model([1000.0, 1880.0, 3534.4]))
    last_actual = forecast_spec.historicals.get_value(
        "canonical.is.revenue", forecast_spec.historicals.periods[-1]
    )
    # The FIRST forecast year, not a named one. The horizon follows the company's
    # last reported year, and this check is about the gap between the revenue line
    # and the rate published beside it in year one — a later year's revenue has
    # compounded through three rates and is not what the year-one driver claims.
    year_one = forecast_spec.forecast.periods[0]
    year_one_revenue = forecast_spec.forecast.get_value(
        "canonical.is.revenue", year_one, "base"
    )
    implied = (year_one_revenue / last_actual - 1) * 100

    published = next(
        a.value
        for a in forecast_spec.assumptions
        if a.driver_key == "revenue_growth"
        and a.period == year_one
        and a.scenario == "base"
    )

    assert implied == pytest.approx(published, abs=0.1), (
        f"{year_one} revenue of {year_one_revenue} on {last_actual} implies "
        f"{implied:.2f}% growth, but the sheet publishes {published}%"
    )
