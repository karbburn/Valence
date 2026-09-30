"""A valuation must be a number that could exist.

Three shipped companies were publishing a NEGATIVE implied share price. Ambarella
at -62.40 against a market price of 68.73, Idea Cellular at -3.95, Tata Steel at
-4.38. A negative equity value is not a contrarian view. It is arithmetic that
cannot happen, and no amount of assumption-setting makes it a research opinion.

The cause is visible in the cash flows. Ambarella's forecast carries EBIT of -108
rising to -151 across the five explicit years, so unlevered free cash flow is
negative throughout, and a Gordon terminal value on a negative final-year FCFF
comes out negative too. That negative terminal value is then discounted and added
to five negative explicit years, giving an enterprise value of -2,972 and an equity
value of -2,659.

Discounting a perpetuity of negative cash flows is not a conservative estimate; it
is a formula being applied outside the domain where it means anything. The
existing checks all pass this model: terminal_growth_lt_wacc passes because 2.25%
is indeed below the 13.03% WACC, and dcf_bridge_reconciles passes because the
negative figures add up correctly. Both are true statements about their own
subject and neither can notice that the subject has no meaning.

This is deliberately narrower than a check about disagreeing with the market. A DCF
that lands below the market price is a view, and publishing one is the product
working. What cannot be published is arithmetic that has left the domain of
possible answers.
"""

from __future__ import annotations

from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import ModelCheckResult


def check_valuation_is_meaningful(spec: ModelSpecification) -> ModelCheckResult:
    """Refuse an enterprise or equity value that could not exist."""
    scenarios = spec.valuation or []
    if not scenarios:
        return ModelCheckResult(
            check_name="valuation_is_meaningful",
            category="data_quality",
            passed=False,
            detail=(
                "This model carries no valuation scenarios, so there is nothing to "
                "check. Failing rather than passing, because a check that verified "
                "nothing and reported success would be believed."
            ),
            implicated_scenarios=["base", "bull", "bear"],
        )

    broken: list[str] = []
    worst = None
    for scenario in scenarios:
        bridge = getattr(scenario, "dcf_bridge", None)
        if bridge is None:
            broken.append(f"{scenario.scenario}: no dcf_bridge")
            continue
        ev = getattr(bridge, "enterprise_value", None)
        equity = getattr(bridge, "equity_value", None)
        price = getattr(bridge, "implied_share_price", None)
        final_fcff = None
        terminal = getattr(scenario, "terminal_value", None)
        if terminal is not None:
            final_fcff = getattr(terminal, "final_year_fcff", None)

        if final_fcff is not None and final_fcff < 0:
            broken.append(
                f"{scenario.scenario}: terminal value built on a NEGATIVE final-year "
                f"free cash flow of {final_fcff:,.0f}. Discounting a perpetuity of "
                f"cash outflows is not an estimate, it is the formula applied "
                f"outside the domain where it means anything."
            )
        if ev is not None and ev <= 0:
            broken.append(
                f"{scenario.scenario}: enterprise value {ev:,.0f} is not positive. "
                f"An enterprise cannot be worth less than nothing unless its "
                f"liabilities exceed its assets outright."
            )
        if equity is not None and equity <= 0:
            broken.append(
                f"{scenario.scenario}: equity value {equity:,.0f} is not positive, so "
                f"the implied share price is not a value."
            )
        if price is not None and price <= 0:
            broken.append(
                f"{scenario.scenario}: implied share price {price:,.2f} is not "
                f"positive. This is the figure the page publishes."
            )
        if worst is None or (price is not None and price < worst[1]):
            worst = (getattr(scenario, "scenario", "?"), price)

    if not broken:
        return ModelCheckResult(
            check_name="valuation_is_meaningful",
            category="data_quality",
            passed=True,
            detail=(
                f"Every scenario has a positive enterprise value, equity value and "
                f"implied share price (lowest {worst[1]:,.2f} on {worst[0]})."
                if worst and worst[1] is not None else
                "Every scenario carries a positive enterprise and equity value."
            ),
        )

    return ModelCheckResult(
        check_name="valuation_is_meaningful",
        category="data_quality",
        passed=False,
        detail=(
            "This model produces values that cannot exist, so it is not a view "
            "anyone can hold. "
            + " ".join(broken)
            + " The checks that would normally object all pass it: terminal growth "
            "is below WACC, and the bridge reconciles, because the negative figures "
            "add up correctly. A DCF landing below the market price is a legitimate "
            "result and this check does not object to that; what it refuses is an "
            "answer outside the range of possible ones. Either the forecast has to "
            "produce positive free cash flow, or this company cannot be valued by "
            "this method and must not carry a published price."
        ),
        implicated_canonical_keys=["equity_value", "enterprise_value", "implied_share_price"],
        implicated_periods=["terminal"],
        implicated_scenarios=sorted({b.split(":")[0] for b in broken}),
    )
