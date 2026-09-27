from __future__ import annotations

"""
BSE (Bombay Stock Exchange) filing ingestion module.

Parses annual report PDFs or XBRL filings from BSE for Indian-listed companies.
Currently a **stub** — returns empty results. Implement when BSE data format
is available.

Priority for Indian companies (highest → lowest):
    1. nse_filing  — NSE annual report PDFs (audited, internally consistent)
    2. bse_filing  — BSE annual report PDFs (audited, same data as NSE for most companies)
    3. screener    — Screener.in third-party aggregation (may differ from filings)
    4. yfinance_live — Real-time market data (limited financial statement detail)

Companies currently relying on secondary sources (screener/yfinance only):
    - hcltech_hcltech, lt_lt, tcs_tcs, tatamotors_tatamotors, tatasteel_tatamotors
      (screener only — no NSE/BSE filing)
    - reliance_reliance, itc_itc, bhartiartl_bhartiartl, ongc_ongc, maruti_maruti,
      hindunilvr_hindunilvr, tatapower_tatapower, kaynes_kaynes, idea_idea, tsm_tsm
      (yfinance_live only — limited statement detail)

To add BSE filing support:
    1. Place company annual report PDFs in backend/data/filings/{company_id}/
    2. Implement parse_bse_filing() below using pdfplumber (like pdf_tables.py)
    3. Add source="bse_filing" to the RawDatapoint records
    4. The selector will automatically prioritize bse_filing over screener/yfinance
"""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import List

from backend.data.store import RawDatapoint, Source, Status

logger = logging.getLogger(__name__)


def _datapoint_id(company_id: str, metric: str, period: str, source: str, section: str, page: int) -> str:
    return hashlib.sha1(f"{company_id}|{section}|{metric}|{period}|{source}|{page}".encode()).hexdigest()


def parse_bse_filing(
    pdf_path: Path,
    company_id: str,
    section: str,
    source: Source = "bse_filing",
) -> List[RawDatapoint]:
    """Parse a BSE annual report PDF into RawDatapoint records.

    ** Stub ** — currently returns an empty list. The BSE filing format
    uses the same annual report PDFs as NSE (both exchanges receive the
    same company filings). Implementation should follow the same pattern
    as ``backend.data.parsers.pdf_tables.parse_predicted_statement_page``.

    Args:
        pdf_path: Path to the BSE annual report PDF.
        company_id: Company identifier (e.g. "reliance_reliance").
        section: Financial statement section ("BALANCE SHEET", "PROFIT & LOSS", "CASH FLOW").
        source: Source tag for provenance tracking.

    Returns:
        Empty list (stub). When implemented, returns list of RawDatapoint
        records with source="bse_filing" and provenance tagging.
    """
    logger.info("BSE filing stub: %s section=%s (no parser implemented yet)", pdf_path.name, section)
    # Not yet implemented, and deliberately returning empty rather than guessing.
    #
    # The BSE annual report PDFs use the same table structure as the NSE filings,
    # so the parser is pdf_tables.parse_predicted_statement_page() with the page
    # numbers for each company's annual report. Until that exists this returns
    # nothing, which is safe: the source selector treats a source that yields no
    # datapoints as absent and falls through to the next one, rather than
    # recording a filing it did not actually read.
    return []


def parse_bse_company_filings(
    company_id: str,
    filings_dir: Path,
) -> List[RawDatapoint]:
    """Scan a company's filings directory for BSE annual reports and parse them.

    ** Stub ** — returns empty list. When implemented, scans for PDF files
    in ``filings_dir`` and calls ``parse_bse_filing()`` for each section.

    Args:
        company_id: Company identifier.
        filings_dir: Directory containing BSE filing PDFs.

    Returns:
        Empty list (stub).
    """
    if not filings_dir.exists():
        return []

    pdf_files = sorted(filings_dir.glob("*.pdf"))
    if not pdf_files:
        return []

    logger.info("BSE stub: found %d PDFs for %s — no parser implemented yet", len(pdf_files), company_id)
    # A parser would, for each PDF, determine the fiscal year and read three
    # sections: BALANCE SHEET, PROFIT & LOSS (annual only) and CASH FLOW, through
    # parse_bse_filing() or pdf_tables.parse_predicted_statement_page().
    #
    # Discovering the PDFs without being able to read them is not progress, so
    # this returns empty and the log line above is the only trace. See the note
    # in parse_bse_filing() for why empty is the safe answer here.
    return []
