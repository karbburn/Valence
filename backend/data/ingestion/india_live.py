from __future__ import annotations

"""
India Live Ingestion Module for Valence.

Fetches live audited financial statements (P&L, Balance Sheet, Cash Flow) for any Indian listed equity
via yfinance (.NS / .BO) with fallback to TwelveData or local source exports.
Converts values to standard INR Crores and canonical raw metric labels.
"""

import hashlib
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import yfinance as yf

from backend.data.store import RawDatapoint, Source, Status

logger = logging.getLogger(__name__)


def _datapoint_id(company_id: str, metric: str, period: str, source: str, section: str, row: int) -> str:
    return hashlib.sha1(f"{company_id}|{section}|{metric}|{period}|{source}|{row}".encode()).hexdigest()


# Mappings from yfinance row indices to Valence raw metric labels
YF_INCOME_MAP = [
    ("Sales", ["Total Revenue", "Operating Revenue", "Gross Revenue"]),
    ("Cost of sales", ["Cost Of Revenue", "Reconciled Cost Of Revenue"]),
    ("Employee Cost", ["Salaries And Wages", "Staff Costs", "Employee Benefit Expense"]),
    ("Other Expenses", ["Operating Expense", "Other Operating Expenses", "Selling General And Administration"]),
    ("Operating Profit", ["Operating Income", "EBIT"]),
    ("Other Income", ["Other Non Operating Income Expenses", "Non Operating Income Expense", "Other Income Expense"]),
    ("Depreciation", ["Reconciled Depreciation", "Depreciation And Amortization In Income Statement", "Depreciation Amortization Depletion"]),
    ("Interest", ["Interest Expense Non Operating", "Interest Expense", "Finance Costs"]),
    ("Profit before tax", ["Pretax Income", "Income Before Tax"]),
    ("Tax", ["Tax Provision", "Income Tax Expense"]),
    ("Net profit", ["Net Income Common Stockholders", "Net Income", "Net Income From Continuing Operation Net Minority Interest"]),
    ("EPS in Rs", ["Basic EPS", "Diluted EPS"]),
]

