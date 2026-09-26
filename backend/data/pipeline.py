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


def _get_secondary_filing_datapoints(company_id: str) -> list[RawDatapoint]:
    """Dynamically scan and parse secondary PDF filings for company_id if present."""
    filing_dps: list[RawDatapoint] = []

    # Check company-specific filings directory or legacy Infosys files
    company_filings_dir = FILINGS / company_id
    if company_filings_dir.exists() and company_filings_dir.is_dir():
        pdf_files = sorted(company_filings_dir.glob("*.pdf"))
        for pdf in pdf_files:
            try:
                page_dps = parse_predicted_statement_page(
                    pdf, 99, "BALANCE SHEET", "nse_filing", annual_only=False, company_id=company_id
                )
                filing_dps.extend(page_dps)
            except Exception:
                pass

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
