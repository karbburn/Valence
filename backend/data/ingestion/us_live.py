from __future__ import annotations

"""
US Live Ingestion Module for Valence.

Fallback source for US-listed companies that do not file US-GAAP XBRL with SEC
EDGAR (foreign private issuers such as TSM, ASML, NIO). Fetches multi-year
audited financial statements via yfinance and emits RawDatapoints using the
same raw metric labels and USD/millions units as the SEC EDGAR pipeline, so
taxonomy normalization maps them identically.
"""

import hashlib
import logging
from datetime import date, datetime
from typing import Dict, List

import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import yfinance as yf

from backend.data.errors import NoFinancialsAvailable
from backend.data.store import RawDatapoint

logger = logging.getLogger(__name__)


def _datapoint_id(company_id: str, metric: str, period: str, source: str, section: str, row: int) -> str:
    return hashlib.sha1(f"{company_id}|{section}|{metric}|{period}|{source}|{row}".encode()).hexdigest()


# Raw labels match sec_edgar US_GAAP_TAG_MAP so taxonomy mapping is identical.
YF_INCOME_MAP = [
    ("Revenues", ["Total Revenue", "Operating Revenue", "Gross Revenue"]),
    ("Cost of sales", ["Cost Of Revenue", "Reconciled Cost Of Revenue", "Cost Of Goods Sold"]),
    ("Operating profit", ["Operating Income", "EBIT", "Operating Income Loss"]),
    ("Other Income", ["Other Non Operating Income Expenses", "Non Operating Income Expense", "Other Income Expense"]),
    ("Depreciation", ["Reconciled Depreciation", "Depreciation And Amortization In Income Statement", "Depreciation Amortization Depletion"]),
    ("Finance cost", ["Interest Expense Non Operating", "Interest Expense", "Finance Costs"]),
    ("Profit before tax", ["Pretax Income", "Income Before Tax"]),
    ("Tax", ["Tax Provision", "Income Tax Expense"]),
    ("Net Profit", ["Net Income Common Stockholders", "Net Income", "Net Income From Continuing Operation Net Minority Interest"]),
    # Basic and diluted EPS are distinct canonical keys. Collapsing them made
    # the share-count schedule derive its "diluted" count from a basic figure.
    ("Basic (₹)", ["Basic EPS"]),
    ("Diluted (₹)", ["Diluted EPS"]),
]