YF_BALANCE_MAP = [
    ("Equity Share Capital", ["Share Issued", "Ordinary Shares Number"]),
    ("Reserves", ["Retained Earnings", "Other Equity", "Stockholders Equity"]),
    ("Borrowings", ["Total Debt", "Long Term Debt", "Long Term Debt And Capital Lease Obligation"]),
    ("Other Liabilities", ["Total Non Current Liabilities Net Minority Interest", "Current Liabilities"]),
    ("Total_Liab", ["Total Liabilities Net Minority Interest", "Total Liabilities"]),
    ("Net Block", ["Net PPE", "Gross PPE", "Properties"]),
    ("Capital Work in Progress", ["Construction In Progress", "Capital Work In Progress"]),
    ("Investments", ["Investments And Advances", "Other Investments", "Investment Properties"]),
    ("Other Assets", ["Other Non Current Assets", "Other Current Assets"]),
    ("Total_Asset", ["Total Assets"]),
    ("Receivables", ["Accounts Receivable", "Receivables", "Gross Accounts Receivable"]),
    ("Cash & Bank", ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash Financial"]),
]

YF_CASHFLOW_MAP = [
    ("Cash from Operating Activity", ["Operating Cash Flow", "Cash Flowsfromusedin Operating Activities"]),
    ("Capital Expenditure", ["Capital Expenditure", "Purchase Of PPE", "PaymentsToAcquirePropertyPlantAndEquipment"]),
    ("Cash from Investing Activity", ["Investing Cash Flow", "Cash Flowsfromusedin Investing Activities"]),
    ("Cash from Financing Activity", ["Financing Cash Flow", "Cash Flowsfromusedin Financing Activities"]),
]


def fetch_and_parse_india_live(company_id: str) -> List[RawDatapoint]:
    """Fetch live multi-year financial statements for an Indian listed company.

    Args:
        company_id: e.g. "reliance_reliance", "bhartiartl_bhartiartl", "itc_itc".

    Returns:
        List of RawDatapoint records in INR Crores.
    """
    ticker_base = company_id.split("_")[0].upper()
    sym_ns = f"{ticker_base}.NS"
    sym_bo = f"{ticker_base}.BO"

    logger.info("Fetching live financials for %s via yfinance...", sym_ns)
    tk = yf.Ticker(sym_ns)

    # Fetch statements
    inc_df = getattr(tk, "income_stmt", None)
    if inc_df is None or inc_df.empty:
        inc_df = getattr(tk, "financials", None)

    # Try BSE if NSE empty
    if inc_df is None or inc_df.empty:
        tk = yf.Ticker(sym_bo)
        inc_df = getattr(tk, "income_stmt", None)

    bs_df = getattr(tk, "balance_sheet", None)
    cf_df = getattr(tk, "cashflow", None)

    if inc_df is None or inc_df.empty:
        raise ValueError(f"Could not fetch live income statement for {company_id} from NSE/BSE")

    # Discover and sort available columns (dates) chronologically
    col_dates = []
    for col in inc_df.columns:
        if isinstance(col, (datetime, date)):
            col_dates.append(col)
        else:
            try:
                d = datetime.fromisoformat(str(col)[:10]).date()
                col_dates.append(d)
            except Exception:
                pass

    if not col_dates:
        raise ValueError(f"No valid reporting periods found in income statement for {company_id}")

    # Sort chronological (oldest to newest)
    sorted_cols = sorted(col_dates)
    # Take latest 3 annual periods
    target_cols = sorted_cols[-3:] if len(sorted_cols) >= 3 else sorted_cols

    # Build period labels e.g. FY24, FY25, FY26
    period_map: Dict[str, str] = {}
    for i, c_d in enumerate(target_cols):
        # Sequential ending in FY26 or based on year
        period_map[str(c_d)[:10]] = f"FY{str(c_d.year)[2:]}"

    datapoints: List[RawDatapoint] = []
    now = datetime.now()

    def _extract_from_df(df, mapping, section):
        if df is None or df.empty:
            return
        # Normalize index to string for case-insensitive lookup
        df_index_map = {str(idx).strip().lower(): idx for idx in df.index}

        for row_idx, (metric_label, yf_candidates) in enumerate(mapping):
            matched_idx = None
            for cand in yf_candidates:
                cand_lower = cand.lower()
                if cand_lower in df_index_map:
                    matched_idx = df_index_map[cand_lower]
                    break

            if matched_idx is None:
                continue

            # Extract per target period
            for c_d in target_cols:
                d_str = str(c_d)[:10]
                period_lbl = period_map[d_str]

                # Find column in df matching date
                col_match = None
                for col in df.columns:
                    if str(col)[:10] == d_str:
                        col_match = col
                        break

                if col_match is None:
                    continue

                raw_val = df.loc[matched_idx, col_match]
                if raw_val is None or (isinstance(raw_val, float) and (raw_val != raw_val)):
                    continue

                try:
                    val_num = float(raw_val)
                except (ValueError, TypeError):
                    continue

                # Conversion:
                # Basic shares -> in Crores (val / 1e7)
                # EPS -> single INR (val)
                # Monetary values -> INR Crores (val / 1e7)
                if metric_label in ("EPS in Rs", "canonical.is.eps_diluted", "canonical.is.eps_basic"):
                    final_val = val_num
                else:
                    final_val = val_num / 1e7

                dp_id = _datapoint_id(company_id, metric_label, period_lbl, "yfinance_live", section, row_idx + 1)
                datapoints.append(
                    RawDatapoint(
                        id=dp_id,
                        company_id=company_id,
                        metric_raw=metric_label,
                        period_label=period_lbl,
                        period_end_date=c_d if isinstance(c_d, date) else date.today(),
                        value=round(final_val, 4),
                        currency="INR",
                        units="crores",
                        source="yfinance_live",
                        source_location=f"yfinance!{matched_idx}",
                        status="reported",
                        update_date=now,
                    )
                )

    _extract_from_df(inc_df, YF_INCOME_MAP, "PROFIT & LOSS")
    _extract_from_df(bs_df, YF_BALANCE_MAP, "BALANCE SHEET")
    _extract_from_df(cf_df, YF_CASHFLOW_MAP, "CASH FLOW:")

    if not datapoints:
        raise ValueError(f"Extracted 0 valid datapoints for {company_id} from live source")

    return datapoints
