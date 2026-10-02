from __future__ import annotations

"""
FastAPI Routes for Valence Engine.

Provides API endpoints for:
- GET /api/model/{company_id}: Fetch current ModelSpecification
- POST /api/model/recompute: Apply driver override, re-run engine, return updated spec
- POST /api/model/revert: Revert driver override back to model-generated state
- GET /api/export/excel: Trigger openpyxl exporter and download 31-tab .xlsx workbook
"""

import logging
import re
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from backend.data.snapshot_io import read_model_snapshot, write_model_snapshot
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from backend.api import throttle as ingest_throttle
from backend.data.providers.market_data import (
    REGISTRY_FALLBACKS,
    last_completed_session,
)
from backend.export.excel.exporter import export_model_to_excel
from backend.forecast.engine import run_forecast
from backend.forecast.pipeline import run as run_forecast_pipeline
from backend.models.spec.forecast import Forecast
from backend.models.statements.historical_model import HistoricalModel
from backend.models.statements.pipeline import run as run_historical
from backend.models.spec.model_specification import ModelSpecification
from backend.validation.pipeline import run_qa
from backend.valuation.pipeline import run_valuation

router = APIRouter()

logger = logging.getLogger("valence.api")

API_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = API_DIR.parent.parent

# Company identifiers are slug-shaped ("infy_infy", "aapl_us"). Enforcing the shape at
# every entry point keeps untrusted input away from cache paths, DB lookups, and the
# ingestion triggers.
COMPANY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{1,62}[a-z0-9]$")


def _require_valid_company_id(company_id: str) -> str:
    if not COMPANY_ID_PATTERN.match(company_id):
        raise HTTPException(status_code=400, detail="Invalid company identifier.")
    return company_id


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

# Serializes recompute/revert read-modify-write cycles. Without this, rapid
# sequential edits race: each request reads the pre-override spec and appends
# a duplicate user_override, which can never be reverted (previous=None).
_SPEC_MUTEX = threading.Lock()

# Serializes workbook exports, and bounds how long a request will wait for one.
#
# Two reasons this exists, and the second is the one that took the service down.
#
# 1. CORRECTNESS. The formula-value registry the exporter uses to embed cached
#    results in the .xlsx is a module-level dict keyed by (sheet, row, col), and
#    every export clears it on entry. Two exports in flight therefore share
#    their keys: one wipes the other's values mid-write, and each can write the
#    other's numbers into its own cells. A downloaded workbook can then disagree
#    with the model it was generated from.
#
# 2. CAPACITY. An export holds a model specification and builds a 31-sheet
#    workbook in memory at once. The service runs on a 512MB instance, so a
#    handful of simultaneous exports exhausts memory and the container is
#    killed — which presents to the user as an intermittent 500, then a 502 or
#    503 while the instance restarts, and it stays down for as long as the
#    restart takes. One export at a time is what fits.
#
# A waiting request is told the service is busy rather than being left to time
# out, because "busy, try again" is actionable and a hung request is not.
_EXPORT_MUTEX = threading.Lock()
_EXPORT_WAIT_SECONDS = 90.0

# How many requests may be WAITING for the export lock.
#
# Without a bound, every queued request occupies a worker thread for the whole
# wait. The sync routes share one threadpool, so a burst of exports would fill it
# with threads doing nothing but waiting on a lock, and /api/health — the check
# the platform's own uptime monitor uses — would stop answering. The service
# would look dead while doing exactly what it was asked to.
_EXPORT_QUEUE_LIMIT = 2
_export_waiting = threading.Semaphore(_EXPORT_QUEUE_LIMIT)


def _normalize_assumptions(
    assumptions: List["AssumptionObject"],
) -> List["AssumptionObject"]:
    """Deduplicate assumptions to one entry per (driver_key, scenario, period).

    Survivor preference: user_override carrying previous_model_value (revertable),
    then any user_override, then model_generated. A previous_model_value found on
    any dropped duplicate is adopted by the survivor so revert keeps working.
    Repairs specs polluted by the pre-lock duplicate-append race.
    """
    from backend.models.spec.assumptions import AssumptionObject

    grouped: Dict[tuple, List[AssumptionObject]] = {}
    for a in assumptions:
        grouped.setdefault((a.driver_key, a.scenario, a.period), []).append(a)

    def rank(a: AssumptionObject) -> tuple:
        if a.type == "user_override" and a.previous_model_value is not None:
            return (0,)
        if a.type == "user_override":
            return (1,)
        return (2,)

    normalized: List[AssumptionObject] = []
    for group in grouped.values():
        if len(group) == 1:
            normalized.append(group[0])
            continue
        ordered = sorted(group, key=rank)
        survivor = ordered[0]
        rescued_prev = next(
            (g.previous_model_value for g in group if g.previous_model_value is not None),
            None,
        )
        if rescued_prev is not None and survivor.previous_model_value is None:
            survivor = survivor.model_copy(update={"previous_model_value": rescued_prev})
        if survivor.type == "user_override" and survivor.previous_model_value is None:
            # Baseline lost to the race: keep current math, restore revertability
            # going forward by re-basing onto the present value.
            survivor = survivor.model_copy(
                update={"type": "model_generated", "source": "re-based after duplicate repair"}
            )
            logger.warning(
                "Dropped %d duplicate override(s) for %s; re-based (baseline unrecoverable).",
                len(group) - 1, survivor.driver_key,
            )
        else:
            logger.warning(
                "Dropped %d duplicate assumption(s) for %s.",
                len(group) - 1, survivor.driver_key,
            )
        normalized.append(survivor)
    return normalized


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
    """Seed the master universe once per process instead of per request.

    Re-seeding rewrites the seed rows, and those rows carry no slug, so slugs are
    reassigned afterwards. Without this a redeploy would leave every /stock route
    resolving to a 404 until something else happened to write the column.
    """
    global _UNIVERSE_SEEDED
    if not _UNIVERSE_SEEDED:
        from backend.data.universe.master_list import seed_master_universe
        from backend.data.universe.store import assign_slugs_to_universe
        seed_master_universe()
        assign_slugs_to_universe()
        _UNIVERSE_SEEDED = True


