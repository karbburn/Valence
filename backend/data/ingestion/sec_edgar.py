from __future__ import annotations

"""
SEC EDGAR structured data ingestion module.

Fetches live XBRL company facts from SEC EDGAR API (data.sec.gov) or parses
offline synthetic export files, returning provenance-tagged RawDatapoint records
for US-listed filers.

Supports direct US GAAP Capex mapping (`PaymentsToAcquirePropertyPlantAndEquipment`)
replacing investing cash flow proxies.

Design decision — single-source by design:
    SEC EDGAR company facts are structured XBRL, machine-generated, and
    authoritative by definition. Reconciling EDGAR against a second source is
    intentionally omitted here. The Source literal "sec_edgar" identifies
    EDGAR-sourced records throughout the pipeline.
"""

import hashlib
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl
import requests

from backend.data.store import RawDatapoint, Source, Status

logger = logging.getLogger(__name__)

SEC_HEADERS = {
    "User-Agent": "ValencePlatform team@valence.com",
    "Accept-Encoding": "gzip, deflate",
}

# Known CIK lookup table
CIK_REGISTRY: Dict[str, str] = {
    "aapl_us": "0000320193",
    "msft_us": "0000789019",
    "infy_us": "0001065280",
}


def _datapoint_id(company_id: str, metric: str, period: str, source: str, section: str, row: int) -> str:
    return hashlib.sha1(f"{company_id}|{section}|{metric}|{period}|{source}|{row}".encode()).hexdigest()


def _clean(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, float):
        return v
    s = str(v).replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _period_label(d: date) -> str:
    return f"FY{str(d.year)[2:]}"


# US GAAP XBRL Concept Tag Mappings to Raw Metric Labels
US_GAAP_TAG_MAP: List[Tuple[str, List[str], str]] = [
    # (Raw Metric Label, [XBRL Tags in priority order], Section)
    ("Revenues", [
        "Revenues", 
        "RevenueFromContractWithCustomerExcludingAssessedTax", 
        "SalesRevenueNet", 
        "OperatingRevenue", 
        "TotalRevenueNet", 
        "TotalRevenuesAndOtherIncome"
    ], "PROFIT & LOSS"),
    ("Cost of sales", [
        "CostOfGoodsAndServicesSold", 
        "CostOfRevenue", 
        "CostOfGoodsSold"
    ], "PROFIT & LOSS"),
    ("Gross profit", ["GrossProfit"], "PROFIT & LOSS"),
    ("Total operating expenses", ["OperatingExpenses"], "PROFIT & LOSS"),
    ("Operating profit", ["OperatingIncomeLoss", "OperatingProfit", "IncomeLossFromOperations"], "PROFIT & LOSS"),
    ("Depreciation", [
        "DepreciationDepletionAndAmortization", 
        "DepreciationAndAmortization",
        "Depreciation"
    ], "PROFIT & LOSS"),
    ("Finance cost", ["InterestExpense", "InterestAndDebtExpense"], "PROFIT & LOSS"),
    ("Other Income", ["NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense"], "PROFIT & LOSS"),
    ("Profit before tax", [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeTaxes",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
    ], "PROFIT & LOSS"),
    ("Tax", ["IncomeTaxExpenseBenefit", "IncomeTaxesPaidNet"], "PROFIT & LOSS"),
    ("Net Profit", [
        "NetIncomeLoss", 
        "ProfitLoss", 
        "NetIncomeLossAvailableToCommonStockholdersBasic"
    ], "PROFIT & LOSS"),
    ("Net Block", [
        "PropertyPlantAndEquipmentNet", 
        "PropertyPlantAndEquipmentGross"
    ], "BALANCE SHEET"),
    ("Cash & Bank", [
        "CashAndCashEquivalentsAtCarryingValue", 
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashAndShortTermInvestments"
    ], "BALANCE SHEET"),
    ("Current investments", [
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesCurrent",
        "ShortTermInvestments"
    ], "BALANCE SHEET"),
    ("Inventory", [
        "InventoryNet",
        "InventoryGross",
        "InventoryFinishedGoods"
    ], "BALANCE SHEET"),
    ("Trade receivables", [
        "AccountsReceivableNetCurrent", 
        "ReceivablesNetCurrent"
    ], "BALANCE SHEET"),
    ("Prepayments and other assets", ["PrepaidExpenseAndOtherAssetsCurrent", "PrepaidExpenseCurrent"], "BALANCE SHEET"),
    ("Total current assets", ["AssetsCurrent"], "BALANCE SHEET"),
    ("Total assets", ["Assets"], "BALANCE SHEET"),
    # DEBT — three separate lines, because one line cannot carry a debt stack.
    #
    # A single "Borrowings" tag chosen by preference silently drops most of what
    # a company owes. `LongTermDebtNoncurrent` excludes the current portion of
    # long-term debt, and neither finance nor operating lease liabilities are
    # debt tags at all, so an EV -> equity bridge built on it deducted a fraction
    # of the real obligation: Apple was short by 12,350 of current maturities,
    # Microsoft by 16,532 of operating leases, Amazon by 3,203, and one large
    # filer's borrowings resolved to nothing at all. Every per-share figure and
    # every EV multiple built on that bridge was overstated.
    #
    # Long-term = the non-current measure. Current = everything due within a
    # year, including the current portion of long-term debt. Together they are
    # total borrowings, and the two never double-count because the non-current
    # tag by construction excludes the current slice.
    ("Borrowings", [
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebt",
    ], "BALANCE SHEET"),
    ("Short term borrowings", [
        "LongTermDebtCurrent",
        "DebtCurrent",
        "ShortTermBorrowings",
        "OtherShortTermBorrowings",
        "ShortTermBankLoansAndNotesPayable",
    ], "BALANCE SHEET"),
    ("Finance lease liabilities", [
        "FinanceLeaseLiability",
        "FinanceLeaseLiabilityNoncurrent",
        "CapitalLeaseObligations",
    ], "BALANCE SHEET"),
    # Operating leases are shown, not deducted: they are an operating cost in
    # EBIT under US GAAP, so including them in net debt alongside a post-rent
    # EBIT would double-count. Making the balance visible lets a reader apply
    # the other convention without the platform hiding it.
    ("Operating lease liabilities", [
        "OperatingLeaseLiability",
        "OperatingLeaseLiabilityNoncurrent",
    ], "BALANCE SHEET"),
    ("Total current liabilities", ["LiabilitiesCurrent"], "BALANCE SHEET"),
    ("Total liabilities", ["Liabilities"], "BALANCE SHEET"),
    ("Total equity", ["StockholdersEquity", "CommonStockValue"], "BALANCE SHEET"),
    ("Cash from Operating Activity", [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"
    ], "CASH FLOW:"),
    ("Cash from Investing Activity", [
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"
    ], "CASH FLOW:"),
    ("Cash from Financing Activity", [
        "NetCashProvidedByUsedInFinancingActivities",
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"
    ], "CASH FLOW:"),
    ("PaymentsToAcquirePropertyPlantAndEquipment", [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquirePropertyPlantEquipment"
    ], "CASH FLOW:"),
    ("Stock Based Compensation", [
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense"
    ], "CASH FLOW:"),
    ("Basic (in shares)", [
        "CommonStockSharesOutstanding", 
        "EntityCommonStockSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic"
    ], "PROFIT & LOSS"),
]


