from __future__ import annotations

"""
FastAPI Routes for Valence Engine.

Provides API endpoints for:
- GET /api/model/{company_id}: Fetch current ModelSpecification
- POST /api/model/recompute: Apply driver override, re-run engine, return updated spec
- POST /api/model/revert: Revert driver override back to model-generated state
- GET /api/export/excel: Trigger openpyxl exporter and download 27-tab .xlsx workbook
"""

import json
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
from backend.models.spec.model_specification import ModelSpecification
from backend.validation.pipeline import run_qa
from backend.valuation.pipeline import run_valuation

import re

router = APIRouter()

API_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = API_DIR.parent.parent

# In-memory session model cache for fast live recomputation
_MODEL_CACHE: Dict[str, ModelSpecification] = {}
_HIST_MODEL_CACHE: Dict[str, HistoricalModel] = {}
_UNIVERSE_SEEDED: bool = False


def _ensure_universe_seeded() -> None:
    """Seed the master universe once per process instead of per request."""
    global _UNIVERSE_SEEDED
    if not _UNIVERSE_SEEDED:
        from backend.data.universe.master_list import seed_master_universe
        seed_master_universe()
        _UNIVERSE_SEEDED = True


from backend.data.batch import ensure_company_ingested
from backend.data.universe.store import update_onboarding_status


def _get_hist_model(company_id: str = "infy_infy") -> HistoricalModel:
    """Return cached HistoricalModel for the given company_id."""
    global _HIST_MODEL_CACHE
    if company_id not in _HIST_MODEL_CACHE:
        ensure_company_ingested(company_id)
        _HIST_MODEL_CACHE[company_id] = run_historical(
            target_periods=["FY24", "FY25", "FY26"],
            company_id=company_id,
        )
    return _HIST_MODEL_CACHE[company_id]


def _get_or_build_spec(company_id: str = "infy_infy") -> ModelSpecification:
    if company_id not in _MODEL_CACHE:
        cache_path = PROJECT_ROOT / "backend" / "data" / "cache" / f"{company_id}.json"
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    raw_str = f.read()
                _MODEL_CACHE[company_id] = ModelSpecification.deserialize(raw_str)
                print(f"Loaded {company_id} ModelSpecification from precomputed cache.")
            except Exception as e:
                print(f"Failed to load cache for {company_id}, compiling live: {e}")
                ensure_company_ingested(company_id)
                hist_m = _get_hist_model(company_id)
                f_spec = run_forecast_pipeline(hist_m)
                v_spec = run_valuation(f_spec)
                _MODEL_CACHE[company_id] = run_qa(v_spec)
        else:
            print(f"No precomputed cache for {company_id}. Ingesting & compiling live...")
            ensure_company_ingested(company_id)
            hist_m = _get_hist_model(company_id)
            f_spec = run_forecast_pipeline(hist_m)
            v_spec = run_valuation(f_spec)
            q_spec = run_qa(v_spec)
            _MODEL_CACHE[company_id] = q_spec

            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(q_spec.serialize())
                print(f"Wrote compiled cache for {company_id}.")
            except Exception as e:
                print(f"Warning: could not write cache for {company_id}: {e}")

            try:
                update_onboarding_status(company_id, "onboarded", notes="On-demand live ingestion")
            except Exception:
                pass

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
    try:
        spec = _get_or_build_spec(company_id)
        return spec.model_dump(mode="json")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=422 if "No canonical" in str(e) or "unmapped" in str(e) else 500,
            detail=f"Could not build valuation model for '{company_id}': {str(e)}"
        )


@router.post("/model/recompute")
def recompute_model(req: OverrideRequest, company_id: str = "infy_infy") -> Dict[str, Any]:
    """Apply driver override, re-run forecast -> valuation -> QA engine, and return updated spec."""
    spec = _get_or_build_spec(company_id)

    # 1. Update assumption list with override
    new_assumptions = []
    found = False
    for a in spec.assumptions:
        if a.driver_key == req.driver_key and a.scenario == req.scenario and (a.period in (req.period, "all") or req.period == "all"):
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
    hist_m = _get_hist_model(company_id)
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
    return spec.model_dump(mode="json")


@router.post("/model/revert")
def revert_driver_override(req: RevertRequest, company_id: str = "infy_infy") -> Dict[str, Any]:
    """Revert driver override back to model-generated state and re-run engine."""
    spec = _get_or_build_spec(company_id)

    new_assumptions = []
    for a in spec.assumptions:
        if a.driver_key == req.driver_key and a.scenario == req.scenario and (a.period in (req.period, "all") or req.period == "all"):
            new_assumptions.append(a.reverted())
        else:
            new_assumptions.append(a)

    hist_m = _get_hist_model(company_id)
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
    return spec.model_dump(mode="json")