from backend.data.batch import ensure_company_ingested
from backend.data.errors import NoFinancialsAvailable
from backend.data.universe.store import update_onboarding_status


def _get_hist_model(company_id: str = "infy_infy") -> HistoricalModel:
    """Return cached HistoricalModel for the given company_id.

    A company with nothing behind it answers 503 here rather than letting the
    error surface as a 500. This is the one place every endpoint that needs a
    company's statements goes through, so the conversion lives here rather than
    being repeated at each caller.

    That matters because the two driver-override endpoints call this directly.
    They were answering 500 on exactly the condition the model endpoint had
    already learned to answer 503, and the state where it bites is ordinary: the
    compiled snapshots are tracked while the database they were built from is
    not, so a fresh deploy reads a model from disk and then fails on the first
    edit of a driver, because the statements behind it were never in the
    checkout.
    """
    global _HIST_MODEL_CACHE
    if company_id not in _HIST_MODEL_CACHE:
        try:
            ensure_company_ingested(company_id)
            _lru_put(
                _HIST_MODEL_CACHE,
                company_id,
                run_historical(
                    target_periods=DEFAULT_HIST_PERIODS,
                    company_id=company_id,
                ),
            )
        except NoFinancialsAvailable as e:
            logger.info("No financials available for %s: %s", company_id, e)
            raise HTTPException(
                status_code=503,
                detail="No financial statements could be sourced for this ticker yet. Try again shortly.",
            )
    return _lru_get(_HIST_MODEL_CACHE, company_id)


def _historicals_fingerprint(spec: ModelSpecification) -> tuple:
    """Anchor figures from the last historical period, for cache freshness checks."""
    periods = spec.historicals.periods or []
    last = periods[-1] if periods else ""
    return (
        spec.historicals.get_value("canonical.is.revenue", last),
        spec.historicals.get_value("canonical.bs.total_assets", last),
    )


def _forecast_contract(spec: ModelSpecification) -> frozenset:
    """The set of canonical keys this spec's forecast actually carries.

    Used to detect a snapshot written by an older engine. Comparing anchor
    values alone cannot see an engine change: a cache that still matches the
    database on revenue and total assets may have been produced before the
    forecast engine began emitting, say, the working-capital movement, in which
    case the valuation layer has to substitute a derived number and the
    published figures no longer come from the model the reader is looking at.
    """
    return frozenset(
        li.canonical_key
        for li in (spec.forecast.line_items if spec.forecast else [])
        if li.scenario == "base"
    )


def _expected_forecast_contract(company_id: str) -> frozenset:
    """Canonical keys the CURRENT forecast engine emits for this company.

    Derived by running the engine rather than from a hardcoded list, so the
    check cannot itself drift out of date when the engine gains a line item.
    """
    from backend.forecast.pipeline import run as run_forecast_pipeline

    return _forecast_contract(run_forecast_pipeline(_get_hist_model(company_id)))


def _cache_matches_database(cached_spec: ModelSpecification) -> bool:
    """True when the cached snapshot was built from the current database state.

    Two independent conditions must hold:

    1. The historical anchors still agree with a fresh assembly, so an ingestion
       correction invalidates the frozen forecast.
    2. The cached forecast carries every canonical key the current forecast
       engine emits, so a snapshot written by an older engine is rebuilt rather
       than served with substituted inputs.
    """
    try:
        company_id = cached_spec.metadata.company_id
        fresh = _get_hist_model(company_id)
        fresh_periods = fresh.periods or []
        last = fresh_periods[-1] if fresh_periods else ""
        anchors = (
            fresh.income_statement.get_value("canonical.is.revenue", last),
            fresh.balance_sheet.get_value("canonical.bs.total_assets", last),
        )
        if _historicals_fingerprint(cached_spec) != anchors:
            return False

        missing = _expected_forecast_contract(company_id) - _forecast_contract(cached_spec)
        if missing:
            logger.info(
                "Rebuilding %s: cached forecast is missing %d canonical key(s) the "
                "current engine emits (e.g. %s)",
                company_id,
                len(missing),
                ", ".join(sorted(missing)[:3]),
            )
            return False
        return True
    except Exception as e:
        logger.warning("Freshness check failed; treating cache as valid: %s", e)
        return True


class _StaleCache(Exception):
    """Raised when a cached snapshot predates the current database state."""


