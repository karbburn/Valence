from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel

ScenarioLabel = Literal["base", "bull", "bear", "custom"]

FORECAST_HORIZON_YEARS = 5
FORECAST_PERIODS = ["FY27", "FY28", "FY29", "FY30", "FY31"]


class ForecastLineItem(BaseModel):
    """Single forecast canonical value for one period in one scenario.

    Structurally identical shape to HistoricalLineItem — the engine produces
    the same canonical key / period / value contract regardless of whether
    the period is historical or forecast.
    """
    canonical_key: str
    period_label: str
    period_end_date: date
    value: float
    scenario: ScenarioLabel
    currency: str = "INR"
    units: str = "crores"
    driver_key: Optional[str] = None        # which driver produced this value


class Forecast(BaseModel):
    """Container for all forecast line items across all scenarios and periods.

    Populated by the forecasting engine.
    """
    horizon_years: int = FORECAST_HORIZON_YEARS
    periods: List[str] = FORECAST_PERIODS
    scenarios: List[ScenarioLabel] = ["base", "bull", "bear"]
    line_items: List[ForecastLineItem] = []

    def get(
        self, canonical_key: str, period: str, scenario: ScenarioLabel = "base"
    ) -> Optional[ForecastLineItem]:
        for item in self.line_items:
            if (
                item.canonical_key == canonical_key
                and item.period_label == period
                and item.scenario == scenario
            ):
                return item
        return None

    def get_value(
        self, canonical_key: str, period: str, scenario: ScenarioLabel = "base"
    ) -> Optional[float]:
        item = self.get(canonical_key, period, scenario)
        return item.value if item else None
