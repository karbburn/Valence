from __future__ import annotations

"""
Scenario wiring: builds Bull/Bear/Custom assumption sets as complete parallel copies,
not multipliers on Base. Per 04_assumption_architecture.md §4.
"""

import copy
from typing import List

from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.forecast import FORECAST_PERIODS


# Bull/Bear deltas per driver (additive to base value, per period).
# These are complete overrides — not multipliers.
_BULL_DELTAS: dict[str, float] = {
    "revenue_growth": +2.0,   # pp
    "ebitda_margin":  +1.0,   # pp
    "ebit_margin":    +0.8,   # pp
    "dso_days":       -5.0,   # days (lower = better)
}

_BEAR_DELTAS: dict[str, float] = {
    "revenue_growth": -2.0,
    "ebitda_margin":  -1.0,
    "ebit_margin":    -0.8,
    "dso_days":       +5.0,
}


def build_scenario_assumptions(
    base_assumptions: List[AssumptionObject],
    scenario: str,
) -> List[AssumptionObject]:
    """Build a complete parallel assumption set for Bull, Bear, or Custom.

    Starts as a deep copy of Base, then applies per-driver deltas.
    Custom scenario is returned as an unmodified copy of Base (user edits via UI).
    """
    if scenario not in ("bull", "bear", "custom"):
        raise ValueError(f"Unknown scenario '{scenario}'")

    deltas = _BULL_DELTAS if scenario == "bull" else (_BEAR_DELTAS if scenario == "bear" else {})

    result: List[AssumptionObject] = []
    for a in base_assumptions:
        if a.scenario != "base":
            continue
        new_value = a.value + deltas.get(a.driver_key, 0.0)
        result.append(
            AssumptionObject(
                driver_key=a.driver_key,
                value=new_value,
                period=a.period,
                scenario=scenario,
                type="model_generated",
                source=a.source + (f" [{scenario} delta: {deltas.get(a.driver_key, 0):+g}]" if a.driver_key in deltas else ""),
                previous_model_value=None,
            )
        )
    return result