def _cached_spec_session(spec: ModelSpecification) -> Optional[str]:
    """The market session a cached spec was valued against, if it records one."""
    for output in getattr(spec, "valuation", None) or []:
        reverse = getattr(output, "reverse_dcf", None)
        if reverse is not None and reverse.market_price_date:
            return reverse.market_price_date
    return None


def _spec_is_current_for_session(
    spec: ModelSpecification, market: str, now: Optional[datetime] = None
) -> bool:
    """Whether a cached spec was valued against the session that has since closed.

    The in-memory model cache has no time-based expiry. It evicts by capacity, and
    the capacity is larger than the number of onboarded companies, so nothing is
    ever evicted. A spec therefore lived for the life of the process with the
    price frozen at the moment it was first requested, and the daily refresh that
    recomputes valuation against live quotes only ever ran on the one request
    that missed the cache. Every company the process had ever served kept
    yesterday's close indefinitely, and nothing in the served output said so: the
    price carried a real session date and a real source, just not the current one.

    A model is invalidated when a newer session has closed since it was valued.
    That is the same question the quote cache asks, asked with the same calendar,
    so the two cannot disagree about which close is the current one.

    The comparison is for equality, and both directions matter. A spec priced
    against an earlier session is stale, and a spec dated against a session that
    has not happened cannot be a settled close at all, so neither is current.
    """
    session = _cached_spec_session(spec)
    if session is None:
        # Nothing to compare against, so the spec cannot be shown to be current.
        return False
    return session == last_completed_session(market, now).isoformat()


def _get_or_build_spec(
    company_id: str = "infy_infy", force_retry: Optional[bool] = None
) -> ModelSpecification:
    cache_path = PROJECT_ROOT / "backend" / "data" / "cache" / f"{company_id}.json"
    if company_id in _MODEL_CACHE:
        cached_spec = _lru_get(_MODEL_CACHE, company_id)
        reg = REGISTRY_FALLBACKS.get(company_id, {})
        market = reg.get("market") or ("us" if company_id.endswith("_us") else "india")
        if _spec_is_current_for_session(cached_spec, market):
            # Self-heal a snapshot that has gone missing underneath us.
            #
            # `assets/gsd/rebuild.py` deletes the snapshot AND the database rows, then
            # asks the API to rebuild. If this process still holds the model in memory
            # the request is served from the LRU, returns 200, and nothing is written
            # -- so the rebuild reports that the company did not come back, for a
            # model that was sitting right there. One company failed this way
            # repeatedly until the negative cache turned every later attempt into a
            # 503, which is how a recoverable problem presented as unsourceable data.
            #
            # A shipped company whose artifact has vanished should have the artifact
            # restored, not a 200 that pretends it is still there.
            if company_id in _SHIPPED_AT_STARTUP and not cache_path.exists():
                try:
                    write_model_snapshot(cache_path, cached_spec.serialize())
                    logger.info("Restored missing snapshot for %s from memory.",
                                company_id)
                except Exception as e:
                    logger.warning("Could not restore missing snapshot for %s: %s",
                                   company_id, e)
            return cached_spec
        # A newer session has closed. Drop it and revalue, rather than serve a
        # model priced against a close the market has already moved past.
        del _MODEL_CACHE[company_id]
        logger.info(
            "Cached model for %s predates the current %s session; revaluing.",
            company_id,
            market,
        )

    # Whether this company is part of the curated shipped set, as read at import.
    #
    # `data/cache/` is the launch surface: what is in it is what the site serves and
    # what `scripts/check_shipped_set.py` holds us to. Writing to it from the read
    # path meant the surface moved by traffic rather than by intention -- a visitor
    # browsing companies grew the shipped set from 23 to 162 once, and every one of
    # those models then reported as an unreviewed regression.
    #
    # So an on-demand build for a company that is not already shipped stays in the
    # in-memory LRU and is not written. Refreshing a snapshot that already exists is
    # still written, because that keeps a shipped member current rather than adding
    # one. Adding a company to the shipped set becomes a deliberate act.
    has_snapshot = cache_path.exists()

    # A company already known to be unsourceable must not be retried on every
    # request. Once /stock/<ticker> is public an unresolvable slug is something a
    # crawler will find, and retrying spends the upstream providers' budget on a
    # request that cannot succeed.
    # An explicit operator request must be allowed to retry, whatever the negative
    # cache says.
    #
    # `assets/gsd/rebuild.py` deletes the snapshot and the database rows and then
    # asks the API to rebuild. The first attempt can fail for reasons that have
    # nothing to do with the company being unsourceable -- a network blip, an upstream
    # 429, a process restart mid-build. That marks the company negative, and because
    # the cache lives in the process, every subsequent attempt in the same batch is
    # refused instantly without trying. One company in the shipped set could not be
    # rebuilt at all until this was found.
    #
    # The negative cache is right for a crawler hitting a public slug and wrong for a
    # person re-running the build, so the distinction is made explicit rather than
    # left to timing.
    if force_retry is None:
        force_retry = _FORCE_REBUILD
    if force_retry:
        ingest_throttle.clear_failure(company_id)

    if not has_snapshot and ingest_throttle.is_negative(company_id):
        raise HTTPException(
            status_code=503,
            detail="No financial statements could be sourced for this ticker yet. Try again shortly.",
        )

    # Single-flight: concurrent requests for one uncached ticker produce one
    # build. The loser does not start a duplicate.
    with ingest_throttle.single_flight(company_id) as is_first:
        if not is_first:
            raise HTTPException(
                status_code=503,
                detail="This model is being compiled right now. Retry in a few seconds.",
            )
        return _build_spec_locked(company_id, cache_path, has_snapshot)