def resolve_cik(company_id: str) -> str:
    """Resolve 10-digit zero-padded CIK string for company_id."""
    if company_id in CIK_REGISTRY:
        return CIK_REGISTRY[company_id]

    ticker = company_id.split("_")[0].upper()
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for entry in data.values():
                if entry.get("ticker", "").upper() == ticker:
                    cik_int = entry["cik_str"]
                    return str(cik_int).zfill(10)
    except Exception as e:
        logger.warning("Failed SEC CIK lookup for %s: %s", company_id, e)

    # Never silently fall back to a different company's CIK — that would fetch the
    # wrong company's financials. Fail loudly so the caller can fix the registry.
    raise ValueError(
        f"Could not resolve SEC CIK for '{company_id}' (ticker '{ticker}'). "
        f"Add it to CIK_REGISTRY or verify the SEC company_tickers lookup."
    )


# Annual filings whose facts may be used, including the amended variants.
ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"})

# How many historical annual periods the model keeps.
HISTORICAL_PERIODS = 3

# A duration fact is annual when it spans most of a year. Quarterly and
# year-to-date facts sit well below this and a cumulative nine-month figure at
# 272 days is excluded; the bounds allow for 52/53-week and 4-4-5 calendars.
MIN_ANNUAL_SPAN_DAYS = 330
MAX_ANNUAL_SPAN_DAYS = 400


def _span_days(item: dict) -> Optional[int]:
    start, end = item.get("start"), item.get("end")
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except (ValueError, TypeError):
        return None


def _end_of(item: dict) -> Optional[date]:
    raw = item.get("end")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _is_annual_filing(item: dict) -> bool:
    """True when the fact comes from an annual report, not a 10-Q."""
    return item.get("form") in ANNUAL_FORMS and item.get("fp") == "FY"


def _fiscal_label(period_end: date) -> str:
    """Period label for a fiscal year end.

    A fiscal year is named for the calendar year its period end falls in, which
    is how a filer refers to it in its own report. A year ending 31 January 2026
    is FY26.
    """
    return f"FY{str(period_end.year)[2:]}"


