from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ScenarioType = Literal["base", "bull", "bear", "custom"]


class ScenarioDefinition(BaseModel):
    """A complete, independent set of assumptions — not a multiplier on Base.

    Switching scenarios swaps the entire assumption set the Forecast Engine reads,
    not a global scalar adjustment. Custom scenarios are user-created copies of
    another scenario, edited driver-by-driver.
    """
    scenario_id: str                        # e.g. "base", "bull", "bear", or user slug
    type: ScenarioType
    display_name: str                       # e.g. "Base Case", "Bull Case"
    based_on: Optional[str] = None          # for custom: which scenario_id was copied from
    assumption_ids: List[str] = Field(default_factory=list)  # IDs of AssumptionObjects in this scenario
    description: str = ""


# V1 built-in scenario set — Base/Bull/Bear always present.
# Custom scenarios are created at runtime by the web renderer per user action.
V1_SCENARIOS: List[ScenarioDefinition] = [
    ScenarioDefinition(
        scenario_id="base",
        type="base",
        display_name="Base Case",
        description="Model-generated central assumptions.",
    ),
    ScenarioDefinition(
        scenario_id="bull",
        type="bull",
        display_name="Bull Case",
        description="Optimistic assumptions — higher growth, expanding margins.",
    ),
    ScenarioDefinition(
        scenario_id="bear",
        type="bear",
        display_name="Bear Case",
        description="Conservative assumptions — slower growth, margin compression.",
    ),
]
