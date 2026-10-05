from __future__ import annotations

"""
India Ingestion & Reconciliation Pipeline Module.

Orchestrates Screener.in primary ingestion, optional secondary BSE/NSE PDF filing extraction,
and automated metric reconciliation across all onboarded Indian companies.

Data source priority (highest → lowest):
    1. nse_filing  — NSE annual report PDFs (audited, authoritative for Indian companies)
    2. sec_edgar   — SEC EDGAR XBRL (authoritative for US-listed companies)
    3. bse_filing  — BSE annual report PDFs (stub — same data as NSE, for future expansion)
    4. screener    — Screener.in third-party aggregation (secondary; may differ from filings)
    5. yfinance_live — Real-time market data (limited financial statement detail)

Source coverage audit (as of current DB):
    Companies with NSE filing: infy_infy (nse_filing + screener)
    Companies with SEC EDGAR:  aapl_us, amba_us, amd_us, amzn_us, awi_us, dox_us,
                               googl_us, infy_us, intc_us, meta_us, msft_us, nflx_us,
                               nvda_us, tsla_us
    Companies with screener:   hcltech_hcltech, lt_lt, sunpharma_sunpharma,
                               tatamotors_tatamotors, tatasteel_tatasteel, tcs_tcs, wipro_wipro
    Companies with yfinance:   bhartiartl_bhartiartl, hindunilvr_hindunilvr, idea_idea,
                               itc_itc, kaynes_kaynes, maruti_maruti, ongc_ongc,
                               reliance_reliance, tatapower_tatapower, tsm_tsm
"""

import json
import logging
from pathlib import Path

from backend.data.ingestion.screener import parse_screener_export
from backend.data.parsers.pdf_tables import parse_predicted_statement_page
from backend.data.reconciliation import reconcile
from backend.data.store import RawDatapoint, delete_company_datapoints, save_datapoints

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "valence.db"
SOURCES = HERE / "sources"
FILINGS = HERE / "filings"
LOG_PATH = HERE / "discrepancy_log.json"

logger = logging.getLogger(__name__)