def _build_spec_locked(
    company_id: str, cache_path: Path, has_snapshot: bool
) -> ModelSpecification:
    """Compile or refresh the spec for one company. Caller holds single-flight."""
    # Read from the release-time set, not from the filesystem. `has_snapshot`
    # describes the request -- a rebuild deletes the file before asking for it
    # back -- while shipped-ness is a property of the release and survives the
    # file being absent.
    is_shipped = company_id in _SHIPPED_AT_STARTUP
    if has_snapshot:
        try:
            spec = ModelSpecification.deserialize(read_model_snapshot(cache_path))
            logger.info("Loaded %s ModelSpecification from precomputed cache.", company_id)
            # The cache holds a build-time SNAPSHOT of market data (price, shares,
            # beta, risk-free rate, ERP). Re-run valuation against live providers so
            # the served model reflects current market prices. The forecast itself is
            # reused from the cache, so this is a light valuation recompute, not a
            # full rebuild. If the live fetch fails (provider or network down),
            # fall back to the snapshot rather than triggering a heavy on-demand
            # ingestion that could OOM the free tier.
            try:
                if not _cache_matches_database(spec):
                    logger.info(
                        "Cache for %s predates current database state; rebuilding.",
                        company_id,
                    )
                    raise _StaleCache()
                spec = run_qa(run_valuation(spec))
                logger.info("Refreshed live market data for %s.", company_id)
            except _StaleCache:
                hist_m = _get_hist_model(company_id)
                spec = run_qa(run_valuation(run_forecast_pipeline(hist_m)))
                try:
                    write_model_snapshot(cache_path, spec.serialize())
                    logger.info("Wrote refreshed cache for %s.", company_id)
                except Exception as e:
                    logger.warning("Warning: could not write cache for %s: %s", company_id, e)
            except Exception as refresh_err:
                logger.warning(
                    "Market-data refresh failed for %s; serving cached snapshot: %s",
                    company_id,
                    refresh_err,
                )
            _lru_put(_MODEL_CACHE, company_id, spec)
            return spec
        except Exception as e:
            logger.warning("Failed to load cache for %s, compiling live: %s", company_id, e)

    # No usable snapshot. This is the branch that performs live ingestion, so it
    # is the one the throttle guards.
    logger.info("No precomputed cache for %s. Ingesting & compiling live...", company_id)
    with ingest_throttle.ingest_slot(company_id) as got_slot:
        if not got_slot:
            raise HTTPException(
                status_code=503,
                detail="The engine is busy compiling other models. Retry shortly.",
            )
        try:
            ensure_company_ingested(company_id)
            hist_m = _get_hist_model(company_id)
            q_spec = run_qa(run_valuation(run_forecast_pipeline(hist_m)))
        except NoFinancialsAvailable as e:
            # A listed ticker with nothing behind it yet. Recorded as a failure so
            # it is not re-attempted on every request, and answered 503 because
            # that is a temporary condition rather than a broken build.
            ingest_throttle.mark_failure(company_id)
            logger.info("No financials available for %s: %s", company_id, e)
            raise HTTPException(
                status_code=503,
                detail="No financial statements could be sourced for this ticker yet. Try again shortly.",
            )
        except Exception:
            ingest_throttle.mark_failure(company_id)
            raise

    _lru_put(_MODEL_CACHE, company_id, q_spec)

    if is_shipped:
        try:
            write_model_snapshot(cache_path, q_spec.serialize())
            logger.info("Wrote compiled cache for %s.", company_id)
        except Exception as e:
            logger.warning("Warning: could not write cache for %s: %s", company_id, e)
    else:
        # Deliberately not written. This model exists in the LRU for this process
        # and nowhere else, so the shipped set does not move because someone browsed.
        logger.info(
            "Compiled %s on demand; held in memory only. Adding it to the shipped "
            "set is a separate, deliberate act.",
            company_id,
        )

    try:
        update_onboarding_status(company_id, "onboarded", notes="On-demand live ingestion")
    except Exception:
        pass

    ingest_throttle.clear_failure(company_id)
    return q_spec


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
    """The complete ModelSpecification, stamped with its publish decision.

    The audit is a report, not a gate. A model whose inputs are known to be wrong
    was being served with the failures listed underneath a professional headline,
    which asks a reader to discount a number rather than refusing to present it.
    That is the wrong way round: the reader cannot see which of the figures to
    discount, and the headline is the only thing most of them will read.

    The specification now carries a `publication` verdict saying whether this model
    is fit to present as a valuation. The full specification is still returned,
    because the audit and the raw figures are the evidence for the verdict, and
    withholding them would make it unfalsifiable.
    """
    _require_valid_company_id(company_id)
    try:
        # An operator rebuild must be allowed to retry; a crawler must not. See
        # `_get_or_build_spec` for why the distinction is explicit rather than timed.
        spec = _get_or_build_spec(company_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to build valuation model for '%s'", company_id)
        # Classify by the TYPE of failure, never by searching the message for words.
        #
        # This was `422 if "No canonical" in str(e) or "unmeasured" in str(e) else
        # 500`, and any error whose text did not contain those two phrases became a
        # 500 "Failed to build model. See server logs for details." One did: an
        # unlisted ticker raised ValueError from resolve_cik, whose message contains
        # neither, so CWDV answered 500 while four other unsourceable tickers in the
        # same 50-company sweep answered 503 for the identical condition.
        #
        # A substring test cannot be right here. It classifies by vocabulary, so
        # rewording an error reclassifies it, and every future "not available" error
        # whose wording differs becomes a fabricated fault. `NoFinancialsAvailable`
        # is the type for "no filing in reach" and it is converted to 503 above and
        # in `_get_hist_model`; a value the filer published nothing for, or a
        # statement shape the parser does not recognise, is 422 -- a request this
        # build cannot answer, not a service that is broken.
        status_code = 422 if isinstance(e, ValueError) else 500
        raise HTTPException(
            status_code=status_code,
            detail="Failed to build model. See server logs for details.",
        )

    payload = spec.model_dump(mode="json")
    payload["publication"] = _publication_verdict(spec)
    return payload


# A failing check that makes the INPUTS implausible, rather than one that makes
# the arithmetic disagree, is what disqualifies a model. A model that reconciles
# and is merely far from the market is an opinion, and opinions are the product.
# A model built on a cost of revenue that exceeds its revenue is not an opinion,
# it is a broken number, and presenting it as a valuation is a defect.
_INPUT_DEFECT_CHECKS = frozenset(
    {
        "bridge_inputs_plausible",
        "income_statement_is_coherent",
        "year_one_growth_is_plausible",
        "terminal_value_is_not_carrying_the_model",
        "equity_value_positive",
        "cost_of_capital_is_live",
        # A negative enterprise value, equity value or share price is arithmetic
        # that cannot happen, not a valuation that disagrees with the market. Three
        # companies shipped one. Presenting it as "opinion_only" would still put a
        # negative share price on the page.
        "valuation_is_meaningful",
        "debt_is_actually_sourced",
            # The launch bar itself. Thirteen of twenty-three shipped companies
            # had no filing behind their historicals, and nine of them were
            # publishing a full valuation anyway, off a market feed nobody had
            # verified against a filing.
            "inputs_trace_to_a_filing",
    }
)


def _publication_verdict(spec) -> Dict[str, Any]:
    """Whether this model may be presented as a valuation, and why not."""
    checks = getattr(getattr(spec, "qa", None), "checks", None) or []
    failed = [c for c in checks if not getattr(c, "passed", True)]
    defect_checks = sorted(
        {c.check_name for c in failed if c.check_name in _INPUT_DEFECT_CHECKS}
    )
    other_failures = sorted(
        {c.check_name for c in failed if c.check_name not in _INPUT_DEFECT_CHECKS}
    )
    reasons = [
        f"{c.check_name}: {c.detail}"
        for c in failed
        if c.check_name in _INPUT_DEFECT_CHECKS and c.detail
    ]

    publishable = not defect_checks
    return {
        # "publishable" when the inputs are believable. "opinion_only" when the
        # arithmetic reconciles but the inputs do not support a valuation.
        "status": "publishable" if publishable else "opinion_only",
        "publishable": publishable,
        "input_defect_checks_failed": defect_checks,
        "other_checks_failed": other_failures,
        "reasons": reasons,
        "summary": (
            "Inputs pass every plausibility check."
            if publishable
            else (
                f"{len(defect_checks)} input check(s) failed, so these figures are "
                "not presented as a valuation. The audit and the raw numbers are below."
            )
        ),
    }


@router.post("/model/recompute")
def recompute_model(req: OverrideRequest, company_id: str = "infy_infy") -> Dict[str, Any]:
    """Apply driver override, re-run forecast -> valuation -> QA engine, and return updated spec."""
    _require_valid_company_id(company_id)
    with _SPEC_MUTEX:
        spec = _get_or_build_spec(company_id)
        spec.assumptions = _normalize_assumptions(spec.assumptions)

        # 1. Update assumption list with override across all forecast periods
        new_assumptions = []
        found = False
        for a in spec.assumptions:
            if a.driver_key == req.driver_key and a.scenario == req.scenario:
                new_assumptions.append(a.with_override(req.value))
                found = True
            else:
                new_assumptions.append(a)

        if not found:
            # Create new override, snapshotting the model-generated baseline so
            # revert() can restore it (a missing previous value made overrides
            # permanently stuck pre-fix).
            from backend.models.spec.assumptions import AssumptionObject
            baseline = next(
                (a.value for a in spec.assumptions
                 if a.driver_key == req.driver_key and a.type == "model_generated"),
                None,
            )
            new_ass = AssumptionObject(
                driver_key=req.driver_key,
                value=req.value,
                period="all",
                scenario=req.scenario,  # type: ignore
                type="user_override",
                source="Analyst Override",
                previous_model_value=baseline,
            )
            new_assumptions.append(new_ass)

        new_assumptions = _normalize_assumptions(new_assumptions)

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
    _require_valid_company_id(company_id)
    with _SPEC_MUTEX:
        spec = _get_or_build_spec(company_id)
        spec.assumptions = _normalize_assumptions(spec.assumptions)

        new_assumptions = []
        for a in spec.assumptions:
            is_match = (req.driver_key == "all" or a.driver_key == req.driver_key)
            if is_match and a.scenario == req.scenario and (a.period in (req.period, "all") or req.period == "all"):
                new_assumptions.append(a.reverted())
            else:
                new_assumptions.append(a)

        new_assumptions = _normalize_assumptions(new_assumptions)

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
def export_excel(company_id: str = "infy_infy") -> Response:
    """Build the workbook and return it as a download.

    One export runs at a time; see _EXPORT_MUTEX for why. A request that cannot
    get the lock is told the service is busy rather than being allowed to pile
    onto an already exhausted instance.
    """
    _require_valid_company_id(company_id)

    # Refuse at the door rather than queueing without limit: a waiting request
    # holds a worker thread, and the sync threadpool is shared with every other
    # route including the health check.
    if not _export_waiting.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail=(
                "Workbooks are already being built. This service builds a small "
                "number at a time so it stays within memory; try again shortly."
            ),
            headers={"Retry-After": "20"},
        )
    try:
        if not _EXPORT_MUTEX.acquire(timeout=_EXPORT_WAIT_SECONDS):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Another workbook is being built. This service builds one at "
                    "a time so it stays within memory; try again in a moment."
                ),
                headers={"Retry-After": "20"},
            )
        try:
            return _export_excel_locked(company_id)
        finally:
            _EXPORT_MUTEX.release()
    finally:
        _export_waiting.release()


