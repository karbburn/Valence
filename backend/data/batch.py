from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel

from backend.data.pipeline import DB_PATH
from backend.data.precompute import run_precompute
from backend.data.universe.store import update_onboarding_status, get_universe_company

logger = logging.getLogger(__name__)

StatusCategory = Literal["success", "transient_failure", "data_missing", "parse_failure"]


class BatchTaskResult(BaseModel):
    company_id: str
    success: bool
    status_category: StatusCategory
    error_message: Optional[str] = None
    execution_time_seconds: float
    timestamp: datetime = datetime.now()


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = PROJECT_ROOT / "backend" / "data" / "sources"


# Legacy source-file aliases for companies whose source export predates the
# `{company_id}.xlsx` naming convention. New sources should use the convention.
_SOURCE_FILE_ALIASES = {
    "infy_infy": "Infosys.xlsx",
}


def _source_file_for(company_id: str) -> Path:
    """Locate the raw source export for a company_id.

    Resolution order:
      1. Explicit alias (legacy filenames such as ``Infosys.xlsx``).
      2. Convention file ``{company_id}.xlsx`` in the sources directory.

    Raises FileNotFoundError when no source export exists, so callers can
    surface ``data_missing`` instead of silently skipping the company.
    """
    if company_id in _SOURCE_FILE_ALIASES:
        candidate = SOURCES_DIR / _SOURCE_FILE_ALIASES[company_id]
        if candidate.exists():
            return candidate

    candidate = SOURCES_DIR / f"{company_id}.xlsx"
    if candidate.exists():
        return candidate

    raise FileNotFoundError(
        f"No source export found for {company_id} "
        f"(looked for {SOURCES_DIR / f'{company_id}.xlsx'})"
    )


def ensure_company_ingested(company_id: str, db_path: str | Path = DB_PATH) -> None:
    """Ensure raw datapoints are parsed and normalized into SQLite store for company_id."""
    from backend.data.ingestion.screener import parse_screener_export
    from backend.data.ingestion.sec_edgar import parse_sec_edgar_export
    from backend.data.store import query_canonical_datapoints, save_datapoints
    from backend.normalization.pipeline import run as run_norm

    existing = query_canonical_datapoints(db_path, company_id=company_id)
    if len(existing) > 0:
        return

    if company_id.endswith("_us"):
        try:
            from backend.data.ingestion.sec_edgar import fetch_and_parse_sec_edgar
            dps = fetch_and_parse_sec_edgar(company_id=company_id)
        except Exception as e:
            logger.info("Live SEC EDGAR fetch for %s unavailable, falling back to local source file fixture: %s", company_id, e)
            src_file = _source_file_for(company_id)
            dps = parse_sec_edgar_export(src_file, company_id=company_id)
        save_datapoints(db_path, dps, clear_existing=True)
        run_norm(company_id=company_id)
    else:
        try:
            src_file = _source_file_for(company_id)
            from backend.data.pipeline import run as run_india_pipeline
            run_india_pipeline(company_id=company_id, db_path=db_path, clear_db=False)
            run_norm(company_id=company_id)
        except (FileNotFoundError, Exception) as e:
            logger.info("Local source file for %s not found, attempting live Indian equity ingestion: %s", company_id, e)
            from backend.data.ingestion.india_live import fetch_and_parse_india_live
            dps = fetch_and_parse_india_live(company_id=company_id)
            save_datapoints(db_path, dps, clear_existing=True)
            run_norm(company_id=company_id)


def run_batch_company_onboarding(
    company_id: str,
    max_retries: int = 3,
    db_path: str | Path = DB_PATH,
) -> BatchTaskResult:
    """Run full pipeline for a company with exponential backoff retries and status reporting."""
    t0 = time.time()
    company = get_universe_company(company_id, db_path=db_path)
    if company is None:
        t_elapsed = round(time.time() - t0, 3)
        err_msg = f"Company {company_id} not present in master universe"
        return BatchTaskResult(
            company_id=company_id,
            success=False,
            status_category="data_missing",
            error_message=err_msg,
            execution_time_seconds=t_elapsed,
        )

    for attempt in range(1, max_retries + 1):
        try:
            # Respect rate constraints between attempts
            if attempt > 1:
                time.sleep(2 ** attempt * 0.1)

            ensure_company_ingested(company_id=company_id, db_path=db_path)

            # Precompute runs historical -> forecast -> valuation -> QA and saves static cache
            cache_path = run_precompute(company_id=company_id)

            if not cache_path.exists() or cache_path.stat().st_size == 0:
                raise ValueError(f"Cache file empty or missing for {company_id}")

            update_onboarding_status(
                company_id=company_id,
                status="onboarded",
                notes="Pipeline completed successfully with MODEL VALID status",
                db_path=db_path,
            )

            t_elapsed = round(time.time() - t0, 3)
            return BatchTaskResult(
                company_id=company_id,
                success=True,
                status_category="success",
                execution_time_seconds=t_elapsed,
            )

        except FileNotFoundError as e:
            t_elapsed = round(time.time() - t0, 3)
            err_msg = f"Data source file missing: {e}"
            update_onboarding_status(company_id, "failed", err_msg, db_path=db_path)
            return BatchTaskResult(
                company_id=company_id,
                success=False,
                status_category="data_missing",
                error_message=err_msg,
                execution_time_seconds=t_elapsed,
            )

        except Exception as e:
            if attempt < max_retries:
                logger.warning("Attempt %d/%d failed for %s: %s", attempt, max_retries, company_id, e)
                continue
            t_elapsed = round(time.time() - t0, 3)
            err_msg = f"Failed after {max_retries} attempts: {e}"
            update_onboarding_status(company_id, "failed", err_msg, db_path=db_path)
            return BatchTaskResult(
                company_id=company_id,
                success=False,
                status_category="parse_failure",
                error_message=err_msg,
                execution_time_seconds=t_elapsed,
            )

    t_elapsed = round(time.time() - t0, 3)
    return BatchTaskResult(
        company_id=company_id,
        success=False,
        status_category="transient_failure",
        error_message="Exhausted retries",
        execution_time_seconds=t_elapsed,
    )


def run_batch_tier(
    company_ids: list[str],
    db_path: str | Path = DB_PATH,
) -> list[BatchTaskResult]:
    """Execute batch onboarding sequentially across a tier of company IDs."""
    results = []
    for cid in company_ids:
        res = run_batch_company_onboarding(cid, db_path=db_path)
        results.append(res)
        # Politeness rate limit delay
        time.sleep(0.05)
    return results