@router.get("/export/excel")
def export_excel(company_id: str = "infy_infy") -> FileResponse:
    """Trigger 27-tab openpyxl export and return .xlsx file download."""
    spec = _get_or_build_spec(company_id)
    out_dir = PROJECT_ROOT / "backend" / "export" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_ticker = re.sub(r'[^a-zA-Z0-9_-]', '', spec.metadata.ticker.lower())
    file_path = out_dir / f"{safe_ticker}_valuation_model.xlsx"

    export_model_to_excel(spec, file_path)

    if not file_path.exists():
        raise HTTPException(status_code=500, detail="Failed to generate Excel file")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/companies")
def list_available_companies() -> List[Dict[str, Any]]:
    """List all available onboarded companies across India and US markets."""
    from backend.data.universe.store import search_universe_companies
    from backend.models.spec.metadata import get_metadata_for_company

    _ensure_universe_seeded()
    onboarded = search_universe_companies(query="", status="onboarded", limit=1000)
    result = []
    for c in onboarded:
        meta = get_metadata_for_company(c.company_id)
        result.append({
            "company_id": c.company_id,
            "ticker": c.ticker,
            "name": c.name,
            "market": c.market,
            "exchange": c.exchange,
            "currency": meta.currency,
            "units": meta.units,
            "fiscal_year_end": meta.fiscal_year_end,
            "onboarding_status": c.onboarding_status,
        })
    return result


@router.get("/companies/search")
def search_companies(
    q: str = Query("", description="Ticker or company name query"),
    market: Optional[str] = Query(None, description="Filter by market ('india' or 'us')"),
    limit: int = Query(20, ge=1, le=100, description="Max search results"),
) -> List[Dict[str, Any]]:
    """Real-time autocomplete search across ticker and company name for universe companies."""
    from backend.data.universe.store import search_universe_companies
    from backend.models.spec.metadata import get_metadata_for_company

    _ensure_universe_seeded()
    m_filter = market if market in ("india", "us") else None
    matches = search_universe_companies(query=q, market=m_filter, limit=100)
    matches.sort(key=lambda c: (0 if c.onboarding_status in ("onboarded", "partial") else 1, c.ticker))
    results = matches[:limit]

    payload = []
    for c in results:
        meta = get_metadata_for_company(c.company_id)
        payload.append({
            "company_id": c.company_id,
            "ticker": c.ticker,
            "name": c.name,
            "market": c.market,
            "exchange": c.exchange,
            "sector": c.sector,
            "currency": meta.currency,
            "units": meta.units,
            "onboarding_status": c.onboarding_status,
        })
    return payload



# ------------------------------------------------------------------ #
# Persistence Endpoints
# ------------------------------------------------------------------ #

from fastapi import Depends
from backend.api.auth import UserSession, get_current_user
from backend.api.persistence import SavedModelHeader, SavedModelStore


class SaveModelRequest(BaseModel):
    name: Optional[str] = None
    model_id: Optional[str] = None
    company_id: str = "infy_infy"


@router.post("/models/save")
def save_user_model(
    req: SaveModelRequest,
    user: UserSession = Depends(get_current_user),
) -> Dict[str, Any]:
    """Save current ModelSpecification under authenticated user's profile."""
    spec = _get_or_build_spec(req.company_id)
    header = SavedModelStore.save(
        user_id=user.user_id,
        spec=spec,
        model_id=req.model_id,
        name=req.name,
    )
    return {"status": "saved", "header": header.dict()}


@router.get("/models")
def list_user_models(
    user: UserSession = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """List all saved models for authenticated user."""
    headers = SavedModelStore.list_for_user(user.user_id)
    return [h.dict() for h in headers]


@router.get("/models/{model_id}")
def load_user_model(
    model_id: str,
    user: UserSession = Depends(get_current_user),
) -> Dict[str, Any]:
    """Load a specific saved model for user into active workspace."""
    spec = SavedModelStore.load(user.user_id, model_id)
    if not spec:
        raise HTTPException(status_code=404, detail="Saved model not found")

    _MODEL_CACHE[spec.metadata.company_id] = spec
    return spec.model_dump(mode="json")


@router.delete("/models/{model_id}")
def delete_user_model(
    model_id: str,
    user: UserSession = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete a saved model for authenticated user."""
    ok = SavedModelStore.delete(user.user_id, model_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Model not found or already deleted")
    return {"status": "deleted", "model_id": model_id}

