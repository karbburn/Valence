from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

AssumptionType = Literal["model_generated", "user_override"]
ScenarioLabel = Literal["base", "bull", "bear", "custom"]


class AssumptionObject(BaseModel):
    """The central unit of the assumption layer.

    Design rules enforced here:
    - `previous_model_value` is populated at the moment of override, never destroyed.
    - Reverting an override restores the original model_generated value.
    - Each instance is immutable by default; overrides create a new instance via `with_override()`.
    """
    assumption_id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex)
    driver_key: str                          # e.g. "revenue_growth", "wacc.cost_of_equity"
    value: float
    period: str                              # e.g. "FY27", or "all" for period-invariant
    scenario: ScenarioLabel
    type: AssumptionType = "model_generated"
    source: str = ""                         # derivation method if model_gen; analyst note if override
    previous_model_value: Optional[float] = None   # set at override time; never cleared
    last_updated: datetime = Field(default_factory=datetime.now)

    def with_override(self, new_value: float, source: str = "Analyst") -> "AssumptionObject":
        """Return a new AssumptionObject reflecting a user override.

        The original model-generated value is preserved in previous_model_value.
        """
        prev = self.previous_model_value if self.type == "user_override" else self.value
        return AssumptionObject(
            assumption_id=self.assumption_id,   # same ID — same slot, new value
            driver_key=self.driver_key,
            value=new_value,
            period=self.period,
            scenario=self.scenario,
            type="user_override",
            source=source,
            previous_model_value=prev,
            last_updated=datetime.now(),
        )

    def reverted(self) -> "AssumptionObject":
        """Return this assumption reverted to model-generated state.

        Only callable on a user_override — if already model_generated, returns self.
        """
        if self.type == "model_generated" or self.previous_model_value is None:
            return self
        return AssumptionObject(
            assumption_id=self.assumption_id,
            driver_key=self.driver_key,
            value=self.previous_model_value,
            period=self.period,
            scenario=self.scenario,
            type="model_generated",
            source=f"Reverted from user override (was {self.value})",
            previous_model_value=None,
            last_updated=datetime.now(),
        )

    @property
    def is_overridden(self) -> bool:
        return self.type == "user_override"