def _discover_annual_period_ends(us_gaap: dict) -> List[date]:
    """Fiscal year ends for which a genuine annual duration fact exists.

    Built from the income-statement and cash-flow tags because those carry a
    `start`, so a fact can be proven annual by its span. Within one filing the
    comparative shares the fiscal-year field but ends EARLIER, so the latest end
    per fiscal year is the year that filing actually reports.
    """
    probe_tags = (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "NetIncomeLoss",
        "OperatingIncomeLoss",
        "ProfitLoss",
    )
    latest_end_by_fy: Dict[int, date] = {}
    for tag in probe_tags:
        data = us_gaap.get(tag)
        if not data:
            continue
        for unit_items in data.get("units", {}).values():
            for item in unit_items:
                if not _is_annual_filing(item):
                    continue
                span = _span_days(item)
                if span is None or not (MIN_ANNUAL_SPAN_DAYS <= span <= MAX_ANNUAL_SPAN_DAYS):
                    continue
                end = _end_of(item)
                fy = item.get("fy")
                if end is None or fy is None:
                    continue
                try:
                    fy_int = int(fy)
                except (ValueError, TypeError):
                    continue
                if fy_int not in latest_end_by_fy or end > latest_end_by_fy[fy_int]:
                    latest_end_by_fy[fy_int] = end
    return sorted(latest_end_by_fy.values())


def _facts_at_period_ends(
    unit_items: List[dict],
    target_ends: List[date],
) -> Dict[date, dict]:
    """Best fact for each requested period end.

    A duration fact must additionally prove it is annual by its span; an instant
    fact (a balance sheet) has no `start`, so the period end alone identifies it.
    When several filings report the same period, the most recently filed wins —
    that is the company's latest restatement of the figure.
    """
    wanted = set(target_ends)
    best: Dict[date, dict] = {}
    for item in unit_items:
        if not _is_annual_filing(item):
            continue
        end = _end_of(item)
        if end is None or end not in wanted:
            continue
        if item.get("start") is not None:
            span = _span_days(item)
            if span is None or not (MIN_ANNUAL_SPAN_DAYS <= span <= MAX_ANNUAL_SPAN_DAYS):
                continue
        filed = item.get("filed") or ""
        current = best.get(end)
        if current is None or filed > (current.get("filed") or ""):
            best[end] = item
    return best


def _has_period(unit_items: List[dict], target_ends: List[date]) -> bool:
    return bool(_facts_at_period_ends(unit_items, target_ends))


def fetch_and_parse_sec_edgar(company_id: str = "aapl_us") -> list[RawDatapoint]:
    """Fetch live XBRL company facts from SEC EDGAR API and return RawDatapoints.

    Args:
        company_id: Identifier e.g. "aapl_us", "msft_us", "tsla_us", "meta_us".

    Returns:
        List of RawDatapoint records tagged with real US GAAP Capex and source="sec_edgar".
    """
    cik = resolve_cik(company_id)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

    # Rate limiting compliance: 10 req/sec max (0.1s delay)
    time.sleep(0.1)

    resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"SEC EDGAR API HTTP {resp.status_code} for CIK {cik} ({company_id})")

    facts_data = resp.json()
    us_gaap = facts_data.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        raise ValueError(f"No us-gaap facts found in SEC EDGAR response for CIK {cik}")

    # ------------------------------------------------------------------ #
    # Period discovery
    #
    # A fiscal year in company facts is not a period. One `fy` value carries
    # several facts: the annual figure for that year AND the prior-year
    # comparative that the SAME filing restates, and for balance-sheet tags the
    # prior year-end instant as well. Selecting "an item with this fy" and
    # keeping the last one seen therefore picks a comparative as often as the
    # real period, and the choice depends on payload order rather than on which
    # figure the year actually describes.
    #
    # The observable that settles it is the period end date. Within one fiscal
    # year, the annual figure is the one whose `end` is LATEST. So the annual
    # period ends are discovered first, and every tag — duration or instant — is
    # then read at exactly those dates. A balance-sheet fact can no longer land
    # on a date no income statement covers, which is what used to leave the most
    # recent year holding four lines and no revenue.
    # ------------------------------------------------------------------ #
    annual_period_ends = _discover_annual_period_ends(us_gaap)

    if not annual_period_ends:
        raise ValueError(
            f"No annual fiscal periods found in SEC EDGAR facts for {company_id} (CIK {cik})"
        )

    target_ends = annual_period_ends[-HISTORICAL_PERIODS:]

    # Label each period from the company's own fiscal year end, so FY26 always
    # means the year that ended in 2026 rather than whichever filing happened to
    # carry the tag.
    target_labels = {end: _fiscal_label(end) for end in target_ends}

    datapoints: list[RawDatapoint] = []
    now = datetime.now()

    for metric_label, tag_list, section in US_GAAP_TAG_MAP:
        selected_tag = None
        tag_data = None
        for tag in tag_list:
            if tag in us_gaap:
                # Check if this tag has items for our target period ends
                units_dict = us_gaap[tag].get("units", {})
                unit_items = units_dict.get("USD", []) or units_dict.get("shares", []) or units_dict.get("pure", [])
                if _has_period(unit_items, target_ends):
                    selected_tag = tag
                    tag_data = us_gaap[tag]
                    break

        # Fallback to the first tag in tag_list that is present in us_gaap if no tag had target period data
        if not selected_tag:
            for tag in tag_list:
                if tag in us_gaap:
                    selected_tag = tag
                    tag_data = us_gaap[tag]
                    break

        if not selected_tag or not tag_data:
            continue

        units_dict = tag_data.get("units", {})
        unit_items = units_dict.get("USD", []) or units_dict.get("shares", []) or units_dict.get("pure", [])

        for period_end, item in _facts_at_period_ends(unit_items, target_ends).items():
            period_lbl = target_labels[period_end]
            raw_val = float(item["val"])

            # Unit conversion: monetary values to USD millions; share counts are
            # likewise stored in millions so downstream per-share math stays consistent.
            val = raw_val / 1e6

            end_d = period_end
            fy = period_end.year

            dp_id = _datapoint_id(company_id, metric_label, period_lbl, "sec_edgar", section, fy)
            datapoints.append(
                RawDatapoint(
                    id=dp_id,
                    company_id=company_id,
                    metric_raw=metric_label,
                    period_label=period_lbl,
                    period_end_date=end_d,
                    value=round(val, 4),
                    currency="USD",
                    units="millions",
                    source="sec_edgar",
                    source_location=(
                        f"SEC_EDGAR_CompanyFacts!us-gaap:{selected_tag}"
                        f"[period_end={end_d.isoformat()};form={item.get('form')}"
                        f";filed={item.get('filed')}]"
                    ),
                    status="reported",
                    update_date=now,
                )
            )

    if not datapoints:
        raise ValueError(f"Failed to parse any valid 10-K datapoints from SEC EDGAR for {company_id}")

    return datapoints


