from __future__ import annotations

"""
FastAPI Routes for Valence Engine.

Provides API endpoints for:
- GET /api/model/{company_id}: Fetch current ModelSpecification
- POST /api/model/recompute: Apply driver override, re-run engine, return updated spec
- POST /api/model/revert: Revert driver override back to model-generated state
- GET /api/export/excel: Trigger openpyxl exporter and download 27-tab .xlsx workbook
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.export.excel.exporter import export_model_to_excel
from backend.forecast.engine import run_forecast
from backend.forecast.pipeline import run as run_forecast_pipeline
from backend.models.spec.forecast import Forecast
from backend.models.statements.historical_model import HistoricalModel
from backend.models.statements.pipeline import run as run_historical
from backend.validation.pipeline import run_qa
from backend.valuation.pipeline import run_valuation

router = APIRouter()

# In-memory session model cache for fast live recomputation
_MODEL_CACHE: Dict[str, ModelSpecification] = {}
_HIST_MODEL_CACHE: Optional[HistoricalModel] = None


def _get_hist_model() -> HistoricalModel:
    global _HIST_MODEL_CACHE
    if _HIST_MODEL_CACHE is None:
        _HIST_MODEL_CACHE = run_historical(target_periods=["FY24", "FY25", "FY26"])
    return _HIST_MODEL_CACHE


def _get_or_build_spec(company_id: str = "infy_infy") -> ModelSpecification:
    if company_id not in _MODEL_CACHE:
        hist_m = _get_hist_model()
        f_spec = run_forecast_pipeline(hist_m)
        v_spec = run_valuation(f_spec)
        q_spec = run_qa(v_spec)
        _MODEL_CACHE[company_id] = q_spec
    return _MODEL_CACHE[company_id]


class OverrideRequest(BaseModel):
    driver_key: str
    value: float
    period: str = "FY27"
    scenario: str = "base"


class RevertRequest(BaseModel):
    driver_key: str
    period: str = "FY27"
    scenario: str = "base"


@router.get("/model/{company_id}")
def get_model_spec(company_id: str = "infy_infy") -> Dict[str, Any]:
    """Fetch complete ModelSpecification JSON for company."""
    spec = _get_or_build_spec(company_id)
    return spec.serialize()


@router.post("/model/recompute")
def recompute_model(req: OverrideRequest, company_id: str = "infy_infy") -> Dict[str, Any]:
    """Apply driver override, re-run forecast -> valuation -> QA engine, and return updated spec."""
    spec = _get_or_build_spec(company_id)

    # 1. Update assumption list with override
    new_assumptions = []
    found = False
    for a in spec.assumptions:
        if a.driver_key == req.driver_key and a.scenario == req.scenario and (a.period == req.period or a.period == "all" or req.period == "all"):
            new_assumptions.append(a.with_override(req.value))
            found = True
        else:
            new_assumptions.append(a)

    if not found:
        # Create new override assumption object if not present
        from backend.models.spec.assumptions import AssumptionObject
        new_ass = AssumptionObject(
            driver_key=req.driver_key,
            value=req.value,
            period=req.period,
            scenario=req.scenario,  # type: ignore
            type="user_override",
            source="Analyst Override",
        )
        new_assumptions.append(new_ass)

    # 2. Re-run forecast engine for all scenarios
    hist_m = _get_hist_model()
    scenarios = ["base", "bull", "bear"]
    merged_items = []
    for s in scenarios:
        s_assumptions = [a for a in new_assumptions if a.scenario == s]
        f_out = run_forecast(s_assumptions, hist_m, s)
        merged_items.extend(f_out.line_items)

    spec.assumptions = new_assumptions
    spec.forecast = Forecast(line_items=merged_items)

    # 3. Re-run valuation engine
    spec = run_valuation(spec)

    # 4. Re-run QA validation engine
    spec = run_qa(spec)

    _MODEL_CACHE[company_id] = spec
    return spec.serialize()


@router.post("/model/revert")
def revert_driver_override(req: RevertRequest, company_id: str = "infy_infy") -> Dict[str, Any]:
    """Revert driver override back to model-generated state and re-run engine."""
    spec = _get_or_build_spec(company_id)

    new_assumptions = []
    for a in spec.assumptions:
        if a.driver_key == req.driver_key and a.scenario == req.scenario and (a.period == req.period or a.period == "all" or req.period == "all"):
            new_assumptions.append(a.reverted())
        else:
            new_assumptions.append(a)

    hist_m = _get_hist_model()
    scenarios = ["base", "bull", "bear"]
    merged_items = []
    for s in scenarios:
        s_assumptions = [a for a in new_assumptions if a.scenario == s]
        f_out = run_forecast(s_assumptions, hist_m, s)
        merged_items.extend(f_out.line_items)

    spec.assumptions = new_assumptions
    spec.forecast = Forecast(line_items=merged_items)
    spec = run_valuation(spec)
    spec = run_qa(spec)

    _MODEL_CACHE[company_id] = spec
    return spec.serialize()


@router.get("/export/excel")
def export_excel(company_id: str = "infy_infy") -> FileResponse:
    """Trigger 27-tab openpyxl export and return .xlsx file download."""
    spec = _get_or_build_spec(company_id)
    out_dir = Path("backend/export/output")
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"{spec.metadata.ticker.lower()}_valuation_model.xlsx"

    export_model_to_excel(spec, file_path)

    if not file_path.exists():
        raise HTTPException(status_code=500, detail="Failed to generate Excel file")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