def _export_excel_locked(company_id: str) -> Response:
    """The export itself. Callers must hold _EXPORT_MUTEX."""
    spec = _get_or_build_spec(company_id)
    if spec is None:
        raise HTTPException(
            status_code=503,
            detail="The model is still being prepared for this company. Try again in a moment.",
            headers={"Retry-After": "10"},
        )

    out_dir = PROJECT_ROOT / "backend" / "export" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Named for the company, not the ticker. Two onboarded companies can share a
    # ticker — the same issuer listed in two markets — and a ticker-keyed name
    # had both writing one file, so a download could be served the other
    # listing's workbook.
    safe_company = re.sub(r'[^a-zA-Z0-9_-]', '', company_id.lower())
    file_path = out_dir / f"{safe_company}_valuation_model.xlsx"

    try:
        export_model_to_excel(spec, file_path)
    except HTTPException:
        raise
    except MemoryError:
        # The one failure a user can act on by trying again later.
        logger.exception("Out of memory building the workbook for %s", company_id)
        raise HTTPException(
            status_code=503,
            detail="The workbook needs more memory than is free right now. Try again shortly.",
            headers={"Retry-After": "30"},
        )
    except Exception as exc:
        # An unhandled exception here returns a bare "Internal Server Error",
        # which tells the user nothing and tells us nothing. The traceback is
        # logged; the message says which company failed.
        logger.exception("Workbook export failed for %s", company_id)
        raise HTTPException(
            status_code=500,
            detail=f"Could not build the workbook for {company_id}: {type(exc).__name__}",
        )

    if not file_path.exists():
        raise HTTPException(status_code=500, detail="Failed to generate Excel file")

    # The bytes are read while the lock is still held and returned in memory.
    #
    # A FileResponse streams from the path AFTER this function returns, by which
    # point the lock is released and another export of the same company can
    # rewrite the very file being streamed. A download would then be truncated
    # or contain a half-written workbook. Reading it here costs one workbook's
    # worth of memory briefly, which the serialisation already bounds.
    try:
        payload = file_path.read_bytes()
    except OSError as exc:
        logger.exception("Could not read the workbook for %s", company_id)
        raise HTTPException(
            status_code=500,
            detail=f"Could not read the workbook for {company_id}: {type(exc).__name__}",
        )

    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{file_path.name}"',
            "Content-Length": str(len(payload)),
        },
    )


