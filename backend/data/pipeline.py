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
