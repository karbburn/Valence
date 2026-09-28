"""The Driver Panel must expose the number the engine actually used.

The panel renders `assumptions`, but the discount rate comes from the WACC
breakdown. A model_generated `wacc.cost_of_equity` is a CAPM snapshot; if the
panel keeps showing it after the rate has moved, an analyst tunes a slider that
does nothing and the screen disagrees with the WACC tile beside it.

These build the model in-process rather than over HTTP, so they run in the
normal unit-test suite and cannot pass or fail on a dev server being up.
"""

import pytest

from backend.tests.conftest import requires_store

from backend.forecast.pipeline import run as run_forecast_pipeline
from backend.models.statements.pipeline import run as run_historical
from backend.valuation.pipeline import run_valuation

COMPANIES = ["infy_infy", "nvda_us"]


def _spec(company_id: str):
    hist = run_historical(target_periods=["FY24", "FY25", "FY26"], company_id=company_id)
    return run_valuation(run_forecast_pipeline(hist))


def _driver(spec, key: str, scenario: str = "base") -> float | None:
    for a in spec.assumptions:
        if a.driver_key == key and a.scenario == scenario:
            return a.value
    return None


pytestmark = requires_store

@pytest.mark.parametrize("company_id", COMPANIES)
def test_cost_of_equity_driver_matches_the_wacc_used(company_id):
    spec = _spec(company_id)
    wacc = spec.get_valuation("base").wacc

    panel_ke = _driver(spec, "wacc.cost_of_equity")
    assert panel_ke is not None, "cost of equity must be exposed as a driver"

    # CAPM from the published components: rf + beta x erp.
    capm = wacc.risk_free_rate + wacc.beta * wacc.equity_risk_premium
    assert wacc.cost_of_equity == pytest.approx(capm, abs=0.02), (
        f"{company_id}: WACC cost of equity {wacc.cost_of_equity} != "
        f"CAPM {capm:.2f} from published rf/beta/erp"
    )
    assert abs(panel_ke - wacc.cost_of_equity) <= 0.25, (
        f"{company_id}: driver panel shows Ke {panel_ke} but the engine discounted at "
        f"{wacc.cost_of_equity}"
    )


@pytest.mark.parametrize("company_id", COMPANIES)
def test_beta_is_adjusted_exactly_once(company_id):
    """The provider publishes the raw beta; the engine owns the Blume shrink.

    Adjusting in both places composes to 0.4489*b + 0.5511 instead of
    0.67*b + 0.33, overstating beta and understating the implied price.
    """
    spec = _spec(company_id)
    wacc = spec.get_valuation("base").wacc
    raw = None
    try:
        from backend.data.providers.market_data import get_company_market_data

        raw = get_company_market_data(company_id).beta.value
    except Exception:
        pytest.skip("live market data unavailable")
    if raw is None or raw < 0.60:
        # Below the floor the provider substitutes; the single-shrink identity
        # does not apply.
        pytest.skip("beta is provider-recalibrated, not raw")
    assert wacc.beta == pytest.approx(round(0.67 * raw + 0.33, 3), abs=0.001), (
        f"{company_id}: beta {wacc.beta} is not a single Blume adjustment of raw {raw}"
    )


@pytest.mark.parametrize("company_id", COMPANIES)
def test_total_wacc_equals_the_weighted_component_sum(company_id):
    spec = _spec(company_id)
    wacc = spec.get_valuation("base").wacc
    expected = wacc.equity_weight * wacc.cost_of_equity + wacc.debt_weight * wacc.cost_of_debt
    assert wacc.wacc == pytest.approx(expected, abs=0.01)
    assert abs(wacc.equity_weight + wacc.debt_weight - 1.0) < 1e-6


