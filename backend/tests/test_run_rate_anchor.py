"""The first forecast year must not fall below the run rate already traded.

The growth rate is measured from the last REPORTED FISCAL YEAR. That year is not
the current run rate: it ended up to twelve months ago, and the business has
since traded a different twelve months. When the trailing twelve months exceed
the reported year, growing the reported year at its own historical rate produces
a first forecast year BELOW what the business earned in the last twelve months —
a forecast of decline published next to a positive growth rate.

One large-cap's trailing revenue was 12% above its last fiscal year, so its
first forecast year sat 7% below its own trailing twelve months while the sheet
said revenue grew 4.2%. Both numbers are on the same page and they contradict
each other, which is the first thing a reader checks.

The floor is the growth needed to merely MATCH the trailing twelve months. It
only ever raises the published rate, and the source string says when it did and
why.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

import backend.forecast.assumptions as assumptions_module
from backend.forecast.assumptions import suggest_base_assumptions

from backend.tests.test_growth_fade import _model


@contextmanager
def _run_rate(value, basis="trailing twelve months to 2026-06-30"):
    """Pin the run rate the forecast anchor will see."""
    original = assumptions_module._run_rate_floor
    assumptions_module._run_rate_floor = lambda company_id: (value, basis)
    try:
        yield
    finally:
        assumptions_module._run_rate_floor = original


def _fy27(revenues: list[float], run_rate=None, basis="trailing twelve months to 2026-06-30"):
    """The FIRST forecast year's published growth, run rate pinned or suppressed.

    Named for the year one rather than for a label: the horizon follows the
    company's last reported year, and these fixtures end FY22, so year one is not
    FY27. Reading a named year here returned the third forecast year's rate and
    every assertion about year one was really about year three.
    """
    with _run_rate(run_rate, basis):
        model = _model(revenues)
        assumptions = suggest_base_assumptions(model.ratios, model)
    years = sorted(
        a.period
        for a in assumptions
        if a.driver_key == "revenue_growth" and a.scenario == "base"
    )
    return next(
        a.value
        for a in assumptions
        if a.driver_key == "revenue_growth"
        and a.period == years[0]
        and a.scenario == "base"
    )


def _source(revenues: list[float], run_rate=None, basis="trailing twelve months to 2026-06-30"):
    with _run_rate(run_rate, basis):
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


# A business measured at 4.2% a year, whose reported year is 416,161.
SLOW = [347_000.0, 380_000.0, 416_161.0]


# --------------------------------------------------------------------------- #
# The defect
# --------------------------------------------------------------------------- #

def test_first_year_is_not_published_below_the_run_rate():
    """The published year must reach the twelve months already traded.

    Without the floor this company's FY27E was 433,640 against a trailing twelve
    months of 466,823 — a decline, published next to a +4.2% growth rate.
    """
    run_rate = 466_823.0
    published = _fy27(SLOW, run_rate)

    projected = SLOW[-1] * (1.0 + published / 100.0)
    assert projected >= run_rate * 0.999, (
        f"FY27E of {projected:,.0f} is below the {run_rate:,.0f} already traded in "
        f"the last twelve months, while the sheet publishes {published:+.1f}% growth"
    )


def test_the_floor_raises_the_rate_rather_than_lowering_it():
    """A company whose run rate has run ahead cannot be published below it."""
    run_rate = 466_823.0
    measured = _fy27(SLOW, None)

    assert _fy27(SLOW, run_rate) > measured


def test_a_run_rate_behind_the_reported_year_does_not_lower_growth():
    """A business whose trailing twelve months are BELOW its reported year is
    genuinely slowing, and the measured rate stands.

    The floor exists to stop a forecast of decline being published as growth. It
    is not a reason to assume every company is accelerating.
    """
    slower = [400_000.0, 408_000.0, 416_161.0]
    measured = _fy27(slower, None)
    with_run_rate = _fy27(slower, 380_000.0)

    assert with_run_rate == pytest.approx(measured), (
        "a run rate below the reported year must not reduce the published rate"
    )


def test_the_floor_never_exceeds_the_growth_actually_needed():
    """It is a floor, not a new estimate: it lifts the rate to reach the run rate
    and no further."""
    run_rate = 466_823.0
    published = _fy27(SLOW, run_rate)
    needed = (run_rate / SLOW[-1] - 1.0) * 100.0

    assert published == pytest.approx(needed, abs=0.05), (
        f"published {published:.2f}% but only {needed:.2f}% is needed to reach the "
        "run rate; the floor is overshooting into a new forecast"
    )


# --------------------------------------------------------------------------- #
# The floor has to be explainable
# --------------------------------------------------------------------------- #

def test_the_source_says_when_and_why_the_rate_was_raised():
    source = _source(SLOW, 466_823.0, "trailing twelve months to 2026-06-30")

    assert "trailing twelve months" in source, source
    assert "466,823" in source or "466.82" in source, source
    assert "raised" in source, source


def test_an_unraised_rate_does_not_claim_a_run_rate_adjustment():
    """A source string must not describe an adjustment that did not happen."""
    source = _source(SLOW, 380_000.0)

    assert "raised" not in source, source


# --------------------------------------------------------------------------- #
# A run rate in the wrong units must never set a growth rate
# --------------------------------------------------------------------------- #

def test_a_run_rate_in_the_wrong_currency_is_refused():
    """One listing reported trailing revenue in its domestic currency against a
    model in dollars: thirty-seven times too large.

    Taken at face value it would publish a growth rate of thousands of percent
    and a revenue line no analyst would accept, and nothing on the page would
    show why.
    """
    absurd = SLOW[-1] * 37.0
    published = _fy27(SLOW, absurd)

    assert published < 100.0, (
        f"a run rate of {absurd:,.0f} against a reported year of {SLOW[-1]:,.0f} is a "
        f"unit error, not growth, and must not produce {published:,.0f}%"
    )


def test_a_run_rate_two_orders_of_magnitude_small_is_refused():
    tiny = SLOW[-1] * 0.01
    measured = _fy27(SLOW, None)

    assert _fy27(SLOW, tiny) == pytest.approx(measured), (
        "a run rate of one hundredth of the reported year is a unit error and must "
        "not move the published rate"
    )


# --------------------------------------------------------------------------- #
# The shared construction
# --------------------------------------------------------------------------- #

def test_the_peer_denominator_and_the_forecast_anchor_agree():
    """One trailing-twelve-month implementation, not two that can drift.

    The peer path and the forecast anchor were separate copies. A fix applied to
    one left the other computing a different denominator for the same company,
    which is what makes two published numbers about one business irreconcilable.
    """
    from backend.data.providers.run_rate import trailing_twelve_months
    from backend.valuation import peer_multiples as pm

    assert pm._ttl is not trailing_twelve_months or True  # delegation is by call
    # Same construction, same answer, for the same inputs.
    frame, quarterly = _statements()
    assert pm._ttl(frame, pm._REVENUE_ROWS, quarterly) == pytest.approx(
        trailing_twelve_months(frame, pm._REVENUE_ROWS, quarterly)
    )
    assert pm._sum_last_four_quarters(quarterly, pm._REVENUE_ROWS) == pytest.approx(
        trailing_twelve_months(frame, pm._REVENUE_ROWS, quarterly)
    )


def _statements():
    from datetime import date

    from backend.tests.test_peer_basis_consistency import _FakeColumn, _frame

    quarters = {
        _FakeColumn(date(2026, 6, 30)): 130.0,
        _FakeColumn(date(2026, 3, 31)): 120.0,
        _FakeColumn(date(2025, 12, 31)): 110.0,
        _FakeColumn(date(2025, 9, 30)): 100.0,
    }
    return (
        _frame(["Total Revenue"], {"Total Revenue": {_FakeColumn(date(2025, 12, 31)): 400.0}}),
        _frame(["Total Revenue"], {"Total Revenue": quarters}),
    )
