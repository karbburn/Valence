"""The capex fade must land somewhere that is actually a steady state.

A Gordon terminal value is a claim about a perpetuity. In a perpetuity growing at
g, reinvestment covers depreciation plus the capital for that growth, so capex
converges on D&A x (1 + g).

The fade used to target a flat 1.25x depreciation. That target is not a steady
state -- it says the business reinvests for ever at a rate its growth does not
fund -- and it is why the largest company in the shipped set failed
terminal_value_is_not_carrying_the_model with its terminal value carrying the whole
enterprise value and free cash flow near zero in every explicit year.

These assert the arithmetic of the target directly, so the constant cannot be
retuned back into a non-steady-state without turning the suite red.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from backend import constants

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "backend" / "forecast" / "assumptions.py").read_text(encoding="utf-8")


def _steady_state_block() -> str:
    start = SOURCE.index("term_growth, _growth_basis = constants.terminal_growth_for(")
    end = SOURCE.index("is_expansion_cycle =", start)
    return SOURCE[start:end]


class TestSteadyStateCapexIsARealSteadyState:
    def test_the_steady_state_overstates_reinvestment_rather_than_understating_it(self):
        """The premium must sit ABOVE the true economic ratio, not below it.

        This is the assertion that should have existed before the mistake was made.
        A review found the rule had been changed from 1.25 to `1 + g`, i.e. 1.022 --
        which is only correct for a one-year asset life. The correct form is
        `1 + g/delta` with delta the depreciation rate, which is 1.135-1.180 at US
        growth for a 6-8 year asset base.

        The error direction is the whole point. Understating steady-state capex
        raises free cash flow, raises the terminal value, and inflates the headline in
        exactly the direction nobody wants a credibility problem to move. So the test
        asserts the premium sits at or above the top of the economic range: overstating
        reinvestment understates value, and that is the cheap way to be wrong.
        """
        premium = constants.STEADY_STATE_CAPEX_PREMIUM
        assert premium > 1.0, (
            "a steady state at or below depreciation funds no growth at all"
        )
        # US only, and deliberately so. Every flagship filer in the shipped set is a
        # US filer and 1.25 clears their whole range (1.135-1.180 at a 6-8 year asset
        # life).
        #
        # It does NOT clear India's: at 4% growth and a 10 year asset life the
        # economic ratio is 1.40. So for a long-lived Indian asset base this constant
        # UNDERSTATES steady-state capex, which overstates the terminal value, and
        # that is stated here rather than tested away. One global constant cannot be
        # right in both markets, which is precisely why measuring delta is the open
        # item rather than something a test can settle.
        for life in (6, 8):
            true_ratio = 1.0 + (constants.US_TERMINAL_GROWTH / 100.0) * life
            assert premium >= true_ratio, (
                f"at US growth and a {life}-year asset life the economic steady state "
                f"is capex/D&A = {true_ratio:.3f}, but the model uses {premium:.3f}. "
                f"Understating it inflates free cash flow and the terminal value."
            )
        # Known, accepted limitation, recorded rather than tested away.
        #
        # 1.25 does not clear India's range: at 4% growth and an 8-10 year asset life
        # the economic ratio is 1.32-1.40, so for a long-lived Indian asset base this
        # constant UNDERSTATES steady-state capex and therefore overstates the
        # terminal value.
        #
        # One global constant cannot be right in both markets, and pretending
        # otherwise with a looser assertion would hide it. It happens to be harmless
        # today because every publishable company in the shipped set is a US filer;
        # it stops being harmless the moment an Indian filer with a long-lived asset
        # base is published. That is the concrete form of "measuring delta is the open
        # item".


    def test_growth_alone_is_not_the_rule(self):
        """`1 + g` must never come back.

        It reads as the obviously-correct answer -- reinvest to fund depreciation plus
        the growth -- and it is the wrong one, because the growth capital is `g x
        invested capital` while D&A is `delta x invested capital`. The ratio is
        `1 + g/delta`, and the two differ by a factor of 1/delta.
        """
        import re

        block = _steady_state_block()
        offenders = re.findall(r"premium\s*=\s*1\.0\s*\+\s*term_growth", block)
        assert not offenders, (
            "premium = 1 + g ignores the depreciation rate; use "
            "constants.STEADY_STATE_CAPEX_PREMIUM, which is anchored to 1 + g/delta"
        )

    def test_a_filer_already_inside_the_steady_state_is_not_faded(self):
        """Fading a business that is not in a cycle would invent a decline."""
        block = _steady_state_block()
        assert "if hist_capex_pct <= da_pct * premium:" in block, (
            "a filer whose capex is already at or below its steady state must be "
            "left alone, or the forecast invents a decline the filings do not show"
        )
        assert "steady_state_capex = hist_capex_pct" in block

    def test_the_target_is_the_steady_state_itself(self):
        """The fade lands on D&A x (1 + g) -- not near it, and not one clause of it.

        The compound form of this expression could not be checked: it contained a
        clamp that never bound, so a mutation to its inputs passed the suite.
        Stated as one multiplication, the rule is also the only thing a mutation can
        break.
        """
        block = _steady_state_block()
        assert "steady_state_capex = da_pct * premium" in block, (
            "the fade target must be the steady state itself"
        )

    def test_no_hardcoded_depreciation_multiple_survives(self):
        """A literal multiple of D&A is how the defect got in. Refuse new ones."""
        block = _steady_state_block()
        offenders = re.findall(r"da_pct\s*\*\s*([0-9]+\.[0-9]+)", block)
        assert not offenders, (
            "the steady-state capex target must be derived from the terminal growth "
            f"rate, not from a literal multiple of depreciation; found {offenders}"
        )

    @pytest.mark.parametrize("growth", [0.0, 2.25, 4.0])
    def test_a_five_year_fade_reaches_the_steady_state(self, growth):
        """The weights must actually land on the target, not stop short of it."""
        premium = constants.STEADY_STATE_CAPEX_PREMIUM
        hist, da = 13.5, 8.6
        target = min(max(da * (1 + growth / 100.0),
                         min(hist, constants.MAX_STEADY_STATE_CAPEX_PCT)),
                     da * premium)
        from backend.forecast.assumptions import _fade_weights

        weights = _fade_weights(5)
        final = (1 - weights[-1]) * hist + weights[-1] * target
        assert final / da <= premium + 1e-9, (
            f"after the fade, capex is {final / da:.3f}x depreciation, above the "
            f"{premium:.3f}x the growth rate funds"
        )


    @pytest.mark.parametrize("n", [1, 2, 3, 5, 7])
    def test_the_fade_always_reaches_the_target_in_the_last_year(self, n):
        """Whatever the forecast horizon, the terminal year is the steady state.

        Read from the function rather than a copy of its output, so extending the
        forecast cannot quietly leave the fade short of the terminal year again --
        which is exactly what happened when the weights were five hardcoded
        literals ending at 0.85.
        """
        from backend.forecast.assumptions import _fade_weights

        w = _fade_weights(n)
        assert len(w) == n
        if n > 1:
            assert w[0] == 0.0, (
                "the fade starts at the filer's own historical ratio"
            )
        # n == 1 has one year, and that year is the terminal year, so it is already
        # the steady state. Starting it at the historical peak would capitalise the
        # peak for ever.
        assert w[-1] == pytest.approx(1.0), (
            f"with {n} forecast years the fade ends at {w[-1]}, so the Gordon "
            f"terminal value is struck on a year that is not the steady state"
        )
        assert all(b >= a for a, b in zip(w, w[1:])), "the fade must be monotonic"


class TestTheFadeActuallyReachesTheSteadyState:
    """Behavioural. The tests above pin the source text; these run the code.

    Pinning text is a weak instrument here and it showed: three mutations passed
    the suite because the shape assertions still matched while the arithmetic was
    wrong. A test that only reads the file cannot tell a rule from a copy of it.

    So this drives `suggest_base_assumptions` with a filer in a capex cycle and
    checks the published ratios.
    """

    @staticmethod
    def _model(revenues, capex, da):
        from backend.models.statements.balance_sheet import BalanceSheet
        from backend.models.statements.cash_flow import (
            CashFlowStatement,
            CashFlowLineItem,
        )
        from backend.models.statements.historical_model import HistoricalModel
        from backend.models.statements.income_statement import (
            IncomeStatement,
            IncomeStatementLineItem,
        )
        from backend.models.statements.ratios import HistoricalRatios, RatioSeries

        cid = "cycle_us"
        periods = [f"FY{20 + i}" for i in range(len(revenues))]
        return HistoricalModel(
            company_id=cid,
            periods=periods,
            income_statement=IncomeStatement(
                company_id=cid,
                periods=periods,
                line_items=[
                    IncomeStatementLineItem(
                        canonical_key="canonical.is.revenue",
                        display_label="Revenue",
                        values_by_period=dict(zip(periods, revenues)),
                    ),
                    IncomeStatementLineItem(
                        canonical_key="canonical.is.depreciation_amortization",
                        display_label="D&A",
                        values_by_period=dict(zip(periods, da)),
                    ),
                ],
            ),
            balance_sheet=BalanceSheet(company_id=cid, periods=periods, line_items=[]),
            # Capex is read off the CASH FLOW statement. Putting it on the income
            # statement made it invisible and the function silently fell back to the
            # 2.5% platform default -- which is exactly how a test can pass against a
            # rule it never exercised.
            cash_flow_statement=CashFlowStatement(
                company_id=cid,
                periods=periods,
                line_items=[
                    CashFlowLineItem(
                        canonical_key="canonical.cf.capex",
                        display_label="Capex",
                        category="investing",
                        values_by_period=dict(zip(periods, capex)),
                    )
                ],
            ),
            # D&A as a share of revenue is read off the RATIOS series, not recomputed
            # from the income statement, so it has to be supplied there.
            ratios=HistoricalRatios(
                company_id=cid,
                periods=periods,
                ratio_series=[
                    RatioSeries(
                        metric_key="da_pct_revenue",
                        display_label="D&A % of revenue",
                        unit="%",
                        formula_reference="depreciation_amortization / revenue",
                        # Already a percentage. Passing the absolute depreciation
                        # figure instead would make the steady-state target 1,000x
                        # too large, the clamp would never bind, and the test would
                        # assert against a number no filer produces.
                        values_by_period={
                            p: round(abs(v) / r * 100.0, 6)
                            for p, v, r in zip(periods, da, revenues)
                        },
                    )
                ],
            ),
        )

    def _published_capex_ratios(self):
        from backend.forecast.assumptions import suggest_base_assumptions
        from backend.models.spec.forecast import FORECAST_PERIODS

        # A filer in a genuine capex cycle: capex 18% of revenue against D&A at 9%.
        model = self._model(
            revenues=[574_785.0, 637_959.0, 716_924.0],
            capex=[103_461.0, 114_833.0, 131_819.0],
            da=[48_663.0, 52_795.0, 65_756.0],
        )
        out = suggest_base_assumptions(model.ratios, model)
        return [a.value for a in out if a.driver_key == "capex_pct_revenue"]

    def test_a_cyclic_filer_publishes_a_capex_ratio_that_converges(self):
        ratios = self._published_capex_ratios()
        assert len(ratios) == 5, f"expected one ratio per forecast year, got {ratios}"
        assert ratios[0] > ratios[-1], (
            "a filer in a capex cycle must see its ratio fade, or the terminal value "
            "is struck on the peak"
        )
        # D&A averaged ~8.6% of revenue here. The steady state funds
        # STEADY_STATE_CAPEX_PREMIUM times depreciation.
        da_pct = (
            48_663 / 574_785 + 52_795 / 637_959 + 65_756 / 716_924
        ) / 3 * 100
        allowed = da_pct * constants.STEADY_STATE_CAPEX_PREMIUM
        # The published ratio is rounded to four decimals by the assumption
        # builder, so the tolerance is a rounding step and not a judgement call.
        assert ratios[-1] <= allowed + 1e-3, (
            f"the terminal year publishes capex at {ratios[-1]:.3f}% of revenue, "
            f"which is {ratios[-1] / da_pct:.3f}x depreciation against a growth rate "
            f"funding {allowed / da_pct:.3f}x. The Gordon terminal value capitalises "
            f"this year, so it must BE the steady state"
        )

    def test_a_cyclic_filer_reaches_it_exactly_in_the_last_year(self):
        ratios = self._published_capex_ratios()
        da_pct = (48_663 / 574_785 + 52_795 / 637_959 + 65_756 / 716_924) / 3 * 100
        target = da_pct * constants.STEADY_STATE_CAPEX_PREMIUM
        assert ratios[-1] == pytest.approx(target, abs=0.05), (
            "the fade must land on the steady state, not merely close to it"
        )
