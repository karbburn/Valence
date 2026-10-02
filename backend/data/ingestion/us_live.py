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
from backend.data.ingestion.feed_borrowings import (
    index_rows as fb_index_rows,
    resolve_borrowings as fb_resolve_borrowings,
)
from backend.data.store import RawDatapoint

logger = logging.getLogger(__name__)


def filed_period_ends(company_id: str) -> Dict[str, date]:
    """The period-end date each period ACTUALLY has, according to the filing.

    A period is a span of time with one end. Yahoo names its columns by the last day
    of the calendar month, so a filer whose fiscal year ends on its own 52/53-week
    date gets a month end from the feed:

        intc_us   FY24  filed 2024-12-28   feed 2024-12-31
        nvda_us   FY24  filed 2024-01-28   feed 2024-01-31
        qcom_us   FY25  filed 2025-09-28   feed 2025-09-30

    and for two filers the two dates fall in DIFFERENT MONTHS, so this is not a
    rounding difference:

        sbux_us   FY23  filed 2023-10-01   feed 2023-09-30
        tjx_us    FY24  filed 2024-02-03   feed 2024-01-31

    Storing the feed's date put two different period ends for the same period into one
    statement -- 47 such periods across 18 of the shipped US models. The filing is the
    authority on when its own period ended, so its date wins and the feed supplies the
    figure only.

    Read from the store rather than recomputed, because the SEC reader already parsed
    the filed statements and `batch` ingests them before this module runs. A period the
    filing says nothing about is absent here, and the caller keeps the feed's date --
    which is then the only date for that period, so there is nothing to disagree with.
    """
    from backend.data.universe.store import DB_PATH

    if not DB_PATH.exists():
        return {}
    import sqlite3

    try:
        conn = sqlite3.connect("file:%s?mode=ro" % DB_PATH.as_posix(), uri=True)
    except sqlite3.Error as exc:  # noqa: PERF203
        logger.warning("could not read filed period ends for %s: %s", company_id, exc)
        return {}

    counts: Dict[str, Dict[date, int]] = {}
    try:
        for period_label, ped in conn.execute(
            "SELECT period_label, period_end_date FROM raw_datapoints "
            "WHERE company_id = ? AND source = 'sec_edgar'",
            (company_id,),
        ):
            try:
                parsed = date.fromisoformat(str(ped)[:10])
            except ValueError:
                continue
            counts.setdefault(period_label, {})
            counts[period_label][parsed] = counts[period_label].get(parsed, 0) + 1
    except sqlite3.Error as exc:
        logger.warning("could not read filed period ends for %s: %s", company_id, exc)
        return {}
    finally:
        conn.close()

    # The most frequent filed date wins, so one odd row cannot move a period.
    return {
        label: max(dates.items(), key=lambda kv: (kv[1], -kv[0].toordinal()))[0]
        for label, dates in counts.items()
        if dates
    }


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
    # Long-term borrowings and short-term debt are resolved separately rather than
    # through this map, because the feed bundles leases into them and the lease has
    # to be taken back out. See _extract_borrowings.
    #
    # No lease line is mapped from the feed, in either direction. The feed cannot
    # distinguish a capital lease from an operating one: Meta's feed carries 28,654
    # of "Capital Lease Obligations" against a filed 1,184 of finance leases, and
    # Ambarella's 13,435 against a filed 13,435 of operating lease liability, while
    # its "Leases" row is 8,464 and 2,560 respectively and matches neither. A row
    # that cannot be placed cannot be asserted, and asserting it either way puts an
    # obligation the valuation deducts, or a figure the reader is invited to apply,
    # on no evidence at all. Lease balances come from the filing.
    #
    # The consequence is stated rather than hidden: a filer whose lease balance is
    # only available from this feed shows none. That is the safe direction, because
    # the balance is a disclosure shown beside the debt and not part of it.
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

    # The filing's own end date for each period, where it has filed one.
    #
    # `period_map` still keys on the feed's date string -- that is how a feed column is
    # matched to a period -- but the date STORED is the filed one. The two jobs are
    # separate and conflating them is what put 2024-01-31 next to NVIDIA's filed
    # 2024-01-28 in the same statement.
    filed_ends = filed_period_ends(company_id)
    if filed_ends:
        logger.info(
            "%s: %d of %d periods take their end date from the filing",
            company_id,
            len([p for p in period_map.values() if p in filed_ends]),
            len(period_map),
        )

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
                        # The filing's end date for this period, where there is one.
                        # See `filed_period_ends`: a period has one end, and the filer
                        # is the authority on its own. Without this the same statement
                        # carries NVIDIA's filed 2024-01-28 and Yahoo's 2024-01-31.
                        period_end_date=filed_ends.get(
                            period_lbl, c_d if isinstance(c_d, date) else date.today()
                        ),
                        value=round(final_val, 4),
                        currency="USD",
                        units="millions",
                        source="yfinance_live",
                        source_location=f"yfinance!{matched_idx}",
                        status="reported",
                        update_date=now,
                    )
                )

    def _extract_borrowings(df):
        """Borrowings from the feed, with any bundled lease obligation removed."""
        if df is None or df.empty:
            return
        rows = fb_index_rows(df.index)

        for c_d in target_cols:
            d_str = str(c_d)[:10]
            period_lbl = period_map.get(d_str)
            if period_lbl is None:
                continue
            col_match = next((c for c in df.columns if str(c)[:10] == d_str), None)
            if col_match is None:
                continue

            for row_idx, (metric_label, matched_row, value) in enumerate(
                fb_resolve_borrowings(rows, lambda idx: df.loc[idx, col_match])
            ):
                dp_id = _datapoint_id(
                    company_id, metric_label, period_lbl, "yfinance_live",
                    "BALANCE SHEET", row_idx + 1,
                )
                datapoints.append(
                    RawDatapoint(
                        id=dp_id,
                        company_id=company_id,
                        metric_raw=metric_label,
                        period_label=period_lbl,
                        # The filing's end date for this period, where there is one.
                        # See `filed_period_ends`: a period has one end, and the filer
                        # is the authority on its own. Without this the same statement
                        # carries NVIDIA's filed 2024-01-28 and Yahoo's 2024-01-31.
                        period_end_date=filed_ends.get(
                            period_lbl, c_d if isinstance(c_d, date) else date.today()
                        ),
                        value=round(value / 1e6 / fx, 4),
                        currency="USD",
                        units="millions",
                        source="yfinance_live",
                        source_location=f"yfinance!{matched_row}",
                        status="reported",
                        update_date=now,
                    )
                )

    _extract_borrowings(bs_df)

    _extract_from_df(inc_df, YF_INCOME_MAP, "PROFIT & LOSS")
    _extract_from_df(bs_df, YF_BALANCE_MAP, "BALANCE SHEET")
    _extract_from_df(cf_df, YF_CASHFLOW_MAP, "CASH FLOW:")
    _extract_from_df(inc_df, YF_SHARE_MAP, "PROFIT & LOSS")

    if not datapoints:
        raise NoFinancialsAvailable(f"Extracted 0 valid datapoints for {company_id} from yfinance live source")

    return datapoints