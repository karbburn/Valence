from __future__ import annotations

"""
FastAPI Routes for Valence Engine.

Provides API endpoints for:
- GET /api/model/{company_id}: Fetch current ModelSpecification
- POST /api/model/recompute: Apply driver override, re-run engine, return updated spec
- POST /api/model/revert: Revert driver override back to model-generated state
- GET /api/export/excel: Trigger openpyxl exporter and download 27-tab .xlsx workbook
"""

import logging
import re
from collections import OrderedDict
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

logger = logging.getLogger("valence.api")

API_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = API_DIR.parent.parent


# ------------------------------------------------------------------ #
# Historical window / override period defaults.
# NOTE: these are hardcoded for now; they should be derived from the
# ingested financial data in the future.
# ------------------------------------------------------------------ #
DEFAULT_HIST_PERIODS = ["FY24", "FY25", "FY26"]
DEFAULT_OVERRIDE_PERIOD = "FY27"


@router.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}

# Bounded in-memory session model cache for fast live recomputation
# (simple LRU via OrderedDict to avoid unbounded memory growth).
MAX_CACHE_SIZE = 50


def _lru_get(cache: OrderedDict, key: str) -> Any:
    """Return cached value for key, marking it most-recently-used."""
    if key not in cache:
        return None
    cache.move_to_end(key)
    return cache[key]


def _lru_put(cache: OrderedDict, key: str, value: Any) -> None:
    """Store value under key, evicting the oldest entry when over capacity."""
    if key in cache:
        cache.move_to_end(key)
    cache[key] = value
    while len(cache) > MAX_CACHE_SIZE:
        cache.popitem(last=False)


_MODEL_CACHE: "OrderedDict[str, ModelSpecification]" = OrderedDict()
_HIST_MODEL_CACHE: "OrderedDict[str, HistoricalModel]" = OrderedDict()
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
        _lru_put(
            _HIST_MODEL_CACHE,
            company_id,
            run_historical(
                target_periods=DEFAULT_HIST_PERIODS,
                company_id=company_id,
            ),
        )
    return _lru_get(_HIST_MODEL_CACHE, company_id)


def _get_or_build_spec(company_id: str = "infy_infy") -> ModelSpecification:
    if company_id not in _MODEL_CACHE:
        cache_path = PROJECT_ROOT / "backend" / "data" / "cache" / f"{company_id}.json"
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    raw_str = f.read()
                spec = ModelSpecification.deserialize(raw_str)
                logger.info("Loaded %s ModelSpecification from precomputed cache.", company_id)
                # The cache holds a build-time SNAPSHOT of market data (price, shares,
                # beta, risk-free rate, ERP). Re-run valuation against live providers so
                # the served model reflects current market prices. The forecast itself
                # is reused from the cache, so this is a light valuation recompute, not
                # a full rebuild. If the live fetch fails (e.g. provider/network down),
                # fall back to the snapshot rather than triggering a heavy on-demand
                # ingestion that could OOM the free tier.
                try:
                    spec = run_valuation(spec)
                    spec = run_qa(spec)
                    logger.info("Refreshed live market data for %s.", company_id)
                except Exception as refresh_err:
                    logger.warning(
                        "Market-data refresh failed for %s; serving cached snapshot: %s",
                        company_id,
                        refresh_err,
                    )
                _lru_put(_MODEL_CACHE, company_id, spec)
            except Exception as e:
                logger.warning("Failed to load cache for %s, compiling live: %s", company_id, e)
                ensure_company_ingested(company_id)
                hist_m = _get_hist_model(company_id)
                f_spec = run_forecast_pipeline(hist_m)
                v_spec = run_valuation(f_spec)
                _lru_put(_MODEL_CACHE, company_id, run_qa(v_spec))
        else:
            logger.info("No precomputed cache for %s. Ingesting & compiling live...", company_id)
            ensure_company_ingested(company_id)
            hist_m = _get_hist_model(company_id)
            f_spec = run_forecast_pipeline(hist_m)
            v_spec = run_valuation(f_spec)
            q_spec = run_qa(v_spec)
            _lru_put(_MODEL_CACHE, company_id, q_spec)

            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(q_spec.serialize())
                logger.info("Wrote compiled cache for %s.", company_id)
            except Exception as e:
                logger.warning("Warning: could not write cache for %s: %s", company_id, e)

            try:
                update_onboarding_status(company_id, "onboarded", notes="On-demand live ingestion")
            except Exception:
                pass

    return _lru_get(_MODEL_CACHE, company_id)


class OverrideRequest(BaseModel):
    driver_key: str
    value: float
    period: str = DEFAULT_OVERRIDE_PERIOD
    scenario: str = "base"


class RevertRequest(BaseModel):
    driver_key: str
    period: str = DEFAULT_OVERRIDE_PERIOD
    scenario: str = "base"


@router.get("/model/{company_id}")
def get_model_spec(company_id: str = "infy_infy") -> Dict[str, Any]:
    """Fetch complete ModelSpecification JSON for company."""
    try:
        spec = _get_or_build_spec(company_id)
        return spec.model_dump(mode="json")
    except Exception as e:
        logger.exception("Failed to build valuation model for '%s'", company_id)
        status_code = 422 if "No canonical" in str(e) or "unmapped" in str(e) else 500
        raise HTTPException(
            status_code=status_code,
            detail="Failed to build model. See server logs for details.",
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

    _lru_put(_MODEL_CACHE, company_id, spec)
    return spec.model_dump(mode="json")


@router.post("/model/revert")
def revert_driver_override(req: RevertRequest, company_id: str = "infy_infy") -> Dict[str, Any]:
    """Revert driver override back to model-generated state and re-run engine.
    
    Supports bulk revert if driver_key is 'all'.
    """
    spec = _get_or_build_spec(company_id)

    new_assumptions = []
    for a in spec.assumptions:
        is_match = (req.driver_key == "all" or a.driver_key == req.driver_key)
        if is_match and a.scenario == req.scenario and (a.period in (req.period, "all") or req.period == "all"):
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

    _lru_put(_MODEL_CACHE, company_id, spec)
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
    results = search_universe_companies(query=q, market=m_filter, limit=limit)

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
# NOTE: Model persistence moved to browser localStorage (frontend). The
# previous server-side /api/models/* endpoints backed by per-user file
# storage were removed along with auth. No backend persistence exists.