# Slug shape accepted from the public web tier. Deliberately tighter than
# COMPANY_ID_PATTERN: a URL segment is untrusted input arriving from the internet,
# so it is bounded tightly before it is used in a query or a file path.
SLUG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,31}$")

# Whether the request currently in flight is an explicit operator rebuild.
#
# Read from a header by middleware rather than by threading a `Request` through four
# route handlers into a plain helper that has no business knowing about HTTP. The
# distinction is worth this little piece of machinery: the negative cache stops a
# crawler retrying an unsourceable ticker, and without a way to override it, a
# rebuild that failed once for an unrelated reason -- a network blip, an upstream
# 429 -- left a shipped company permanently unrebuildable for the life of the process.
_FORCE_REBUILD = False


def set_force_rebuild(value: bool) -> None:
    """Mark the request in flight as an explicit operator rebuild.

    Read from a header by the middleware registered in `main.py`, rather than by
    threading a `Request` through four route handlers into a plain helper that has
    no business knowing about HTTP.

    The distinction is worth this little piece of machinery. The negative ingestion
    cache stops a crawler retrying an unsourceable ticker, which is correct; but
    without a way to override it, a rebuild that failed once for an unrelated reason
    -- a network blip, an upstream 429, a process restart mid-build -- left a shipped
    company permanently unrebuildable for the life of that process. One did.
    """
    global _FORCE_REBUILD
    _FORCE_REBUILD = bool(value)


MODEL_CACHE_DIR = PROJECT_ROOT / "backend" / "data" / "cache"

