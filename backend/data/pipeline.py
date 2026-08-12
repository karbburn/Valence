from __future__ import annotations

from pathlib import Path

from backend.data.ingestion.screener import parse_screener_export
from backend.data.parsers.pdf_tables import parse_predicted_statement_page
from backend.data.reconciliation import reconcile
from backend.data.store import save_datapoints

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "valence.db"
SOURCES = HERE / "sources"
FILINGS = HERE / "filings"
LOG_PATH = HERE / "discrepancy_log.json"

SCREENER_XLSX = SOURCES / "Infosys.xlsx"
FY26_PDF = FILINGS / "infosys-fy26-q4-outcome.pdf"
FY25_PDF = FILINGS / "infosys-fy25-q4-outcome.pdf"


def run() -> dict:
    # Idempotent: start from a clean store each run.
    if DB_PATH.exists():
        DB_PATH.unlink()

    # Phase 1.2 + 1.4: parse both sources (annual columns only from PDFs).
    screener_dps = parse_screener_export(SCREENER_XLSX)

    fy26 = [
        parse_predicted_statement_page(FY26_PDF, 99, "BALANCE SHEET", "nse_filing", annual_only=False),
        parse_predicted_statement_page(FY26_PDF, 100, "PROFIT & LOSS", "nse_filing", annual_only=True),
        parse_predicted_statement_page(FY26_PDF, 103, "CASH FLOW", "nse_filing", annual_only=False),
    ]
    fy25 = [
        parse_predicted_statement_page(FY25_PDF, 105, "BALANCE SHEET", "nse_filing", annual_only=False),
        parse_predicted_statement_page(FY25_PDF, 106, "PROFIT & LOSS", "nse_filing", annual_only=True),
        parse_predicted_statement_page(FY25_PDF, 109, "CASH FLOW", "nse_filing", annual_only=False),
    ]
    filing_dps = [d for page in (fy26 + fy25) for d in page]

    # Phase 1.1: persist everything (both sources retained).
    save_datapoints(DB_PATH, screener_dps + filing_dps)

    # Phase 1.6: reconcile, emit discrepancy log, tag superseded rows.
    discrepancies = reconcile(DB_PATH, LOG_PATH)

    summary = {
        "screener_rows": len(screener_dps),
        "filing_rows": len(filing_dps),
        "discrepancies": len(discrepancies),
    }
    print(json_summary(summary))
    return summary


def json_summary(s: dict) -> str:
    return (
        f"screener rows : {s['screener_rows']}\n"
        f"filing rows   : {s['filing_rows']}\n"
        f"discrepancies : {s['discrepancies']}"
    )


if __name__ == "__main__":
    run()
