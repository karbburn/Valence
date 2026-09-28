from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel

from backend.data.pipeline import DB_PATH
from backend.data.precompute import run_precompute
from backend.data.errors import NoFinancialsAvailable
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


def ensure_company_ingested(
    company_id: str,
    db_path: str | Path = DB_PATH,
    force: bool = False,
) -> None:
    """Ensure raw datapoints are parsed and normalized into SQLite store for company_id.

    `force=True` re-runs the source maps even when canonical data already exists.
    It is required after any change to an ingestion map, a source label, or the
    taxonomy registry: the skip-on-present shortcut meant a corrected mapping
    never reached the database, so the stored rows kept whatever provenance
    the ORIGINAL parse assigned them.
    """
    from backend.data.ingestion.screener import parse_screener_export
    from backend.data.ingestion.sec_edgar import parse_sec_edgar_export
    from backend.data.store import query_canonical_datapoints, save_datapoints
    from backend.normalization.pipeline import run as run_norm

    existing = query_canonical_datapoints(db_path, company_id=company_id)
    if len(existing) > 0 and not force:
        return

    if company_id.endswith("_us"):
        # Fall through the providers on the typed "there is nothing there" error
        # only, not on any exception.
        #
        # A catch-all here means a KeyError from a statement shape the parser did
        # not expect is treated as an outage: the chain walks to the end, finds no
        # export, and reports that no financials are available. The user is told
        # to retry, the company is negatively cached, and the bug is never seen.
        # That is strictly worse than the fault this change set out to fix, and it
        # only became possible once the outcome was given its own type.
        try:
            from backend.data.ingestion.sec_edgar import fetch_and_parse_sec_edgar
            dps = fetch_and_parse_sec_edgar(company_id=company_id)
        except NoFinancialsAvailable as e:
            logger.info("SEC EDGAR has no statements for %s, trying yfinance live: %s", company_id, e)
            try:
                from backend.data.ingestion.us_live import fetch_and_parse_us_live
                dps = fetch_and_parse_us_live(company_id=company_id)
            except NoFinancialsAvailable as e2:
                logger.info("yfinance live has no statements for %s, falling back to local source file fixture: %s", company_id, e2)
                # The local export is the last resort, and it has to stay one.
                # A transient outage at both live providers is exactly the case it
                # exists for, and several companies ship one. Replacing the call
                # here with a raise made those unavailable during an outage, which
                # is the opposite of what a fallback is for.
                #
                # What was actually wrong was only the type escaping: a
                # FileNotFoundError raised from inside an exception handler
                # reached the API as a 500, on a condition the user experiences as
                # "not yet" rather than "broken". A 500 now has to mean the build
                # broke, so the absence of an export is reported as the ordinary
                # outcome it is, with the reason kept for the log.
                #
                # Both markets had this fault, not just this one. The Indian
                # branch guarded its source-file lookup with a handler but left the
                # live fetch unguarded, so a provider that returned nothing raised
                # a plain ValueError straight to the API.
                try:
                    src_file = _source_file_for(company_id)
                except FileNotFoundError as e3:
                    # Chained from the provider failure rather than the missing
                    # file, so the reason the live fetch did not work is still the
                    # one in the traceback. Chaining from the missing file made a
                    # real ingestion fault look like an absent export.
                    raise NoFinancialsAvailable(
                        f"No financial statements could be sourced for {company_id} "
                        f"(SEC EDGAR and yfinance both returned nothing, and there is "
                        f"no local export)"
                    ) from e2
                dps = parse_sec_edgar_export(src_file, company_id=company_id)
        save_datapoints(db_path, dps, clear_existing=True)
        run_norm(company_id=company_id)
    else:
        try:
            _source_file_for(company_id)
            from backend.data.pipeline import run as run_india_pipeline
            # On a forced re-ingest the previous rows must go: a label that is no
            # longer emitted would otherwise linger alongside the corrected ones
            # and the selector could still pick it.
            run_india_pipeline(company_id=company_id, db_path=db_path, clear_db=force)
            run_norm(company_id=company_id)
        except FileNotFoundError:
            logger.info("Local source file for %s not found, attempting live Indian equity ingestion", company_id)
            from backend.data.ingestion.india_live import fetch_and_parse_india_live
            # Nothing is caught here. The ingestion module raises the typed error
            # when the exchange genuinely has nothing, and a KeyError from a shape
            # it did not expect is a real fault that has to stay visible: wrapping
            # this in a bare except answered a bug as "not available yet", told
            # the user to retry, and then negatively cached the ticker so the
            # failure could not be found from the outside.
            dps = fetch_and_parse_india_live(company_id=company_id)
            save_datapoints(db_path, dps, clear_existing=True)
            run_norm(company_id=company_id)

    _supplement_missing_lines(company_id, db_path)


# Lines a summary export routinely omits but the forecast cannot invent for
# itself: without them the working-capital and payout drivers are unresolvable,
# and the model has no honest option but to mark them unknown.
SUPPLEMENTABLE_METRICS = frozenset({
    "Trade payables",
    "Inventory",
    "Dividend Amount",
    "Short term borrowings",
    "Finance lease liabilities",
    "Operating lease liabilities",
    "Minority interest",
})


def _supplement_missing_lines(company_id: str, db_path: str | Path = DB_PATH) -> int:
    """Fill canonical lines the primary source omits, from the live provider.

    A curated summary export carries revenue, profit and a handful of balances,
    but not accounts payable, inventory, dividends, short-term debt or minority
    interest. Those lines are exactly the ones the forecast needs to build
    working capital and the payout ratio, and without them the drivers resolve
    to nothing.

    The rows are MERGED, not substituted: the selector ranks the primary source
    above the market feed, so a value the filing already provides is never
    replaced. Only keys the primary source does not have at all are added.
    """
    from backend.data.store import query_datapoints, save_datapoints
    from backend.normalization.pipeline import run as run_norm

    try:
        existing = query_datapoints(db_path, company_id)
    except Exception:
        return 0
    present = {d.metric_raw for d in existing}
    missing = SUPPLEMENTABLE_METRICS - present
    if not missing:
        return 0

    # A supplement fills gaps. It may never INTRODUCE a period: a live feed
    # dated differently from the filing (a September year end against a
    # December one) would otherwise add a trailing period holding a handful of
    # balance-sheet lines, and the model would treat that stub as the most
    # recent actual and roll the whole forecast forward from it.
    known_periods = {d.period_label for d in existing}

    try:
        if company_id.endswith("_us"):
            from backend.data.ingestion.us_live import fetch_and_parse_us_live

            extra = fetch_and_parse_us_live(company_id=company_id)
        else:
            from backend.data.ingestion.india_live import fetch_and_parse_india_live

            extra = fetch_and_parse_india_live(company_id=company_id)
    except Exception as exc:
        logger.info("Line supplementation for %s unavailable: %s", company_id, exc)
        return 0

    # Keep only labels that are actually missing, only periods the primary
    # source already has, and only that source's own rows, so a partial fetch
    # can neither overwrite a filed figure nor invent a period.
    extra = [
        d
        for d in extra
        if d.metric_raw in missing
        and d.period_label in known_periods
        and d.source != "local_export"
    ]
    if not extra:
        return 0

    save_datapoints(db_path, extra, clear_existing=False)
    run_norm(company_id=company_id)
    logger.info(
        "Supplemented %s with %d live row(s) for %s",
        company_id,
        len(extra),
        ", ".join(sorted(missing)),
    )
    return len(extra)


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
