from __future__ import annotations

"""
Top-level forecast pipeline: takes historical model + metadata and returns
a fully populated ModelSpecification with forecast, assumptions, and scenarios.
"""

from pathlib import Path

from backend.forecast.assumptions import suggest_base_assumptions
from backend.forecast.debt import build_debt_schedule
from backend.forecast.engine import run_forecast
from backend.forecast.scenarios import build_scenario_assumptions
from backend.forecast.share_count import build_share_count
from backend.models.spec.forecast import FORECAST_PERIODS
from backend.models.spec.metadata import INFOSYS_METADATA, ModelMetadata
from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import QAResults
from backend.models.spec.scenarios import V1_SCENARIOS
from backend.models.spec.valuation import ValuationOutput
from backend.models.statements.historical_model import HistoricalModel
from backend.models.statements.pipeline import run as run_historical
from backend.models.statements.ratios import compute_historical_ratios

HERE = Path(__file__).resolve().parent
WORKSPACE_ROOT = HERE.parent.parent
DB_PATH = WORKSPACE_ROOT / "backend" / "data" / "valence.db"


def run(
    historical_model: HistoricalModel | None = None,
    metadata: ModelMetadata = INFOSYS_METADATA,
) -> ModelSpecification:
    """Build a fully populated ModelSpecification including forecast for all scenarios."""
    if historical_model is None:
        historical_model = run_historical(target_periods=["FY24", "FY25", "FY26"])

    # Compute historical ratios used for assumption suggestions
    ratios = compute_historical_ratios(
        historical_model.income_statement,
        historical_model.balance_sheet,
        historical_model.cash_flow_statement,
    )

    # Build Base spec (historicals + schema scaffolding)
    spec = ModelSpecification.from_historical_model(historical_model, metadata)

    # Suggest Base assumptions
    base_assumptions = suggest_base_assumptions(ratios, historical_model)

    # Build Bull/Bear assumptions (complete parallel sets)
    bull_assumptions = build_scenario_assumptions(base_assumptions, "bull")
    bear_assumptions = build_scenario_assumptions(base_assumptions, "bear")

    all_assumptions = base_assumptions + bull_assumptions + bear_assumptions

    # Run forecast engine for each scenario
    base_forecast = run_forecast(base_assumptions, historical_model, "base")
    bull_forecast = run_forecast(bull_assumptions, historical_model, "bull")
    bear_forecast = run_forecast(bear_assumptions, historical_model, "bear")

    # Merge all forecast line items
    from backend.models.spec.forecast import Forecast
    merged_forecast = Forecast(
        line_items=base_forecast.line_items + bull_forecast.line_items + bear_forecast.line_items
    )

    # Scaffold valuation containers per scenario
    valuation_scaffolds = [ValuationOutput(scenario=s) for s in ["base", "bull", "bear"]]

    spec.forecast = merged_forecast
    spec.assumptions = all_assumptions
    spec.valuation = valuation_scaffolds
    spec.qa = QAResults.empty()

    # Build debt schedules for each scenario (zero-debt company computes correctly to zero)
    debt_schedules = [
        build_debt_schedule(
            opening_balance=0.0,
            interest_rate=0.0,
            draws_by_period={},
            scheduled_repayments_by_period={},
            optional_repayments_by_period={},
            periods=FORECAST_PERIODS,
            scenario=s,
        )
        for s in ["base", "bull", "bear"]
    ]
    spec.debt_schedule = debt_schedules

    # Build share count schedule (historical derived + forecast held flat)
    spec.share_count = build_share_count(historical_model, FORECAST_PERIODS)

    print(
        f"Forecast Pipeline Complete:\n"
        f"  - Assumptions generated : {len(all_assumptions)} "
        f"({len(base_assumptions)} base + {len(bull_assumptions)} bull + {len(bear_assumptions)} bear)\n"
        f"  - Forecast line items   : {len(merged_forecast.line_items)} "
        f"({len(base_forecast.line_items)} base x 3 scenarios)\n"
        f"  - Forecast periods      : {merged_forecast.periods}\n"
        f"  - Scenarios             : base, bull, bear\n"
        f"  - Debt schedules        : {len(debt_schedules)} scenarios (all zero-debt)\n"
        f"  - Share count periods   : {len(spec.share_count.periods)} (hist + forecast)"
    )

    return spec


if __name__ == "__main__":
    run()
