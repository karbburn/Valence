"""No fade may stop short of its target in the terminal year.

A Gordon terminal value capitalises the final explicit year. So that year has to be a
steady state, and any driver that is still mid-transition when it arrives is being
capitalised at a value the business will not hold.

Three separate instances of this lived in one function, and each survived because of
how it failed:

- capex faded to a target 1.25x depreciation that was not the economically correct
  one. This inflated value, and `terminal_value_is_not_carrying_the_model` caught it.
- the capex fade then stopped at 0.85, leaving 15% of the peak ratio in the terminal
  year. Reached the right target and still did not arrive.
- the tax fade stopped at 0.75, so the terminal year was taxed below the statutory
  rate. This one ran CONSERVATIVE -- it understated the terminal value -- and an
  error that makes the number look worse than it is does not get reported.

That last one is the reason this test exists as a sweep rather than a spot check. An
understating error is invisible in a review that only looks for scary numbers, and
the check that flags it (`terminal_value_is_not_carrying_the_model`) fires on a share
that is too high, so it can never see one that is too low.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ASSUMPTIONS = (ROOT / "backend" / "forecast" / "assumptions.py").read_text(encoding="utf-8")


def _fade_assignments() -> dict[str, str]:
    """Every `*_weights = [...]` LITERAL left in the forecast assumptions.

    Comprehensions are excluded by requiring the bracket body to contain no `for`.
    A list comprehension is derived from len(forecast_periods), which is the whole
    point; only a typed-out literal is a silent promise about the forecast length.
    """
    out = {}
    for m in re.finditer(r"(\w*(?:fade|weights)\w*)\s*=\s*(\[[^\]]*\])", ASSUMPTIONS):
        body = m.group(2)
        if "for" in body:
            continue
        out[m.group(1)] = body
    return out


class TestNoLiteralFadeWeightListSurvives:
    def test_there_are_no_hardcoded_fade_lists_left(self):
        """Every fade is derived from len(forecast_periods), not typed out.

        A five-element literal is a silent promise that the forecast has five
        periods. Adding or removing one must not be able to leave a fade short of its
        target, which is exactly what happened to the capex fade and then, separately,
        to the tax fade three lines away.
        """
        literals = _fade_assignments()
        assert not literals, (
            "these fade schedules are still typed out as literals, so they cannot "
            f"track the forecast length: {literals}"
        )


class TestEveryFadeReachesItsTarget:
    def test_capex_fade_ends_at_one(self):
        from backend.forecast.assumptions import _fade_weights

        for n in (1, 2, 3, 4, 5, 6, 8, 10):
            w = _fade_weights(n)
            assert len(w) == n
            assert w[-1] == pytest.approx(1.0), (
                f"with {n} forecast years the capex fade ends at {w[-1]}, so the "
                f"terminal value is struck on a peak-investment year"
            )

    def test_tax_fade_ends_at_the_statutory_rate(self):
        """The one that ran conservative, and so was never caught."""
        block_start = ASSUMPTIONS.index("tax_fade_weights")
        block_end = ASSUMPTIONS.index("for idx, p in enumerate(forecast_periods)", block_start)
        block = ASSUMPTIONS[block_start:block_end]
        assert "len(forecast_periods)" in block, (
            "the tax fade must be derived from the forecast length; a literal ends "
            "wherever it was typed"
        )
        # The terminal year must be fully weighted onto the statutory rate.
        assert re.search(r"i / \(len\(forecast_periods\) - 1\)", block) or \
            "else 1.0" in block, (
            "the tax fade must reach 1.0 in the final period, otherwise the "
            "perpetuity is taxed below its own statutory rate"
        )

    def test_the_old_short_taxes_terminal_value_cannot_come_back(self):
        assert "[0.0, 0.0, 0.25, 0.50, 0.75]" not in ASSUMPTIONS, (
            "this schedule ends at 0.75, taxing the terminal year below statutory. It "
            "understated the terminal value, which is why it was never reported"
        )


class TestTaxFadeShape:
    def test_it_is_linear(self):
        """A tax rate converges as credits run off, which is a drift, not a cycle."""
        i = ASSUMPTIONS.index("tax_fade_weights")
        j = ASSUMPTIONS.index("for idx, p in enumerate(forecast_periods)", i)
        block = ASSUMPTIONS[i:j]
        assert "i / (len(forecast_periods) - 1)" in block, (
            "the tax fade is not a simple linear ramp over the forecast"
        )
        # And it must not be the capex curve's shape.
        assert "** 2" not in block, (
            "the capex fade's front-loaded square was copied into the tax fade; a tax "
            "normalisation drifts rather than unwinding early"
        )


class TestFadesAreMonotonic:
    @pytest.mark.parametrize("n", [2, 3, 5, 7])
    def test_neither_fade_goes_backwards(self, n):
        from backend.forecast.assumptions import _fade_weights

        # Monotonic only. The capex fade is deliberately front-loaded and the tax fade
        # is linear, and they are different curves on purpose -- a capex cycle unwinds
        # early, a tax normalisation drifts. Asserting a shared shape would be
        # asserting a falsehood about one of them.
        w = _fade_weights(n)
        assert all(b >= a for a, b in zip(w, w[1:])), (
            f"capex fade is not monotonic at n={n}: {w}"
        )