def parse_sec_edgar_export(path: str | Path, company_id: str = "aapl_us") -> list[RawDatapoint]:
    """Parse a local spreadsheet export into RawDatapoints.

    PROVENANCE. The figures in these workbooks are maintained by hand in the
    repository; they are not a retrieval from EDGAR and must never claim to be.
    This function therefore tags them `local_export` / `estimated` and points
    `source_location` at the real file and cell.

    It previously tagged every row `sec_edgar` / `reported` with a fabricated
    `SEC_EDGAR_CompanyFacts!<col><row>` location. Because `sec_edgar` is in
    AUTHORITATIVE_SOURCES that label made invented projections outrank real
    filings, and it presented them to the reader as audited 10-K data. Several
    companies served their last two "historical" years from these files, so the
    growth rate the whole forecast faded from was computed on figures no filer
    ever published.
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Data Sheet"]
    rows = list(ws.iter_rows(values_only=True))
    file_ref = Path(path).name

    datapoints: list[RawDatapoint] = []
    header_idx = None
    for i, row in enumerate(rows):
        if row[0] in ("PROFIT & LOSS", "BALANCE SHEET", "CASH FLOW:"):
            header_idx = i
        if row[0] == "Report Date" and header_idx is not None:
            periods: list[date] = [r.date() for r in row[1:] if hasattr(r, "date")]
            section = rows[header_idx][0]
            for j in range(i + 1, len(rows)):
                label = (rows[j][0] or "").strip()
                if not label or (isinstance(rows[j][0], str) and rows[j][0] in ("PROFIT & LOSS", "BALANCE SHEET", "CASH FLOW:", "Quarters", "PRICE:", "DERIVED:")):
                    break
                values = [_clean(v) for v in rows[j][1:]]
                for k, (period, val) in enumerate(zip(periods, values)):
                    if val is None:
                        continue
                    source: Source = "local_export"
                    status: Status = "estimated"
                    offset = k + 2
                    col = openpyxl.utils.get_column_letter(offset + 1)
                    datapoints.append(
                        RawDatapoint(
                            id=_datapoint_id(company_id, label, _period_label(period), source, section, j + 1),
                            company_id=company_id,
                            metric_raw=label,
                            period_label=_period_label(period),
                            period_end_date=period,
                            value=val,
                            currency="USD",
                            units="millions",
                            source=source,
                            source_location=f"{file_ref}!Data Sheet!{col}{j + 1}",
                            status=status,
                            update_date=datetime.now(),
                        )
                    )
            header_idx = None
    wb.close()
    return datapoints