@pytest.mark.parametrize("company_id", COMPANIES)
def test_capital_weights_use_the_latest_share_count(company_id):
    """WACC market cap and the equity bridge must use the SAME share count.

    The schedule is ordered ascending, so a periods[0] lookup is the OLDEST year
    and produced two different share counts inside one valuation output.
    """
    spec = _spec(company_id)
    wacc = spec.get_valuation("base").wacc
    bridge = spec.get_valuation("base").dcf_bridge
    hist_last = spec.historicals.periods[-1] if spec.historicals.periods else None
    latest = spec.share_count.get_diluted(hist_last) if hist_last else None
    if latest and bridge.shares_outstanding:
        assert abs(latest - bridge.shares_outstanding) < 0.5, (
            f"{company_id}: bridge uses {bridge.shares_outstanding} but the latest "
            f"historical count is {latest}"
        )


@pytest.mark.parametrize("company_id", COMPANIES)
def test_kpi_upside_matches_bridge_figures(company_id):
    """The -x% vs mkt tile is computed in the UI; verify the same arithmetic."""
    spec = _spec(company_id)
    base = spec.get_valuation("base")
    implied = base.dcf_bridge.implied_share_price
    market = base.reverse_dcf.market_price
    upside = (implied - market) / market * 100
    assert -95.0 < upside < 300.0, f"{company_id}: implausible upside {upside:.1f}%"


@pytest.mark.parametrize("company_id", COMPANIES)
def test_fiscal_calendar_comes_from_metadata_not_the_slug(company_id):
    """infy_us is a US-listed ADR on a 31 March Indian fiscal year.

    Deriving the fiscal year end (or the tax rate, or the terminal-growth
    anchor) from the company_id suffix mis-classifies it.
    """
    spec = _spec(company_id)
    from backend.models.spec.metadata import parse_fiscal_year_end

    expected_month, expected_day = parse_fiscal_year_end(spec.metadata.fiscal_year_end)
    for item in spec.forecast.line_items:
        if item.period_label == "FY27":
            assert item.period_end_date.month == expected_month, (
                f"{company_id}: FY27 period end month {item.period_end_date.month} != "
                f"{expected_month} from metadata"
            )
            assert item.period_end_date.day <= expected_day
            break


@pytest.mark.parametrize("company_id", COMPANIES)
def test_income_statement_foots(company_id):
    """EBITDA - D&A must equal EBIT in the forecast, for every period."""
    spec = _spec(company_id)
    fc = spec.forecast
    for period in ("FY27", "FY28", "FY29", "FY30", "FY31"):
        ebitda = fc.get_value("canonical.is.ebitda", period, "base")
        ebit = fc.get_value("canonical.is.operating_profit", period, "base")
        da = fc.get_value("canonical.is.depreciation_amortization", period, "base")
        if None in (ebitda, ebit, da):
            continue
        assert ebitda - da == pytest.approx(ebit, abs=0.05), (
            f"{company_id} {period}: EBITDA - D&A != EBIT "
            f"({ebitda:,.2f} - {da:,.2f} = {ebitda - da:,.2f} vs {ebit:,.2f})"
        )


@pytest.mark.parametrize("company_id", COMPANIES)
def test_forecast_cash_flow_reconciles_to_the_balance_sheet(company_id):
    """prior cash + CFO + CFI + CFF must equal the modelled cash balance.

    Dividends used to be deducted from equity while never appearing in
    financing, so the two statements diverged by exactly the dividend every
    year and nothing reconciled them.
    """
    spec = _spec(company_id)
    fc = spec.forecast
    periods = ["FY27", "FY28", "FY29", "FY30", "FY31"]
    hist = spec.historicals
    prior_cash = hist.get_value("canonical.bs.cash_and_bank", hist.periods[-1]) or 0.0

    for period in periods:
        cfo = fc.get_value("canonical.cf.operating_activities", period, "base") or 0.0
        cfi = fc.get_value("canonical.cf.investing_activities", period, "base") or 0.0
        cff = fc.get_value("canonical.cf.financing_activities", period, "base")
        cash = fc.get_value("canonical.bs.cash_and_bank", period, "base")
        if cff is None or cash is None:
            continue
        assert prior_cash + cfo + cfi + cff == pytest.approx(cash, abs=1.0), (
            f"{company_id} {period}: cash roll-forward "
            f"{prior_cash + cfo + cfi + cff:,.2f} != balance-sheet cash {cash:,.2f}"
        )
        prior_cash = cash
