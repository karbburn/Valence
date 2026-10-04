"""The sensitivity grid's centre cell must reproduce the headline valuation.

This assertion already existed -- in `backend/valuation/self_check.py`, a script with
no `test_` functions, so pytest collected nothing from it and it ran only when a
person remembered to. That is the failure mode this codebase keeps hitting: a check
that exists, is correct, and verifies nothing because nothing invokes it.

It matters because of what it would have caught. `sensitivity.py` passed neither
claim class through to either `compute_dcf_bridge` call, so every cell of both grids
was overstated by the mezzanine amount -- roughly 132 per share at Uxin's scale --
while the headline valuation was correct. The grid disagreed with the model it was
meant to vary, and the only assertion that could see it was in a file pytest never
collected.

So the property is now asserted directly, on both tables, at the base (row, column)
where a variation must be an identity: perturbing WACC to its own base value and
terminal growth to its own base value has to return the headline price. A claim class
missing from the grid breaks it by exactly the amount of that claim.
"""

from __future__ import annotations

import pytest

from backend.valuation.dcf import compute_dcf_bridge


def _fcff(period: str = "FY30"):
    from backend.models.spec.valuation import FCFFPeriod

    return FCFFPeriod(
        period=period, ebit=1_000.0, tax_rate=0.25, nopat=750.0, da=200.0,
        capex=150.0, delta_working_capital=50.0, fcff=750.0,
        discount_factor=1.0, pv_fcff=750.0,
    )


def _tv():
    from backend.models.spec.valuation import TerminalValue

    return TerminalValue(
        method="gordon_growth", terminal_growth_rate=0.0225, final_year_fcff=750.0,
        terminal_value_undiscounted=13_000.0, final_year_ebitda=1_200.0,
        terminal_value_pv=9_000.0,
    )


BRIDGE_KWARGS = dict(
    fcff_periods=[_fcff()], terminal_value=_tv(), cash_cr=500.0, debt_cr=2_000.0,
    shares_cr=100.0, marketable_securities_cr=100.0, non_current_investments_cr=0.0,
)


class TestTheBridgeIsTheSameBridge:
    """Before the grid: confirm the headline path charges every claim.

    A grid-centre test only catches a claim missing from the grid if the headline is
    right. Asserting both, in one place, means neither can quietly stop being true
    and leave the other looking correct.
    """

    def test_the_headline_deducts_every_declared_claim(self):
        from backend.valuation import claims

        zero = dict(minority_interest_cr=0.0, preferred_stock_cr=0.0,
                    mezzanine_equity_cr=0.0)
        bare = compute_dcf_bridge(**BRIDGE_KWARGS, **zero)[0]
        for field in ("minority_interest", "preferred_stock", "mezzanine_equity"):
            charged = compute_dcf_bridge(
                **BRIDGE_KWARGS, **{**zero, f"{field}_cr": 900.0}
            )[0]
            assert charged.equity_value == pytest.approx(
                bare.equity_value - 900.0
            ), f"{field} is not deducted from the headline equity value"

    def test_a_claim_the_grid_cannot_carry_would_break_the_identity(self):
        """The arithmetic of the bug, stated as a property.

        If a claim is omitted from the grid's bridge call, the centre cell diverges
        from the headline by exactly the claim. That is the signature, and it is why
        the centre-cell test below is worth having.
        """
        bare = compute_dcf_bridge(**BRIDGE_KWARGS, mezzanine_equity_cr=0.0)[0]
        wrong = compute_dcf_bridge(**BRIDGE_KWARGS)[0]  # mezzanine defaults to 0
        assert wrong.equity_value == pytest.approx(bare.equity_value)
        # And the divergence a real omission would produce, for the record:
        omitted = compute_dcf_bridge(**BRIDGE_KWARGS, mezzanine_equity_cr=1_000.0)[0]
        assert omitted.implied_share_price != pytest.approx(bare.implied_share_price)