def _cached_nse_pdfs(company_id: str) -> list[tuple[Path, dict]]:
    """Cached NSE attachments for this company, with the fetcher's own metadata.

    The fetcher writes `<symbol>.json` beside each PDF and records the balance-sheet pages
    it found by CONTENT. That record is the only thing connecting a company to a document,
    and it is what this function reads rather than a filename or a hardcoded page number.

    The metadata is MATCHED BY ITS OWN `symbol` FIELD, and the directory is searched rather
    than indexed by a guessed filename. The first version built the path as
    `NSE_CACHE_DIR / f"{ticker.upper()}.json"`, which works on Windows and returns nothing on
    Linux, because the fetcher writes the symbol in whatever case it was invoked with
    (`tcs.json`) and only Windows resolves `TCS.json` to it. The whole path was invisible
    until CI ran it on a case-sensitive filesystem and both companies came back with zero
    filing rows -- the exact symptom this function exists to fix, reappearing for a new
    reason.

    Matching the recorded symbol also means a cache holding `TCS.json` and one holding
    `tcs.json` both work, and a metadata file whose name disagrees with its contents is
    still found by what it says rather than by what it is called.
    """
    from backend.data.ingestion.nse_filings import NSE_CACHE_DIR

    ticker = company_id.split("_")[0].strip().upper()
    if not ticker or not NSE_CACHE_DIR.is_dir():
        return []

    found: list[tuple[Path, dict]] = []
    for meta_path in sorted(NSE_CACHE_DIR.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        symbol = str(meta.get("symbol") or "").strip().upper()
        if symbol != ticker:
            continue
        pdfs = sorted(meta_path.parent.glob(f"{meta_path.stem}-*.pdf"))
        found.extend((p, meta) for p in pdfs)
    return found


# Whether the product may reach the exchange at all.
#
# **OFF unless a deployment explicitly enables it**, and that default is a decision rather than an
# oversight. Three reasons, in order of weight.
#
# 1. It is a read-path side effect. `ensure_company_ingested` runs on the request path, so enabling
#    this by default would mean browsing the site generates exchange traffic. It was observed doing
#    exactly that: one full test-suite run ingested a company with no cached filing and pulled a
#    193-page, 23MB results PDF from the exchange. A unit test that performs network I/O against a
#    third party is the same defect as the network marker that promised otherwise and never did it.
# 2. The exchange's terms govern how often a client may ask, and that has not been answered. Until
#    it is, the honest default is that this codebase does not ask on its own.
# 3. The product degrades perfectly well without it: a labelled market feed, which is what every
#    Indian company read before acquisition existed. Turning this on changes what the site fetches
#    from a third party, so it belongs in the environment where it is visible, not buried in a
#    conditional that an ingest call happens to pass through.
ACQUISITION_ENABLED_ENV = "VALENCE_ENABLE_NSE_ACQUISITION"

# How long a failed fetch is remembered, and how many one process may attempt per window.
#
# Both mirror the ticker index's own fetch policy, deliberately. The negative memory stops a filer
# with no available statement from being retried on every request forever; the budget stops a burst
# of cold reads from becoming a burst of requests. Neither is persisted: a restart is the right time
# to try again, and a negative cache that outlived the process would mean a filing could never be
# picked up without a redeploy.
ACQUISITION_FAILED_TTL_SECONDS = 5 * 60
ACQUISITION_BUDGET = 25
ACQUISITION_BUDGET_WINDOW_SECONDS = 60 * 60

_acquisition_failed: dict[str, float] = {}
_acquisition_spends: list[float] = []


def _spends_in_window(now: float) -> int:
    """How many fetches this process has made inside the current window.

    A ROLLING WINDOW, not a lifetime cap. The first version counted 25 fetches for the life of the
    process, which meant a long-running server acquired 25 filings ever and then silently stopped --
    a degradation with no symptom and indistinguishable from "acquisition is broken". A window bounds
    the RATE, which is the property that protects the exchange, and still lets a busy server pick
    filings up over time.

    Not thread-safe, and that is a decision rather than an oversight. This is a ceiling on traffic to
    a third party; the worst case is that N concurrent reads each pass the check before any of them
    records a spend, so the true rate is a small multiple of the ceiling rather than exactly it.
    Locking would make a read-path function contend on every cold company, which is the worse trade.
    The overshoot is bounded by the number of concurrent readers, not by time.
    """
    cutoff = now - ACQUISITION_BUDGET_WINDOW_SECONDS
    return sum(1 for stamp in _acquisition_spends if stamp > cutoff)


def acquisition_enabled() -> bool:
    """Whether this process may contact the exchange. Off unless a deployment asks for it."""
    import os

    return os.environ.get(ACQUISITION_ENABLED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def reset_acquisition_state() -> None:
    """Clear the failure memory and the budget. For tests, and for an operator forcing a retry."""
    _acquisition_failed.clear()
    _acquisition_spends.clear()


def acquisition_state(company_id: str) -> tuple[bool, str]:
    """Whether this company may be fetched right now, and why not if it may not.

    Returns ``(allowed, reason)``, the reason being one of ``disabled``, ``cached``,
    ``recent-failure``, ``budget-exhausted``, or ``allowed``.

    Split from the fetch so the decision can be asserted directly, with no network and no sleeping,
    and so the caller acts on a returned answer rather than on a side effect.
    """
    ticker = company_id.split("_")[0].strip().upper()
    if not ticker:
        return False, "empty-company-id"
    if not acquisition_enabled():
        return False, "disabled"
    if _cached_nse_pdfs(company_id):
        return False, "cached"

    import time

    now = time.monotonic()
    failed_at = _acquisition_failed.get(ticker)
    if failed_at is not None and now - failed_at < ACQUISITION_FAILED_TTL_SECONDS:
        return False, "recent-failure"
    if _spends_in_window(now) >= ACQUISITION_BUDGET:
        return False, "budget-exhausted"
    return True, "allowed"


def acquire_filing(company_id: str) -> bool:
    """Try once to fetch this company's audited statement from the exchange.

    **Best-effort by contract, and that is the whole design.** This is called from the read path, so
    every failure route returns False, writes nothing, and raises nothing. The company then reads its
    market feed with that labelled, exactly as every Indian company read before this existed. It must
    never become an error page, and never a half-written model.

    The fallback is acceptable precisely because it is visible. A fallback that silently produced a
    plausible *filed* answer would be worse than a failure; this one produces a market figure that
    says it is a market figure.

    The acquirer itself, `NSEFilings`, is untouched and already tested. This decides whether to call
    it and remembers the answer. A success writes the PDF and its metadata, which is exactly what
    `_cached_nse_pdfs` reads, so the next caller sees it immediately and does not fetch again.
    """
    import time

    ticker = company_id.split("_")[0].strip().upper()
    allowed, _reason = acquisition_state(company_id)
    if not allowed:
        return False

    global _acquisition_spends
    _acquisition_spends.append(time.monotonic())

    try:
        from backend.data.ingestion.nse_filings import NSE_CACHE_DIR, NSEFilings

        result = NSEFilings(NSE_CACHE_DIR).acquire(ticker)
    except Exception as exc:  # noqa: BLE001
        # Transport error, rate limit, changed endpoint, parse failure -- all mean the same thing
        # here, which is "not now". Debug level keeps a cold read quiet.
        _acquisition_failed[ticker] = time.monotonic()
        logger.debug("acquisition for %s failed: %s: %s", ticker, type(exc).__name__, exc)
        return False

    if not getattr(result, "ok", False):
        _acquisition_failed[ticker] = time.monotonic()
        logger.info(
            "%s: no audited statement available from the exchange (%s). Reading the market feed "
            "instead, which is labelled as the feed.",
            ticker, getattr(result, "note", "no reason recorded"),
        )
        return False

    _acquisition_failed.pop(ticker, None)
    logger.info(
        "%s: fetched %s, %s pages, balance sheet at %s.",
        ticker, getattr(result, "url", "?"), getattr(result, "pages", "?"),
        getattr(result, "balance_sheet_pages", "?"),
    )
    return True


def _filing_datapoints_from_cached_pdf(
    pdf_path: Path, meta: dict, company_id: str
) -> list[RawDatapoint]:
    """Parse the balance-sheet pages the fetcher located, and only those.

    THIS FUNCTION IS THE MISSING LAST MILE, and its absence is why all twelve India models
    are `opinion_only`.

    `nse_filings.py` acquires the audited PDF, opens it, and finds the balance sheet by
    content -- HCLTech's at printed page 5, TCS's at printed pages 11 and 20, both measured
    against the cached documents. It records the page numbers in its metadata and returns.
    Nothing read that record: `balance_sheet_pages` had no consumer outside the fetcher and
    its own test, so the database held ZERO `nse_filing` rows for TCS, HCLTech and Tata
    Steel while their audited statements sat in `backend/data/filings/nse/` already
    downloaded and already located.

    That is a different defect from the one on record. The recorded blocker is the
    `inputs_trace_to_a_filing` threshold of 0.9, which needs more than 2,736 filing rows per
    company and is therefore unreachable by parser work. But that arithmetic only describes
    the LAST step. There was no parser at all between the located page and the datastore, so
    the threshold was never the thing standing in the way.

    Two details that are easy to get wrong and are asserted by the tests rather than by
    reading:

    The fetcher records PRINTED page numbers (`i + 1`) because that is what a reader sees in
    the document. `parse_predicted_statement_page` takes a 0-BASED INDEX into `pdf.pages`.
    Off by one here lands on the facing page, which for a balance sheet is the note before
    it or the statement after, and the rows read cleanly off the wrong page.

    The section is not asserted by the caller. `looks_like_balance_sheet` matched the
    balance sheet's own subtotal caption on that page, so "BALANCE SHEET" is what the
    document says about itself, not what the caller would like it to be. The previous
    hardcoded table asserted `section="PROFIT & LOSS"` for a page that prints a
    comprehensive income statement.
    """
    pages = meta.get("balance_sheet_pages") or []
    dps: list[RawDatapoint] = []
    for printed in pages:
        page_index = int(printed) - 1
        try:
            dps.extend(
                parse_predicted_statement_page(
                    pdf_path,
                    page_index,
                    "BALANCE SHEET",
                    "nse_filing",
                    annual_only=False,
                    company_id=company_id,
                )
            )
        except Exception as exc:  # noqa: BLE001
            # One unreadable page must not cost the others, and the reason must be
            # recorded rather than discarded. A silent `pass` here is indistinguishable
            # from a document with nothing on it, which is how a whole filer's
            # statements go missing without anything saying so.
            logger.warning(
                "Could not read %s printed page %s of %s: %s: %s",
                printed, company_id, pdf_path.name, type(exc).__name__, exc,
            )
    return dps


def _get_secondary_filing_datapoints(company_id: str) -> list[RawDatapoint]:
    """Audited filing datapoints for this company, from whatever document we hold.

    The cached-NSE path runs first and covers every India company the fetcher has acquired
    a statement for. The Infosys hardcoded table is kept because its document predates the
    fetcher and lives outside its cache directory, not because it is a better way.
    """
    filing_dps: list[RawDatapoint] = []

    for pdf_path, meta in _cached_nse_pdfs(company_id):
        filing_dps.extend(_filing_datapoints_from_cached_pdf(pdf_path, meta, company_id))

    if filing_dps:
        logger.info(
            "%s: %d filing datapoints from %d cached NSE attachment(s)",
            company_id, len(filing_dps), len(_cached_nse_pdfs(company_id)),
        )
        return filing_dps

    company_filings_dir = FILINGS / company_id
    if company_filings_dir.exists() and company_filings_dir.is_dir():
        for pdf in sorted(company_filings_dir.glob("*.pdf")):
            from backend.data.ingestion.nse_filings import balance_sheet_pages
            import pdfplumber

            try:
                with pdfplumber.open(pdf) as doc:
                    found = balance_sheet_pages(doc)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Could not scan %s for a balance sheet: %s: %s",
                    pdf.name, type(exc).__name__, exc,
                )
                continue
            for printed in found:
                try:
                    filing_dps.extend(
                        parse_predicted_statement_page(
                            pdf, printed - 1, "BALANCE SHEET", "nse_filing",
                            annual_only=False, company_id=company_id,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Could not read %s printed page %s of %s: %s: %s",
                        printed, company_id, pdf.name, type(exc).__name__, exc,
                    )

    elif company_id == "infy_infy":
        fy26_pdf = FILINGS / "infosys-fy26-q4-outcome.pdf"
        fy25_pdf = FILINGS / "infosys-fy25-q4-outcome.pdf"
        if fy26_pdf.exists() and fy25_pdf.exists():
            fy26 = [
                parse_predicted_statement_page(fy26_pdf, 99, "BALANCE SHEET", "nse_filing", annual_only=False, company_id=company_id),
                parse_predicted_statement_page(fy26_pdf, 100, "PROFIT & LOSS", "nse_filing", annual_only=True, company_id=company_id),
                parse_predicted_statement_page(fy26_pdf, 103, "CASH FLOW", "nse_filing", annual_only=False, company_id=company_id),
            ]
            fy25 = [
                parse_predicted_statement_page(fy25_pdf, 105, "BALANCE SHEET", "nse_filing", annual_only=False, company_id=company_id),
                parse_predicted_statement_page(fy25_pdf, 106, "PROFIT & LOSS", "nse_filing", annual_only=True, company_id=company_id),
                parse_predicted_statement_page(fy25_pdf, 109, "CASH FLOW", "nse_filing", annual_only=False, company_id=company_id),
            ]
            filing_dps = [d for page in (fy26 + fy25) for d in page]

    if not filing_dps:
        logger.info(
            "%s: no audited filing datapoints. No cached NSE attachment for this ticker "
            "(expected %s/<TICKER>.json beside a downloaded PDF), no per-company "
            "filings directory, and no legacy document.",
            company_id, FILINGS / "nse",
        )

    return filing_dps


def run(
    company_id: str = "infy_infy",
    db_path: str | Path = DB_PATH,
    clear_db: bool = False,
    reset_store: bool = False,
) -> dict:
    """Run India ingestion and reconciliation pipeline for company_id.

    `clear_db` means "discard what is currently stored for THIS company" — it
    deletes that company's rows. It used to unlink the database file, so asking
    one company to re-ingest silently destroyed every other company's data plus
    the universe table, and the next build served a one-company store. Deleting
    an entire shared store is a different and much rarer operation, so it now has
    its own name.
    """
    from backend.data.batch import _source_file_for

    db_p = Path(db_path)
    if reset_store and db_p.exists():
        db_p.unlink()
    elif clear_db:
        delete_company_datapoints(db_p, company_id)

    # 1. Primary path: Screener export
    src_file = _source_file_for(company_id)
    screener_dps = parse_screener_export(src_file, company_id=company_id)

    # 2. Secondary path: BSE/NSE filing PDFs (optional per company)
    filing_dps = _get_secondary_filing_datapoints(company_id)

    # 3. Persist raw datapoints into store
    save_datapoints(db_p, screener_dps + filing_dps, clear_existing=False)

    # 4. Reconcile primary vs secondary sources for company_id
    discrepancies = reconcile(db_p, LOG_PATH, company_id=company_id)

    summary = {
        "company_id": company_id,
        "screener_rows": len(screener_dps),
        "filing_rows": len(filing_dps),
        "discrepancies": len(discrepancies),
    }
    print(json_summary(summary))
    return summary


def json_summary(s: dict) -> str:
    return (
        f"company_id    : {s.get('company_id', 'infy_infy')}\n"
        f"screener rows : {s['screener_rows']}\n"
        f"filing rows   : {s['filing_rows']}\n"
        f"discrepancies : {s['discrepancies']}"
    )


if __name__ == "__main__":
    run()
