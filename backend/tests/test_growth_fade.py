"""Year one of the revenue forecast carries the measured growth rate.

The defect this pins: the growth fade halved the first forecast year for any
company whose measured growth exceeded 25% and left it at full rate below that,
so a 32.7% grower was published at 16.4% and an 88.3% grower at 44.1%, while a
16.4% grower kept its 16.4%. There is no economic reason a company that grows
slightly faster should have its first forecast year cut in half — the rule had a
threshold discontinuity, not a rationale. On one large-cap that put the
published first-year growth at roughly half the street's estimate, and the
figure appears twice in the product.

The fade now starts in year two and decays geometrically, so the path has no
step change either.
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
    return [
        next(
            a.value
            for a in assumptions
            if a.driver_key == "revenue_growth" and a.period == period and a.scenario == "base"
        )
        for period in FORECAST_PERIODS
    ]


# A steady 3-year history, so the measured CAGR is exactly the rate below.
@pytest.mark.parametrize(
    "annual_growth_pct",
    [2.0, 6.0, 12.0, 16.0, 24.0, 26.0, 33.0, 60.0, 88.0],
)
def test_first_forecast_year_carries_the_measured_rate(annual_growth_pct):
    """Year one equals the measured CAGR, in every growth band.

    The boundary cases matter most: 24% and 26% are either side of the old 25%
    threshold, and they used to produce 24% and 13%.
    """
    base = 1000.0
    factor = 1.0 + annual_growth_pct / 100.0
    revenues = [base * factor**i for i in range(3)]

    growths = _growths(revenues)

    assert growths[0] == pytest.approx(annual_growth_pct, abs=0.05), (
        f"a company measured at {annual_growth_pct}% was published at "
        f"{growths[0]}% for its first forecast year"
    )


def test_no_threshold_discontinuity():
    """A company growing marginally faster must not be published much lower.

    This is the defect stated as a property: the old rule cut year one in half
    for crossing 25%, so a 26% grower landed near a 16% grower's number.
    """
    just_below = _growths([1000.0, 1240.0, 1537.6])[0]   # ~24% CAGR
    just_above = _growths([1000.0, 1260.0, 1587.6])[0]   # ~26% CAGR

    assert just_above > just_below, (
        f"growth published FALLS when measured growth rises: {just_below}% at 24% "
        f"CAGR but {just_above}% at 26% CAGR. The fade rule has a threshold "
        "discontinuity in it."
    )
    # And the gap tracks the measured gap rather than jumping. Crossing a
    # threshold is not a reason to change the published number by more than the
    # change in the history that produced it.
    measured_gap = 2.0
    assert (just_above - just_below) == pytest.approx(measured_gap, abs=0.1), (
        f"measured growth rose {measured_gap}pp across the threshold but the "
        f"published year moved {just_above - just_below:.1f}pp"
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


def test_growth_source_states_the_rule():
    """The published source string must describe the rule that produced it."""
    model = _model([1000.0, 1880.0, 3534.4])
    assumptions = suggest_base_assumptions(model.ratios, model)

    source = next(
        a.source
        for a in assumptions
        if a.driver_key == "revenue_growth" and a.period == "FY27" and a.scenario == "base"
    )

    assert "year one carries it in" in source, (
        "the FY27 growth source does not say that year one is the measured "
        f"rate: {source!r}"
    )
    assert "decays" in source, f"the FY27 growth source does not state the fade: {source!r}"


def test_flat_growth_source_says_it_is_held_flat():
    """A held-flat rate is a different claim from a faded one, and says so."""
    model = _model([1000.0, 1040.0, 1081.6])
    assumptions = suggest_base_assumptions(model.ratios, model)

    source = next(
        a.source
        for a in assumptions
        if a.driver_key == "revenue_growth" and a.period == "FY27" and a.scenario == "base"
    )

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
    fy27 = forecast_spec.forecast.get_value("canonical.is.revenue", "FY27", "base")
    implied = (fy27 / last_actual - 1) * 100

    published = next(
        a.value
        for a in forecast_spec.assumptions
        if a.driver_key == "revenue_growth" and a.period == "FY27" and a.scenario == "base"
    )

    assert implied == pytest.approx(published, abs=0.1), (
        f"FY27 revenue of {fy27} on {last_actual} implies {implied:.2f}% growth, "
        f"but the sheet publishes {published}%"
    )