# The shipped set, read ONCE at import, before anything can create or remove a file.
#
# Reading membership per-request was wrong, and wrong in a way the rebuild tooling
# found immediately: `assets/gsd/rebuild.py` deletes a snapshot and then asks the API
# to rebuild it, so a per-request existence test saw the company as unshipped and
# declined to write it. All 23 rebuilds failed. The same test would also have
# mis-classified a shipped model whose snapshot was corrupt and being repaired.
#
# Membership is a property of the release, not of the filesystem's current state. A
# shipped company stays shipped while its file happens to be absent, because the
# file being absent is a fact about the request, not about the product.
_SHIPPED_AT_STARTUP: frozenset[str] = frozenset(
    f.stem for f in MODEL_CACHE_DIR.glob("*.json") if f.stem != "market_data_cache"
)
logger.info("Shipped set at startup: %d companies", len(_SHIPPED_AT_STARTUP))


def _has_compiled_model(company_id: str) -> bool:
    """True when a model snapshot exists on disk for this company.

    Written by _build_spec_locked on every successful build, so it records a
    model that has genuinely been produced rather than one that could be.
    """
    return (MODEL_CACHE_DIR / f"{company_id}.json").exists()


def _model_built_at(company_id: str) -> str | None:
    """When this company's model was last compiled, as an ISO date.

    Read from the same snapshot `_has_compiled_model` already looks at, so the
    two cannot disagree about whether a model exists.

    This exists so the sitemap can state a real last-modified date. It was
    stamping every URL with the moment the sitemap was generated instead, so
    twenty-two pages that had not changed in months all claimed to have been
    edited in the same millisecond, and the methodology page claimed to change
    every time the sitemap revalidated. A last-modified value is how a crawler
    decides what is worth re-fetching, and one that is always "now" is a signal to
    re-fetch everything or to stop trusting the field, which loses the distinction
    the field exists to carry.
    """
    path = PROJECT_ROOT / "backend" / "data" / "cache" / f"{company_id}.json"
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()


def _manifest_record(c) -> Dict[str, Any]:
    return {
        "slug": c.slug,
        "company_id": c.company_id,
        "ticker": c.ticker,
        "name": c.name,
        "market": c.market,
        "exchange": c.exchange,
        "sector": c.sector,
        "cik": c.cik,
        "has_model": _has_compiled_model(c.company_id),
        # Whether this company is in scope for the model engine at all.
        #
        # A bank or an insurer is deliberately excluded: an unlevered FCFF DCF
        # needs operating cash flow to discount, and a financial does not generate
        # one, so the engine has no correct answer to give. Those companies carry no
        # slug and /stock/<ticker> 404s them by design.
        #
        # The search dropdown was still offering them as clickable rows labelled
        # "Builds on open", which is a promise the resolver cannot keep. HDFC Bank
        # and JPMorgan appeared in results and 404'd on click. The exclusion is
        # right; advertising it as buildable was not.
        "is_financial": bool(getattr(c, "is_financial", False)),
        # The date the compiled model was written, for the sitemap's lastmod.
        # A date and not a timestamp: the sitemap is revalidated far more often
        # than any model changes, and a value that moves on every revalidation
        # says nothing.
        "model_built_at": _model_built_at(c.company_id),
    }


@router.get("/companies/manifest")
def get_company_manifest(
    offset: int = Query(0, ge=0, description="Row offset for paging"),
    limit: int = Query(500, ge=1, le=5000, description="Max rows per page"),
) -> Dict[str, Any]:
    """The public URL universe: every non-financial company that has a slug.

    Backs the /stock index and sitemap generation. Financial-sector rows are
    excluded because the model engine does not service them, so a slug pointing
    at one would resolve to a page that can never load.
    """
    from backend.data.universe.store import list_slugs

    _ensure_universe_seeded()
    rows = list_slugs()
    window = rows[offset : offset + limit]
    return {
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < len(rows),
        "companies": [_manifest_record(c) for c in window],
    }


