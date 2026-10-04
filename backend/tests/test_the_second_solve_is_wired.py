"""The reverse DCF's second solve is dead code, and it was broken while dead.

`compute_reverse_dcf` runs two solves. The first, the closed-form implied perpetuity
growth rate, always runs and is what every shipped model reports. The second, a bisection
for the revenue CAGR that would reproduce the market price, is guarded by

    if forecast and assumptions and historical_model is not None:

and nothing in the product ever supplies a `historical_model`. `run_valuation` takes one as
a keyword defaulting to None and no caller passes it, so the branch is unreachable. Measured
across all 23 shipped snapshots: `implied_revenue_cagr` is null in 69 of 69 valuation rows,
and a spy on the solver during a real `run_precompute` recorded zero calls.

That is worth knowing, and it is not what this file is for. This file is for the state the
dead branch was left in.

`compute_reverse_dcf` passed `mezzanine_equity_cr` to `_solve_implied_revenue_cagr`, whose
signature had no such parameter. Every other claims-aware call site in the project threads it
(`sensitivity.py` twice, `pipeline.py` into the bridge, and this module's own
`_price_at_growth`), and `claims.py` records that four enumerations of the claim list had
already drifted once each. This was the fifth, and it would have raised

    TypeError: _solve_implied_revenue_cagr() got an unexpected keyword argument

on the first build after anyone wired a historical model through. Nothing caught it because
the branch never runs, and the one test that calls `compute_reverse_dcf` passes no forecast,
no assumptions and no historical model, so it takes the other path.

So: assert the call happens, with the claim, when the inputs are present. That fails at HEAD
and passes once the parameter is threaded, and it keeps failing if the enumeration drifts
again.
"""
from __future__ import annotations

import inspect

import pytest


class _Stub:
    """Just enough of a forecast/assumption list to enter the branch.

    The solver is stubbed out, so nothing here has to be a real model. What is under test is
    the CALL, not the arithmetic: which keywords reach the second solve, and whether the
    call is even made.
    """

    def __bool__(self):
        return True

    def __iter__(self):
        return iter(())


def _fcff(label):
    from backend.valuation.dcf import FCFFPeriod

    return FCFFPeriod(period=label, fcff=100.0)


@pytest.fixture
def solver_spy(monkeypatch):
    """Record every call to the bisection solver, and return a value rather than solving."""
    from backend.valuation import reverse_dcf as module

    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return 4.2

    monkeypatch.setattr(module, "_solve_implied_revenue_cagr", fake)
    return calls


def _solve_through(solver_spy, **extra):
    from backend.valuation.reverse_dcf import compute_reverse_dcf

    result = compute_reverse_dcf(
        market_price=60.0,
        fcff_periods=[_fcff("FY26"), _fcff("FY27"), _fcff("FY28")],
        wacc_pct=8.0,
        cash_cr=500.0,
        debt_cr=2_000.0,
        shares_cr=100.0,
        marketable_securities_cr=100.0,
        forecast=_Stub(),
        assumptions=_Stub(),
        historical_model=_Stub(),
        **extra,
    )
    return result


def test_the_second_solve_receives_every_claim_ahead_of_common_equity(solver_spy):
    from backend.valuation.claims import CLAIMS_AHEAD_OF_COMMON_EQUITY

    _solve_through(
        solver_spy,
        minority_interest_cr=11.0,
        preferred_stock_cr=22.0,
        mezzanine_equity_cr=33.0,
    )

    assert len(solver_spy) == 1, (
        "the bisection solve was not called, so this file is asserting nothing about it. "
        "It is currently unreachable in production because no caller supplies a "
        "historical_model, which is a separate finding; a test that cannot enter the "
        "branch must say so rather than pass quietly."
    )
    passed = solver_spy[0]
    missing = [
        f"{c.bridge_field}_cr"
        for c in CLAIMS_AHEAD_OF_COMMON_EQUITY
        if f"{c.bridge_field}_cr" not in passed
    ]
    assert not missing, (
        f"the reverse solver omits {missing}. It solves for a growth rate that reproduces "
        f"the market price, so a claim it ignores is equity value it believes exists. The "
        f"rate it reports then implies MORE equity than the filer published, which is a "
        f"plausible-looking number in exactly the wrong direction."
    )


def test_mezzanine_reaches_the_solver_at_the_amount_it_was_given(solver_spy):
    _solve_through(solver_spy, mezzanine_equity_cr=48_056.0)
    assert solver_spy[0]["mezzanine_equity_cr"] == pytest.approx(48_056.0)


def test_the_solver_accepts_what_it_is_passed():
    """The signature has to match the call, or the branch raises the moment it is reached."""
    from backend.valuation.reverse_dcf import _solve_implied_revenue_cagr

    params = inspect.signature(_solve_implied_revenue_cagr).parameters
    for name in ("mezzanine_equity_cr", "minority_interest_cr", "preferred_stock_cr"):
        assert name in params, (
            f"_solve_implied_revenue_cagr has no {name}, and compute_reverse_dcf passes "
            f"one. The call cannot succeed."
        )


def test_the_branch_is_unreachable_in_production_and_that_is_known():
    """Records the dead branch as a FACT, so it cannot be forgotten silently.

    If this fails, someone has wired a historical model through. That is the intended
    change, and `implied_revenue_cagr` will start appearing on every model, which is a
    user-visible output change and needs its own review rather than arriving as a side
    effect of plumbing.
    """
    from backend.valuation.pipeline import run_valuation

    assert inspect.signature(run_valuation).parameters["historical_model"].default is None
    assert not _any_caller_supplies_historical_model(), (
        "a caller now passes historical_model to run_valuation, so the reverse DCF's "
        "bisection solve runs and implied_revenue_cagr appears on every model. Review "
        "that output before treating it as routine."
    )


def _any_caller_supplies_historical_model() -> bool:
    """Does anything in the PRODUCT pass historical_model into run_valuation?

    Tracked files only, and the exclusion list is not a guess. The first version walked the
    working tree and found two callers under `assets/`, which is gitignored: a video
    pipeline that builds its figures by driving the valuation directly. They are real code
    that really does call it, and they are not the product, so the test failed on a launch
    claim while the shipped path stayed unchanged.

    `git ls-files` is the authority on what ships. A walk of the filesystem treats a
    developer's scratch directory as production, which is the same class of error as reading
    a plausible number and believing it.
    """
    import ast
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    try:
        listing = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=root, capture_output=True, text=True, check=True, timeout=120,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git ls-files is unavailable, so the product was not scanned")

    for rel in listing:
        if rel.startswith("backend/tests/"):
            continue
        path = root / rel
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name != "run_valuation":
                continue
            if any(kw.arg == "historical_model" for kw in node.keywords):
                return True
    return False