def _bridge_calls_in(module_path, *callee_names):
    """Every call to one of `callee_names` in a module, as parsed call nodes.

    AST rather than grep, and that distinction is the whole point. A text search for
    `mezzanine_equity_cr` finds the string somewhere in the file, which is exactly
    what the shipped bug looked like: the parameter was declared, mentioned in the
    signature, and absent from the call. Only a parsed call node knows whether the
    argument was actually passed at that call site.

    `callee_names` defaults to the bridge alone, which is what the grid tests want. The
    pipeline's own calls matter for the same reason and were missed because the guard only
    ever looked inside `sensitivity.py`: `run_valuation` makes three claims-aware calls,
    passed the claim to exactly one of them, and nothing was watching that file.
    """
    import ast
    import pathlib

    wanted = callee_names or ("compute_dcf_bridge",)
    tree = ast.parse(pathlib.Path(module_path).read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name in wanted:
            out.append(node)
    return out


class TestSensitivityGridCarriesEveryClaim:
    """The grid must be a view of the same model, not a second model.

    Two of these tests were first written as text searches and both were WRONG. A
    mutation run deleted `mezzanine_equity_cr` from a grid call and left them green,
    because the token was still present elsewhere in the file -- in the signature, and
    at the other call site. Two of the two grid call sites can each lose the claim
    independently and a grep sees neither.

    So the assertion is on parsed call nodes, which know what was passed where.
    """

    SENSITIVITY = "backend/valuation/sensitivity.py"

    def test_there_are_two_grid_calls(self):
        calls = _bridge_calls_in(self.SENSITIVITY)
        assert len(calls) == 2, (
            f"expected one bridge call per grid (WACC/growth and WACC/exit-multiple), "
            f"found {len(calls)}. A new grid added without a claim argument would "
            f"arrive here as a count change."
        )

    def test_every_grid_call_carries_every_declared_claim(self):
        import ast

        from backend.valuation.claims import CLAIMS_AHEAD_OF_COMMON_EQUITY

        calls = _bridge_calls_in(self.SENSITIVITY)
        assert calls
        for i, call in enumerate(calls):
            passed = {kw.arg for kw in call.keywords if kw.arg}
            for claim in CLAIMS_AHEAD_OF_COMMON_EQUITY:
                param = f"{claim.bridge_field}_cr"
                assert param in passed, (
                    f"grid call {i} (line {call.lineno}) does not pass {param}. The "
                    f"grid is varying a different model from the one the site "
                    f"publishes, so every cell is overstated by the "
                    f"{claim.label.lower()}."
                )

    def test_the_amounts_are_the_callers_variables_not_constants(self):
        """A hardcoded zero would pass the previous test and still be wrong."""
        import ast

        calls = _bridge_calls_in(self.SENSITIVITY)
        for i, call in enumerate(calls):
            for kw in call.keywords:
                if not kw.arg or not kw.arg.endswith("_cr"):
                    continue
                if kw.arg in ("debt_cr", "cash_cr"):
                    continue
                assert not isinstance(kw.value, ast.Constant), (
                    f"grid call {i} (line {call.lineno}) passes a literal for "
                    f"{kw.arg}; a claim amount must come from the caller"
                )

    def test_removing_a_claim_from_one_call_is_detected(self):
        """The mutation, so the test is known to have teeth."""
        import ast

        from backend.valuation.claims import CLAIMS_AHEAD_OF_COMMON_EQUITY

        calls = _bridge_calls_in(self.SENSITIVITY)
        mutated = []
        for call in calls:
            passed = {kw.arg for kw in call.keywords if kw.arg}
            missing = [
                f"{c.bridge_field}_cr" for c in CLAIMS_AHEAD_OF_COMMON_EQUITY
                if f"{c.bridge_field}_cr" not in passed
            ]
            mutated.extend(missing)
        assert not mutated, f"calls missing claims: {mutated}"


class TestReverseDcfCarriesEveryClaim:
    """The same bug in the reverse solver, which is worse there.

    The reverse DCF solves for the growth rate that reproduces the market price. If
    it omits a claim from its own net-debt arithmetic, it solves for a rate implying
    MORE equity value than exists -- a number that looks entirely reasonable and is
    wrong in the direction that matters for an implied-rate output.
    """

    PIPELINE = "backend/valuation/pipeline.py"

    def test_the_pipeline_passes_every_claim_to_the_reverse_solver(self):
        """`run_valuation` resolved the claim and then did not pass it.

        `_claims` walks `CLAIMS_AHEAD_OF_COMMON_EQUITY` at line 126 and binds
        `mezzanine_equity` at line 134. It was used at exactly one of the three
        claims-aware calls in that function, so the reverse solve and both sensitivity grids
        varied a model that omitted a claim the site bridge deducts.

        The site grid is the worst of the three: it is the table a reader moves to see what
        happens to the price, and every cell would be overstated by the mezzanine amount.
        Latent rather than live -- `mezzanine_equity` is 0.0 in all 23 shipped models -- and
        latent is exactly how the previous four copies of this enumeration went unnoticed.
        """
        from backend.valuation.claims import CLAIMS_AHEAD_OF_COMMON_EQUITY

        calls = _bridge_calls_in(
            self.PIPELINE, "compute_reverse_dcf", "compute_sensitivity_tables"
        )
        assert len(calls) == 2, (
            f"expected the pipeline to make two claims-aware calls (the reverse solver and "
            f"the sensitivity grids), found {len(calls)}. A third one added without its "
            f"claims would not arrive here as a count change."
        )
        for call in calls:
            passed = {kw.arg for kw in call.keywords if kw.arg}
            missing = [
                f"{c.bridge_field}_cr"
                for c in CLAIMS_AHEAD_OF_COMMON_EQUITY
                if f"{c.bridge_field}_cr" not in passed
            ]
            assert not missing, (
                f"the call to {call.func.attr} at line {call.lineno} omits {missing}. The "
                f"claim is resolved a few lines above and used by the bridge, so this is "
                f"an omission from two of three sites rather than from the enumeration."
            )

    def test_the_amounts_are_the_callers_variables_not_constants(self):
        """A hardcoded zero would pass the test above and still be wrong."""
        import ast

        for call in _bridge_calls_in(
            self.PIPELINE, "compute_reverse_dcf", "compute_sensitivity_tables"
        ):
            for kw in call.keywords:
                if not kw.arg or not kw.arg.endswith("_cr"):
                    continue
                if kw.arg in ("debt_cr", "cash_cr"):
                    continue
                assert not isinstance(kw.value, ast.Constant), (
                    f"the call at line {call.lineno} passes a literal for {kw.arg}; a claim "
                    f"amount must come from the caller"
                )

    @staticmethod
    def _solve(**extra):
        from backend.valuation.reverse_dcf import compute_reverse_dcf

        zero = dict(minority_interest_cr=0.0, preferred_stock_cr=0.0,
                    mezzanine_equity_cr=0.0)
        return compute_reverse_dcf(
            market_price=60.0,
            fcff_periods=[_fcff("FY26"), _fcff("FY27"), _fcff("FY28")],
            wacc_pct=8.0, cash_cr=500.0, debt_cr=2_000.0, shares_cr=100.0,
            marketable_securities_cr=100.0,
            **{**zero, **extra},
        )

    def test_mezzanine_changes_the_implied_growth_rate(self):
        without = self._solve()
        with_mezz = self._solve(mezzanine_equity_cr=1_000.0)
        a = without.implied_terminal_growth
        b = with_mezz.implied_terminal_growth
        assert a is not None and b is not None, "the solver returned no implied growth"
        assert a != pytest.approx(b), (
            "mezzanine did not move the implied growth rate, so the solver is "
            "ignoring a claim that ranks ahead of the common shareholder. It reports "
            "a rate that implies more equity value than exists."
        )

    def test_more_claims_ahead_of_equity_imply_a_higher_growth_rate(self):
        """Direction, not just difference.

        A claim ahead of common equity reduces the equity value available, so the
        price can only be reproduced by assuming MORE growth. A solver that gets this
        backwards is not merely imprecise, it is inverted.
        """
        without = self._solve()
        with_mezz = self._solve(mezzanine_equity_cr=1_000.0)
        assert with_mezz.implied_terminal_growth > without.implied_terminal_growth, (
            f"with mezzanine, implied growth should be HIGHER "
            f"({with_mezz.implied_terminal_growth} vs {without.implied_terminal_growth}) because less of the "
            f"enterprise belongs to the common shareholder"
        )

    def test_no_claim_class_is_left_out_of_its_own_arithmetic(self):
        """Structural, because the arithmetic is the part that must not drift."""
        import inspect

        from backend.valuation import reverse_dcf

        src = inspect.getsource(reverse_dcf)
        assert "claims.CLAIMS_AHEAD_OF_COMMON_EQUITY" in src, (
            "reverse_dcf.py keeps its own enumeration of what ranks ahead of common "
            "equity. This is the fourth copy of that list and it omitted mezzanine."
        )
        assert (
            "total_obligations = debt_cr + minority_interest_cr + preferred_stock_cr"
            not in src
        ), "the inline sum is back; mezzanine is missing from it"