@router.get("/companies/resolve")
def resolve_company_slug(
    slug: str = Query(..., description="Public URL slug, e.g. NVDA or INFY-NYSE"),
) -> Dict[str, Any]:
    """Resolve one public slug to a company. The allowlist behind every /stock route.

    Returning 404 for an unknown slug is the security boundary, not a
    convenience: the page route must never pass an unrecognised segment through
    to /api/model/{company_id}, which would let any well-formed URL trigger live
    third-party ingestion.

    The boundary is unchanged in kind, only in width. A slug that matches no
    stored company is looked up in the exchange index and, if the exchange lists
    it, registered on the spot. So the allowlist is no longer a list someone
    curated by hand: it is every company SEC or the NSE publishes, which is the
    same authority that made the original 22 safe. What is still refused is
    anything neither exchange lists, and a near-miss, because
    ``ticker_index.lookup`` is an exact match and a fuzzy one would hand a page
    route a company_id whose filings belong to somebody else.
    """
    from backend.data.universe import ticker_index
    from backend.data.universe.store import get_universe_by_slug

    if not SLUG_PATTERN.match((slug or "").strip()):
        raise HTTPException(status_code=400, detail="Malformed ticker slug.")

    _ensure_universe_seeded()
    company = get_universe_by_slug(slug)
    if company is None:
        # Exact match, so a slug that merely resembles a ticker still 404s.
        company, _created = ticker_index.resolve_or_register(slug)
    if company is None:
        raise HTTPException(status_code=404, detail="Unknown ticker.")

    return _manifest_record(company)


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
    """Search the companies Valence already models, then the listed universe.

    Two passes, deliberately ordered. The local store comes first and without a
    cap, so a company that has a compiled model is never displaced by an
    alphabetical neighbour from the index. The index then fills the remaining
    room, and those rows carry ``has_model: false`` and a sector of ``""``,
    which is the honest description: listed, not yet built.

    Discovered rows are not written here. Registering on a keystroke would mean a
    search request mutates the universe, and a visitor typing three letters
    would seed three junk rows. Registration happens on resolve, which is a
    deliberate act.
    """
    from backend.data.universe import ticker_index
    from backend.data.universe.store import preview_slug as _preview_slug
    from backend.data.universe.store import search_universe_companies
    from backend.models.spec.metadata import get_metadata_for_company

    _ensure_universe_seeded()
    m_filter = market if market in ("india", "us") else None

    # Reserve part of the result budget for the wider universe.
    #
    # The local pass was uncapped, so for a query like "TATA" it filled all
    # eight slots with covered companies (TATASTEEL, TATAMOTORS, TCS) and the
    # discoveries were pushed off the end. The search looked like it only knew
    # the curated set, which is the opposite of what it does.
    #
    # Half the budget is reserved rather than all of it: a visitor searching for
    # a company they already know is covered should still see it first, but a
    # visitor searching a common prefix has to be able to see that the wider
    # universe answered too.
    local_budget = limit if limit <= 2 else (limit + 1) // 2
    local = search_universe_companies(query=q, market=m_filter, limit=local_budget)

    payload = []
    for c in local:
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
            # Whether a model snapshot actually exists, which is not the same
            # thing as being onboarded. Onboarded means the filings are in the
            # store; has_model means a valuation has been compiled and will be
            # served without a build. The client badges results on this, and it
            # was reading onboarding_status instead, so every result came back
            # "Ready" and the badge claimed a compiled model that mostly did not
            # exist yet.
            "has_model": _has_compiled_model(c.company_id),
            # Carried so selecting a result can rewrite the address bar to a
            # canonical link rather than leaving the URL on the previous ticker.
            "slug": c.slug,
            # Out of scope for the model engine. Banks and insurers are held back
            # deliberately: an unlevered FCFF DCF discounts operating cash flow and
            # a financial does not generate one, so there is no correct answer to
            # give them and no page exists. Advertising them as "Builds on open"
            # was a promise the resolver cannot keep -- HDFC Bank and JPMorgan were
            # offered as clickable rows and 404'd on click.
            #
            # This is a hand-built payload rather than the shared _manifest_record,
            # which is the seventh time in this project a record shape has been
            # duplicated and drifted: the same defect as the client's copy of the
            # publication check names, and as the test script's list of files. A
            # second place to keep in step, with nothing to notice when it falls
            # behind.
            "is_financial": bool(getattr(c, "is_financial", False)),
        })

    if len(payload) < limit and q.strip():
        # The market is passed INTO discovery rather than filtered out after it.
        #
        # Filtering afterwards spent the result budget on a market-blind ranking
        # and then discarded the rows that did not match, so `market=us&limit=3`
        # returned one row because three Indian names filled the budget first.
        # The scope now decides what gets ranked.
        found = ticker_index.discover(q, limit=limit - len(payload), market=m_filter)

        # Dedup on (ticker, market), which is the key `search` itself uses. A
        # ticker-only key silently deleted a genuinely distinct company: the
        # Indian and US lines of one name differ by market, and dropping the
        # second because the ticker matched left a user who wanted the ADR with
        # no way to reach it. The local pass can also hold both listings, so the
        # two passes have to agree on identity.
        known = {(row["ticker"].upper(), row["market"]) for row in payload}
        for listed in found:
            marker = (listed.ticker.upper(), listed.market)
            if marker in known:
                continue
            known.add(marker)
            payload.append({
                # The id the ingestion pipeline will key on, built the same way
                # as every stored company so opening the result needs no second
                # round trip to discover its id.
                "company_id": listed.company_id,
                "ticker": listed.ticker,
                "name": listed.name,
                "market": listed.market,
                "exchange": listed.exchange,
                "sector": "",
                # Unknown until the filings are read, so the units are not
                # guessed from the exchange. A currency shown before anyone has
                # seen the statements is a claim the engine has not made yet.
                "currency": None,
                "units": None,
                "onboarding_status": "not_yet_attempted",
                "has_model": False,
                # The slug this ticker will be given, computed but not reserved.
                # Search results are contractually required to carry one so the
                # client can navigate straight to the company page, and writing a
                # row per keystroke is not an option. Resolve returns the real
                # slug, which can differ if a collision appeared in between, and
                # the client navigates to whatever resolve says.
                "slug": _preview_slug(listed.ticker, listed.market, listed.exchange, listed.cik),
            })
    return payload



# ------------------------------------------------------------------ #
# Persistence Endpoints
# ------------------------------------------------------------------ #
# NOTE: Model persistence moved to browser localStorage (frontend). The
# previous server-side /api/models/* endpoints backed by per-user file
# storage were removed along with auth. No backend persistence exists.

