from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel

ScenarioLabel = Literal["base", "bull", "bear", "custom"]

FORECAST_HORIZON_YEARS = 5


def forecast_periods_after(last_historical: str) -> List[str]:
    """The five fiscal years following a company's last reported one.

    Derived, because the forecast horizon belongs to the company and not to the
    calendar. It was a fixed list, `FY27` through `FY31`, and seven of the twenty-three
    companies served carry their last actual as FY25: Apple, Amazon, Avery, Dover,
    Alphabet, Infosys US, Meta and TSMC all jumped straight from FY25 to FY27 and
    never modelled FY26 at all. Their first forecast year then compounded off a
    base two years old, and the growth driver faded from a year the model does not
    contain.

    The default below is kept as the value used when nothing is known about the
    company's last reported period, which is the situation a hand-built spec is in.
    """
    if not last_historical or not last_historical.startswith("FY"):
        return [f"FY{n}" for n in range(27, 27 + FORECAST_HORIZON_YEARS)]
    digits = last_historical[2:]
    if not digits.isdigit():
        return [f"FY{n}" for n in range(27, 27 + FORECAST_HORIZON_YEARS)]
    first = int(digits)
    # Labels stay two-digit, because that is the convention every statement, the
    # workbook and the driver panel already use. "FY2027" and "FY27" would be two
    # names for one period and the forecast would silently stop matching the
    # historicals it grows out of.
    return [
        f"FY{(first + offset) % 100:02d}"
        for offset in range(1, FORECAST_HORIZON_YEARS + 1)
    ]


FORECAST_PERIODS = forecast_periods_after("FY26")


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