YF_BALANCE_MAP = [
    ("Net Block", ["Net PPE", "Gross PPE", "Properties"]),
    ("Current investments", ["Investments And Advances", "Other Investments", "Investment Properties", "Marketable Securities"]),
    ("Trade receivables", ["Accounts Receivable", "Receivables", "Gross Accounts Receivable"]),
    ("Inventory", ["Inventory", "Inventory Net"]),
    # Accounts payable is an operating working-capital line the forecast needs
    # to resolve DPO. Without it every yfinance-sourced US filer had the driver
    # invented, and the invented payable balance booked a phantom first-year
    # working-capital inflow.
    ("Trade payables", ["Accounts Payable", "Accounts Payable Current", "Trade Payables"]),
    ("Prepayments and other assets", ["Other Non Current Assets", "Other Current Assets", "Prepaid Expense"]),
    ("Total current assets", ["Total Current Assets"]),
    ("Cash & Bank", ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash Financial"]),
    ("Total assets", ["Total Assets"]),
    # Long-term borrowings only; short-term debt is mapped separately so current
    # maturities are not silently excluded from the EV -> equity bridge.
    ("Borrowings", ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"]),
    ("Short term borrowings", ["Current Debt", "Current Debt And Capital Lease Obligation", "Other Current Borrowings"]),
    ("Finance lease liabilities", ["Finance Lease", "Capital Lease Obligation"]),
    ("Operating lease liabilities", ["Operating Lease Liability", "Capital Lease Obligation"]),
    ("Total current liabilities", ["Total Current Liabilities"]),
    ("Total liabilities", ["Total Liabilities Net Minority Interest", "Total Liabilities"]),
    ("Total equity", ["Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"]),
    ("Minority interest", ["Minority Interest", "Minority Interest And Other Voting Interest"]),
]

YF_CASHFLOW_MAP = [
    ("Cash from Operating Activity", ["Operating Cash Flow", "Cash Flowsfromusedin Operating Activities"]),
    ("PaymentsToAcquirePropertyPlantAndEquipment", ["Capital Expenditure", "Purchase Of PPE", "PaymentsToAcquirePropertyPlantAndEquipment"]),
    ("Cash from Investing Activity", ["Investing Cash Flow", "Cash Flowsfromusedin Investing Activities"]),
    ("Cash from Financing Activity", ["Financing Cash Flow", "Cash Flowsfromusedin Financing Activities"]),
    ("Stock Based Compensation", ["Stock Based Compensation", "Share Based Compensation"]),
    # Reported dividends. Without this line the payout ratio is unresolvable and
    # the model books a dividend against a company that pays none.
    ("Dividend Amount", ["Cash Dividends Paid", "Common Stock Dividend Paid"]),
]

YF_SHARE_MAP = [
    ("Basic (in shares)", ["Ordinary Shares Number", "Share Issued", "Weighted Average Shares Diluted"]),
]


def _fx_to_usd(financial_currency: str | None) -> float:
    """Return the rate to convert a financial_currency unit to USD (USD per unit).

    Raises ValueError when the FX rate cannot be resolved for a non-USD currency,
    so callers can fall back to local source files instead of silently corrupting
    valuations with wrong-currency data.
    """
    if not financial_currency or financial_currency.upper() == "USD":
        return 1.0
    pair = f"{financial_currency}=X"
    try:
        fx_tk = yf.Ticker(pair)
        rate = float(fx_tk.fast_info["last_price"])
        if rate and rate > 0:
            return rate
    except Exception as e:
        logger.warning("Could not fetch FX rate for %s: %s", pair, e)
    raise ValueError(
        f"Cannot resolve FX rate for {financial_currency} → USD. "
        f"Falling back to local source files."
    )


def fetch_and_parse_us_live(company_id: str) -> List[RawDatapoint]:
    """Fetch live multi-year financial statements for a US-listed company via yfinance.

    Args:
        company_id: e.g. "tsm_us", "asml_us". Ticker is the prefix before "_us".

    Returns:
        List of RawDatapoint records in USD millions / shares in millions.
    """
    ticker = company_id.split("_")[0].upper()
    logger.info("Fetching live financials for %s via yfinance...", ticker)
    tk = yf.Ticker(ticker)

    inc_df = getattr(tk, "income_stmt", None)
    if inc_df is None or inc_df.empty:
        inc_df = getattr(tk, "financials", None)
    bs_df = getattr(tk, "balance_sheet", None)
    cf_df = getattr(tk, "cashflow", None)

    if inc_df is None or inc_df.empty:
        raise NoFinancialsAvailable(f"Could not fetch live income statement for {company_id} via yfinance")

    # yfinance reports statements in the company's reporting currency; convert
    # to USD so valuation units match the USD market price.
    financial_currency = ""
    try:
        info = tk.info or {}
        financial_currency = info.get("financialCurrency") or ""
    except Exception:
        pass
    fx = _fx_to_usd(financial_currency)

    col_dates = []
    for col in inc_df.columns:
        if isinstance(col, (datetime, date)):
            col_dates.append(col)
        else:
            try:
                col_dates.append(datetime.fromisoformat(str(col)[:10]).date())
            except Exception:
                pass

    if not col_dates:
        raise NoFinancialsAvailable(f"No valid reporting periods found for {company_id}")

    sorted_cols = sorted(col_dates)
    target_cols = sorted_cols[-3:] if len(sorted_cols) >= 3 else sorted_cols

    period_map: Dict[str, str] = {}
    for c_d in target_cols:
        period_map[str(c_d)[:10]] = f"FY{str(c_d.year)[2:]}"

    datapoints: List[RawDatapoint] = []
    now = datetime.now()

    def _extract_from_df(df, mapping, section):
        if df is None or df.empty:
            return
        df_index_map = {str(idx).strip().lower(): idx for idx in df.index}

        for row_idx, (metric_label, yf_candidates) in enumerate(mapping):
            matched_idx = None
            for cand in yf_candidates:
                if cand.lower() in df_index_map:
                    matched_idx = df_index_map[cand.lower()]
                    break
            if matched_idx is None:
                continue

            for c_d in target_cols:
                d_str = str(c_d)[:10]
                period_lbl = period_map[d_str]

                col_match = None
                for col in df.columns:
                    if str(col)[:10] == d_str:
                        col_match = col
                        break
                if col_match is None:
                    continue

                raw_val = df.loc[matched_idx, col_match]
                if raw_val is None or (isinstance(raw_val, float) and raw_val != raw_val):
                    continue
                try:
                    val_num = float(raw_val)
                except (ValueError, TypeError):
                    continue

                if metric_label == "Basic (in shares)":
                    final_val = val_num / 1e6
                else:
                    final_val = val_num / 1e6 / fx

                dp_id = _datapoint_id(company_id, metric_label, period_lbl, "yfinance_live", section, row_idx + 1)
                datapoints.append(
                    RawDatapoint(
                        id=dp_id,
                        company_id=company_id,
                        metric_raw=metric_label,
                        period_label=period_lbl,
                        period_end_date=c_d if isinstance(c_d, date) else date.today(),
                        value=round(final_val, 4),
                        currency="USD",
                        units="millions",
                        source="yfinance_live",
                        source_location=f"yfinance!{matched_idx}",
                        status="reported",
                        update_date=now,
                    )
                )

    _extract_from_df(inc_df, YF_INCOME_MAP, "PROFIT & LOSS")
    _extract_from_df(bs_df, YF_BALANCE_MAP, "BALANCE SHEET")
    _extract_from_df(cf_df, YF_CASHFLOW_MAP, "CASH FLOW:")
    _extract_from_df(inc_df, YF_SHARE_MAP, "PROFIT & LOSS")

    if not datapoints:
        raise NoFinancialsAvailable(f"Extracted 0 valid datapoints for {company_id} from yfinance live source")

    return datapoints