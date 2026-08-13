from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel

from backend.data.pipeline import DB_PATH
from backend.data.precompute import run_precompute
from backend.data.universe.store import update_onboarding_status, get_universe_company

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


def ensure_company_ingested(company_id: str, db_path: str | Path = DB_PATH) -> None:
    """Ensure raw datapoints are parsed and normalized into SQLite store for company_id."""
    from backend.data.ingestion.screener import parse_screener_export
    from backend.data.ingestion.sec_edgar import parse_sec_edgar_export
    from backend.data.store import query_canonical_datapoints, save_datapoints
    from backend.normalization.pipeline import run as run_norm

    existing = query_canonical_datapoints(db_path, company_id=company_id)
    if len(existing) > 0:
        return

    company_files = {
        "infy_infy": "Infosys.xlsx",
        "tcs_tcs": "tcs_tcs.xlsx",
        "tatamotors_tatamotors": "tatamotors_tatamotors.xlsx",
        "tatasteel_tatasteel": "tatasteel_tatasteel.xlsx",
        "aapl_us": "aapl_us.xlsx",
        "msft_us": "msft_us.xlsx",
        "infy_us": "infy_us.xlsx",
    }

    if company_id not in company_files:
        return

    file_name = company_files[company_id]
    src_file = SOURCES_DIR / file_name
    if not src_file.exists():
        return

    if company_id.endswith("_us"):
        dps = parse_sec_edgar_export(src_file, company_id=company_id)
    else:
        dps = parse_screener_export(src_file, company_id=company_id)

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

    ensure_company_ingested(company_id=company_id, db_path=db_path)

    for attempt in range(1, max_retries + 1):
        try:
            # Respect rate constraints between attempts
            if attempt > 1:
                time.sleep(2 ** attempt * 0.1)

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
            if attempt == max_retries:
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
