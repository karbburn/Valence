from __future__ import annotations

from pathlib import Path

from backend.data.store import query_canonical_datapoints, query_datapoints
from backend.models.statements.historical_model import HistoricalModel, build_historical_model

HERE = Path(__file__).resolve().parent
WORKSPACE_ROOT = HERE.parent.parent.parent
DB_PATH = WORKSPACE_ROOT / "backend" / "data" / "valence.db"
COMPANY_ID = "infy_infy"


def run(target_periods: list[str] | None = None, company_id: str = "infy_infy") -> HistoricalModel:
    """Run Historical Model Assembly for a target company."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}. Run taxonomy normalization pipeline first.")

    canonical_dps = query_canonical_datapoints(DB_PATH, company_id)
    if not canonical_dps:
        raise ValueError(f"No canonical datapoints found in database for company '{company_id}'.")

    raw_dps = query_datapoints(DB_PATH, company_id)

    model = build_historical_model(canonical_dps, target_periods=target_periods, raw_datapoints=raw_dps)

    print(
        f"Historical 3-Statement Model Assembled:\n"
        f"  - Company ID      : {model.company_id}\n"
        f"  - Historical Years: {model.periods}\n"
        f"  - IS Line Items   : {len(model.income_statement.line_items)}\n"
        f"  - BS Line Items   : {len(model.balance_sheet.line_items)}\n"
        f"  - CF Line Items   : {len(model.cash_flow_statement.line_items)}\n"
        f"  - Ratio Series    : {len(model.ratios.ratio_series)}"
    )

    return model


if __name__ == "__main__":
    run()
