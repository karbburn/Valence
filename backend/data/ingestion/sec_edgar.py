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

from backend.data.errors import NoFinancialsAvailable
from backend.data.store import RawDatapoint, Source, Status
from backend.data.ingestion import ifrs_tags

logger = logging.getLogger(__name__)

SEC_HEADERS = {
    "User-Agent": "ValencePlatform team@valence.com",
    "Accept-Encoding": "gzip, deflate",
}

# Known CIK lookup table
# A fallback for when SEC's ticker file cannot be reached, not a source of truth.
#
# These are consulted ONLY after SEC has been asked and has failed, and a hit here
# is logged as a warning. The entry for infy_us was wrong and cost a launch: it held
# 0001065280, which is NETFLIX, so the "Infosys Limited (NYSE ADR)" page was built
# from Netflix's 10-K. Revenue 45,183, total assets 55,597, cash 9,033 and equity
# 26,616 are all Netflix's FY2025 figures, the bridge was Netflix's, and the page
# published an implied share price of $63.25 against a market price of $10.64 —
# six times the price of a company the page named. Nothing caught it: the model was
# internally consistent, every identity held, the workbook agreed with the model, and
# the tie-out reported the filer as merely "not auditable because it reports under
# IFRS", which is a statement about the taxonomy and read as though the numbers had
# been left alone.
#
# A hand-kept identifier that is trusted without a check is a company name waiting
# to be wrong, and nothing downstream can detect it, because every consumer believes
# it. So SEC's own ticker file decides, and this table only covers for SEC being
# unreachable.
CIK_REGISTRY: Dict[str, str] = {
    "aapl_us": "0000320193",
    "msft_us": "0000789019",
    "infy_us": "0001067491",
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
    # Revenue tags, in priority order. Each entry here is a filer that exists and
    # publishes perfectly good statements and was silently absent from the model
    # because its tag was missing from this list -- no error, no warning, just a
    # company that never appears. A uniform probe of the US index
    # (assets/gsd/coverage_probe.py) is what found the gap.
    #
    # `IncludingAssessedTax` is the one that was missing, and it is not rare:
    # filers tag it instead of `ExcludingAssessedTax` for a perfectly defensible
    # reason, and a tag list that assumes one choice silently loses the filer.
    # Liberty Latin America, Annaly, Northwest Bancshares and AEGON were among
    # those it lost. Expect any new tag here to be a bug surface rather than a
    # nicety, and verify it with the probe before believing it.
    ("Revenues", [
        "Revenues", 
        "RevenueFromContractWithCustomerExcludingAssessedTax", 
        # Includes sales taxes collected on the issuer's behalf. Materially the
        # same revenue figure, and the filers using it are not doing anything odd.
        "RevenueFromContractWithCustomerIncludingAssessedTax",
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
    # Operating expense detail.
    #
    # The income statement renderer has always carried rows for research and
    # development, selling and administrative, and other operating expense, and
    # every one of them exported blank for every company, because no tag here fed
    # them. A reader seeing "Operating Profit (EBIT)" with nothing above it reads
    # the profit as unexplained, and on a filer like this one the research line
    # alone runs to tens of billions.
    ("Research and development", [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ], "PROFIT & LOSS"),
    # Selling and administrative expense, in the two shapes filers actually use.
    #
    # One filer reports a single combined line, another splits the same total into
    # selling and marketing plus general and administrative. The combined tag is
    # read on its own, and the two components are read separately, so that
    # derivation can publish one line either way.
    #
    # The components must not be read as a fallback for the combined line. Doing
    # so silently dropped the marketing half: the component is a third to a half
    # of the total, and the workbook went on to show a gross profit and an
    # operating profit that no longer met, with a gap that grew every year.
    ("Selling and admin", ["SellingGeneralAndAdministrativeExpense"], "PROFIT & LOSS"),
    ("Selling and marketing", ["SellingAndMarketingExpense"], "PROFIT & LOSS"),
    ("General and administrative", ["GeneralAndAdministrativeExpense"], "PROFIT & LOSS"),
    ("Operating profit", ["OperatingIncomeLoss", "OperatingProfit", "IncomeLossFromOperations"], "PROFIT & LOSS"),
    ("Depreciation", [
        "DepreciationDepletionAndAmortization", 
        "DepreciationAndAmortization",
        "Depreciation"
    ], "PROFIT & LOSS"),
    # A filer may use the operating or the non-operating interest tag and switch
    # between them across years.
    #
    # Net measures are deliberately excluded. InterestIncomeExpenseNet is already
    # net of interest income, and finance cost is added to profit before tax when
    # EBITDA is derived, so admitting it here would count a net figure as a gross
    # one. A tag that does not mean the same thing as its neighbours does not
    # belong in the list. One large-cap pharma tags InterestExpense
    # through 2023 and InterestExpenseNonoperating from 2024 onward, so reading
    # only the first tag fills the earlier years and leaves the recent ones
    # empty. That in turn leaves operating profit unbridgeable, because the PBT
    # identity needs finance cost, and the forecast then anchors on whatever
    # single year was left. Both spellings are listed so the years join up.
    (
        "Finance cost",
        [
            "InterestExpense",
            "InterestExpenseNonoperating",
            "InterestAndDebtExpense",
            "InterestExpenseDebt",
        ],
        "PROFIT & LOSS",
    ),
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
    # Net block, in the order filers actually tag it.
    #
    # Gross property, plant and equipment was the second choice, and gross is not
    # net: a filer that tags only the gross figure would publish accumulated
    # depreciation nowhere, so the balance sheet carried the wrong block and
    # overstated assets by the whole accumulated depreciation. Gross is a worse
    # answer than absent, so it is not in the list at all.
    #
    # The third spelling is the one filers use when they combine the net block
    # with finance lease right-of-use assets into a single caption. It is carried
    # after the plain net tag, which the other large filers tag, so reading it
    # cannot disturb them.
    ("Net Block", [
        "PropertyPlantAndEquipmentNet",
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
    ], "BALANCE SHEET"),
    # Gross asset base and accumulated depreciation, kept as separate lines.
    #
    # These exist for one reason: the steady-state capex target. Depreciation runs
    # on a GROSS asset base, so the depreciation rate delta = D&A / gross PP&E is
    # what a terminal value has to be built on, and net PP&E alone cannot give it --
    # net divided by gross understates delta and therefore overstates the growth the
    # business can fund, which inflates the terminal value.
    #
    # Both are standard us-gaap tags and most filers report them, often only as
    # parenthetical components of a single net caption rather than as their own line.
    ("Gross Block", [
        "PropertyPlantAndEquipmentGross",
    ], "BALANCE SHEET"),
    ("Accumulated Depreciation", [
        "AccumulatedDepreciationDepletionAndAmortization",
        "AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
        "AccumulatedDepreciation",
    ], "BALANCE SHEET"),
    ("Cash & Bank", [
        "CashAndCashEquivalentsAtCarryingValue", 
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashAndShortTermInvestments"
    ], "BALANCE SHEET"),
    ("Current investments", [
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesCurrent",
        "ShortTermInvestments",
        # LAST, and deliberately. This element covers the DEBT securities slice of an
        # available-for-sale portfolio, which is narrower than ShortTermInvestments:
        # it excludes the equity and other holdings a filer may park in the same
        # line. Ahead of ShortTermInvestments it made Ambarella publish 121.6 of
        # debt securities where it had been publishing 122.0 of short-term
        # investments, so a broader balance was silently replaced by a narrower one
        # for no stated reason. Last, it is still reached by a filer that tags
        # nothing else, which is the only case that needed it.
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    ], "BALANCE SHEET"),
    ("Inventory", [
        "InventoryNet",
        "InventoryGross",
        "InventoryFinishedGoods"
    ], "BALANCE SHEET"),
    # Vendor non-trade receivables, a line of its own on a filer's balance sheet and
    # one of its largest: Apple's was 33,180 against total current assets of 147,957,
    # so a current-asset block that omitted it fell a fifth of the way short of the
    # filer's own subtotal and nothing said so. It is not a member of the trade
    # receivables line and not part of the other-current-assets catch-all, which is
    # why it needs a canonical key of its own rather than a home inside either.
    ("Vendor non-trade receivables", [
        "NontradeReceivablesCurrent",
    ], "BALANCE SHEET"),
("Unbilled revenue", [
        # Deliberately no us-gaap element, and the reason is a specific filer's own
        # balance sheet rather than a general doubt.
        #
        # `ContractWithCustomerAsset` and `UnbilledReceivablesCurrent` were named here
        # in e6d95d6, to give `canonical.bs.unbilled_revenue` a producer: the key is
        # wired through the renderer, the working-capital driver and the DSO ratio, and
        # a subtraction with no producer always subtracts zero. An element existing in
        # the taxonomy is not a filer printing it on the face of the statement, though,
        # and AMDOCS' 20-F for FYE 2025-09-31 draws the line differently:
        #
        #     Cash and cash equivalents                  324,999    346,085
        #     Short-term interest-bearing investments          0    168,242
        #     Accounts receivable, net                   935,751  1,028,357
        #     Prepaid expenses and other current assets  331,387    228,498
        #     Total current assets                    1,592,137  1,771,182
        #
        # Five captions, both columns summing exactly, and no contract-asset line
        # among them. AMDOCS discloses the element in a note, where it sits inside the
        # caption already mapped above, so mapping it as its own line counted the same
        # money twice -- by exactly the line: +157.166, +211.498, +362.617 against a
        # filed subtotal of 2,003 / 1,912 / 1,771.
        #
        # The label is kept because the IFRS map keys on us-gaap labels and asserts they
        # exist, and Infosys' `CurrentAccruedIncomeIncludingCurrentContractAssets` IS a
        # face caption -- 1,503 at 2025-03-31, read off the 20-F and matching to the
        # rupee. The vocabularies disagree here, so the mapping is asymmetric on
        # purpose rather than by omission.
        #
        # A us-gaap filer that does break contract assets out on the face of its
        # balance sheet will need this back, and the reconciliation gate is what will
        # say so: the line is added, the subtotal stops matching, and the caption is
        # read off that filer's own statement before the element is trusted.
], "BALANCE SHEET"),
        ("Trade receivables", [
        "AccountsReceivableNetCurrent", 
        "ReceivablesNetCurrent"
    ], "BALANCE SHEET"),
    # ONE current-asset catch-all, and the filer's own caption for it.
    #
    # `OtherAssetsCurrent` and `OtherAssetsMiscellaneousCurrent` belong here rather
    # than in a key of their own. In the us-gaap taxonomy they are the same money as
    # `PrepaidExpenseCurrent` viewed from different levels: Armstrong prints one
    # line, "Other current assets 23.9", of which prepaid expenses are 22.5. Held
    # under two canonical keys, the smaller sits inside the larger and every sum
    # that includes both double-counts it — Armstrong's identified current assets
    # came to 414.0 against a filed subtotal of 391.5, and because the residual was
    # clamped at zero, that 22.5 of overlap was reported nowhere.
    #
    # Ordered from the statement-level element down to the narrowest, so a filer
    # that publishes the whole line gets the whole line and a filer that publishes
    # only prepaid expenses still has a home.
("Current income tax assets", [
        # No us-gaap element, deliberately, and verified empty rather than guessed:
        # current income tax assets are not a separate caption anywhere in the
        # taxonomy. `IncomeTaxReceivableCurrent` and `IncomeTaxesReceivableCurrent`
        # each 404 on SEC companyconcept for MSFT, AAPL, NVDA, JPM and JNJ, and a US
        # filer carries this money inside `OtherAssetsCurrent`, already mapped to
        # "Prepayments and other assets". Naming an element here that returns 404
        # would not be a harmless no-op -- it would read as a mapping that works.
], "BALANCE SHEET"),
("Current derivative financial assets", [
        # No us-gaap element, on the same evidence: `DerivativeFinancialAssetsCurrent`,
        # `DerivativeAssetsCurrent` and `HedgingAssetsCurrent` all 404 across those
        # five filers. See above.
], "BALANCE SHEET"),
        ("Prepayments and other assets", [
        "OtherAssetsCurrent",
        "PrepaidExpenseAndOtherAssetsCurrent",
        "OtherAssetsMiscellaneousCurrent",
        "OtherAssetsCurrentNontrade",
        "PrepaidExpenseCurrent",
    ], "BALANCE SHEET"),
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
    #
    # Oracle files NEITHER of the three tags above. It reports borrowings as one
    # combined long-term-and-short-term total and nothing else, so this list
    # resolves to nothing for Oracle and its entire 121,916 long-term stack
    # disappeared from the EV -> equity bridge. Verified against
    # data.sec.gov companyfacts for CIK0001341439 on 2026-09-27:
    #
    #   DebtLongtermAndShorttermCombinedAmount  2026-05-31   129,541
    #   NotesPayableCurrent                     2026-08-31     7,625
    #   LongTermDebtNoncurrent / LongTermDebtCurrent   ABSENT
    #
    # The bridge deducted 14,900 against an obligation above 129,000, and the
    # engine reported 10 of 10 checks passed with an implied price 66% below
    # the market.
    #
    # The combined tag deliberately is NOT in this list. The valuation pipeline
    # sums non-current + current + finance leases, so taking a combined figure as
    # the non-current half would count the current slice twice.
    # `_derive_noncurrent_borrowings` subtracts it instead, and that is the only
    # place that arithmetic happens.
    # Non-current assets.
    #
    # The renderer publishes rows for goodwill, intangibles, deferred tax, non-current
    # investments and a catch-all, and every one of them was blank for every company
    # because no tag fed them. The visible consequence is a balance sheet that does
    # not add up on its face: this filer reported 81,198 of non-current assets
    # against 10,383 of property, plant and equipment, so 70,815 of the balance sheet
    # was simply absent, including 20,832 of goodwill.
    #
    # The subtotal is tagged when the filer publishes one, and derived from total
    # assets less current assets when it does not, which is the common case. It is
    # never left blank, because a subtotal no line explains is no more use to a
    # reader than a missing one.
    ("Goodwill", ["Goodwill"], "BALANCE SHEET"),
    ("Intangible assets", [
        "FiniteLivedIntangibleAssetsNet",
        "IntangibleAssetsNetExcludingGoodwill",
    ], "BALANCE SHEET"),
    ("Deferred income tax assets", ["DeferredIncomeTaxAssetsNet"], "BALANCE SHEET"),
    # The filer's own catch-all. A filer that itemises nothing else puts its
    # right-of-use assets, long-term investments and sundry balances here, and
    # those are the majority of non-current assets at most filers. Naming them
    # keeps the balance sheet adding up to its own subtotal.
    ("Other non-current assets", ["OtherAssetsNoncurrent"], "BALANCE SHEET"),
    # Long-term investments and non-current securities.
    #
    # These are not a rounding item. One filer holds a third of its non-current
    # assets in securities that this statement previously had no line for at all,
    # so 330,505 of a 389,243 subtotal was carried with nothing naming it.
    #
    # The order matters, because a filer may tag several of these and they are not
    # additive. Debt securities and marketable securities are the same holding
    # under two captions, and equity securities without a readily determinable
    # fair value is a subset of other long-term investments. Within a single year
    # only the first tag carrying that year is taken, so nothing is summed and no
    # year double counts.
    #
    # `LongTermInvestments` is the aggregate and sits with the aggregates, ahead of
    # the subsets. Microsoft tags both, and taking the subset instead left 23,948
    # of its filed investments out of the bridge: its 10-K line "Investments" is
    # 36,348, of which "Equity investments" is 12,400 and "Equity method
    # investments" is 12,000, so the subset is neither the caption a reader finds
    # nor the whole of what is nettable against the debt.
    #
    # Across years the behaviour is weaker, and worth stating plainly. Where the
    # first tag has no fact for a year, the sibling top-up fills it from a later
    # tag, so a filer that reports debt securities in one year and marketable
    # securities in another ends up with one row spanning two captions. That is
    # preferable to a gap, and the two captions are close enough in substance that
    # the year-on-year movement is not misleading, but the row is not a single
    # consistent definition and should not be read as one.
    ("Non-current investments", [
        "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent",
        "MarketableSecuritiesNoncurrent",
        "OtherLongTermInvestments",
        "LongTermInvestments",
        "EquitySecuritiesWithoutReadilyDeterminableFairValueAmount",
    ], "BALANCE SHEET"),
    ("Total non-current assets", ["AssetsNoncurrent"], "BALANCE SHEET"),
    ("Borrowings", [
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebt",
    ], "BALANCE SHEET"),
    ("Short term borrowings", [
        "LongTermDebtCurrent",
        "DebtCurrent",
        # Oracle's current slice. It files no LongTermDebtCurrent at all, and
        # DebtCurrent stops at the last 10-K, so the most recent quarter carried
        # no current debt at all until this tag was added.
        "NotesPayableCurrent",
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
    # Mezzanine equity: redeemable preferred, redeemable noncontrolling interest.
    #
    # A filer that prints this presents it BETWEEN liabilities and equity, and its
    # "Total liabilities" excludes it. Without ingesting the line the engine cannot
    # tell that filer apart from one whose liability components merely fall short,
    # so reconciling the subtotal back-solves and folds the mezzanine into
    # liabilities -- Uxin publishing 378,894 against a filed 330,838.
    #
    # `MezzanineEquity` is the element Uxin files; the redeemable variants are what
    # filers use when they break the line out.
    ("Mezzanine equity", [
        "MezzanineEquity",
        "TemporaryEquityCarryingAmountAttributableToParent",
        "RedeemableNoncontrollingInterestEquityCarryingAmount",
        "RedeemablePreferredStockCarryingAmount",
    ], "BALANCE SHEET"),
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
    # EPS, per share, for both bases.
    #
    # The diluted share count is derived from net profit over diluted EPS, and
    # without these lines that derivation cannot run for a US filer at all, so the
    # count came from the live provider while the filing held the number. NVIDIA
    # files 24,304m shares outstanding and the engine was pricing on 24,147m from a
    # provider, a difference nobody could see because the fallback is silent.
    #
    # Per-share, not in shares: the label is what the taxonomy registry maps to
    # canonical.is.eps_basic and canonical.is.eps_diluted.
    ("Diluted (in $)", [
        "EarningsPerShareDiluted",
    ], "PROFIT & LOSS"),
    ("Basic (in $)", [
        "EarningsPerShareBasic",
    ], "PROFIT & LOSS"),
]

# The revenue tag group, lifted out of the table above so anything needing the same
# list reads it rather than restating it. `_discover_annual_period_ends` uses this to
# work out which fiscal years a filer has reported. Derived once, from the table, so
# adding a tag in one place cannot leave the other list behind -- which is exactly
# how the IncludingAssessedTax fix landed in US_GAAP_TAG_MAP while the period probe
# one function below kept the old list.
def _revenue_tags() -> Tuple[str, ...]:
    """The revenue tag group, read from US_GAAP_TAG_MAP.

    A function rather than a module constant so the lookup happens at call time.
    Assigning it at import time with a bare `next()` would raise StopIteration at
    import -- with no message -- if the "Revenues" label were ever renamed, taking
    down every entry point that imports this module. Raising here says which entry
    went missing instead.

    Anything that needs the revenue tags should call this rather than keeping its
    own copy: `_discover_annual_period_ends` had a second, separately maintained
    list which silently fell behind US_GAAP_TAG_MAP, so a filer tagging revenue
    only as IncludingAssessedTax was invisible to period discovery even after the
    ingestion fix that made it visible to everything else.
    """
    for label, tags, _section in US_GAAP_TAG_MAP:
        if label == "Revenues":
            return tuple(tags)
    raise RuntimeError(
        "US_GAAP_TAG_MAP has no 'Revenues' entry, so the revenue tag group cannot be "
        "resolved. Every consumer of revenue tags depends on it."
    )

# Tags that report borrowings as ONE combined long-term-and-short-term figure
# rather than splitting the current slice out. A filer using one of these files no
# non-current borrowings tag at all, so the "Borrowings" line above resolves to
# nothing and the whole long-term stack silently leaves the bridge. The comment
# on that line already recorded the symptom ("one large filer's borrowings
# resolved to nothing at all") without fixing the cause, because there was no tag
# to fall back to.
COMBINED_DEBT_TAGS = (
    "DebtLongtermAndShorttermCombinedAmount",
    "DebtLongtermAndShorttermCombined",
    "LongTermDebtAndShortTermCombinedAmount",
)

# Mirrors the "Short term borrowings" preference order exactly, so the
# subtraction removes precisely what that line adds back. Typed once and
# referenced, not typed twice, because two lists that drift apart silently
# double-count.
_NONCURRENT_BORROWINGS_TAGS = (
    "LongTermDebtNoncurrent",
    "LongTermDebtAndCapitalLeaseObligations",
    "LongTermDebt",
)
_CURRENT_DEBT_TAGS = (
    "LongTermDebtCurrent",
    "DebtCurrent",
    "NotesPayableCurrent",
    "ShortTermBorrowings",
    "OtherShortTermBorrowings",
    "ShortTermBankLoansAndNotesPayable",
)


def _derive_noncurrent_borrowings(
    us_gaap: dict,
    target_ends: set,
) -> Dict[date, float]:
    """Non-current borrowings derived from a combined debt tag, in millions.

    Returns empty when the filer already tags a non-current borrowings concept,
    because then the direct tag is authoritative and nothing should be inferred.

    Where a combined tag exists, non-current is the combined total less the
    current portion. Reporting the combined total as the non-current half would
    double-count, since the caller sums the two.

    When the current slice cannot be found at all, the combined total is used as
    it stands. A company with no maturities inside twelve months genuinely has
    current debt of zero, and at this level that is indistinguishable from the
    tag simply being absent. Guessing zero in the absent case would understate
    debt, and understating debt flatters the equity value, so the safer of the
    two errors is the one that does not invent a number.
    """
    # Presence is not enough. Oracle *does* carry a `LongTermDebt` tag, so a
    # presence test concludes the filer is covered and returns empty, which is
    # precisely the failure this function exists to correct. What matters is
    # whether a tag actually carries facts for the periods being built, and that
    # is the same test the main loop makes.
    for tag in _NONCURRENT_BORROWINGS_TAGS:
        if tag not in us_gaap:
            continue
        items = us_gaap[tag].get("units", {}).get("USD", [])
        if _has_period(items, list(target_ends)):
            return {}

    combined_tag = next((t for t in COMBINED_DEBT_TAGS if t in us_gaap), None)
    if combined_tag is None:
        return {}

    combined = _facts_at_period_ends(
        us_gaap[combined_tag].get("units", {}).get("USD", []), target_ends
    )
    if not combined:
        return {}

    current_items: list = []
    for tag in _CURRENT_DEBT_TAGS:
        if tag in us_gaap:
            current_items = us_gaap[tag].get("units", {}).get("USD", []) or []
            if current_items:
                break
    current = _facts_at_period_ends(current_items, target_ends) if current_items else {}

    out: Dict[date, float] = {}
    for end, item in combined.items():
        total = float(item["val"])
        slice_ = current.get(end)
        if slice_ is not None:
            noncurrent = total - float(slice_["val"])
        else:
            noncurrent = total
            logger.info(
                "no current debt tag found at %s for the combined tag %s; "
                "reporting the full %s as non-current rather than assuming zero",
                end, combined_tag, f"{noncurrent:,.0f}",
            )
        if noncurrent > 0:
            out[end] = noncurrent / 1e6
    return out


def resolve_cik(company_id: str) -> str:
    """Resolve the 10-digit zero-padded CIK for a company_id, from SEC.

    SEC's own ticker file is the authority, and it is asked first on every call. The
    fallback table is consulted only when SEC cannot be reached, and a hit there is
    logged as a warning naming the entry, because a fallback that cannot announce
    itself is indistinguishable from a verified answer.

    This ordering is the fix. The table used to be consulted first and returned
    without a check, so a wrong identifier was never questioned by anything
    downstream: the ingestion read a different company's facts, labelled them with
    the requested company's ticker, and produced a model that was internally perfect
    and entirely fictional. See CIK_REGISTRY.
    """
    ticker = company_id.split("_")[0].upper()
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for entry in data.values():
                if entry.get("ticker", "").upper() == ticker:
                    cik_int = entry["cik_str"]
                    resolved = str(cik_int).zfill(10)
                    cached = CIK_REGISTRY.get(company_id)
                    if cached and cached != resolved:
                        # One request either way, so the table earns nothing. The
                        # stale value is reported rather than quietly used, which is
                        # how a wrong identifier stops being invisible.
                        logger.warning(
                            "CIK_REGISTRY['%s'] is %s but SEC says %s for ticker %s; "
                            "using SEC's and the registry entry is stale",
                            company_id, cached, resolved, ticker,
                        )
                    return resolved
    except Exception as e:
        logger.warning("Failed SEC CIK lookup for %s: %s", company_id, e)

    cached = CIK_REGISTRY.get(company_id)
    if cached:
        logger.warning(
            "Falling back to the unverified CIK_REGISTRY entry %s for '%s' because "
            "SEC's ticker file was unreachable. This identifier has not been "
            "checked against the filer and must not be relied on.",
            cached, company_id,
        )
        return cached

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


# The unit keys a filer's facts arrive under, in the order they are preferred.
#
# `USD/shares` is a per-share amount and was missing from this list, so every EPS
# tag was read as carrying nothing and silently dropped: the lookup found no unit
# it recognised, produced an empty list, and the diluted share count — which is
# derived from net profit over diluted EPS — could not be derived at all. It fell
# through to the live provider instead, so NVIDIA was priced on 24,147m shares
# while its filing carried 24,304m outstanding.
_UNIT_KEYS = ("USD", "USD/shares", "shares", "pure")

# Labels carrying an amount PER SHARE rather than a total, so the millions
# conversion does not apply to them.
_PER_SHARE_LABELS = frozenset({"Diluted (in $)", "Basic (in $)"})


def _unit_items(units_dict: dict) -> List[dict]:
    """The facts for the first unit this filer actually used."""
    for key in _UNIT_KEYS:
        items = units_dict.get(key)
        if items:
            return items
    return []


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
    # Read the revenue tags from the map rather than restating them, so the probe
    # cannot fall behind US_GAAP_TAG_MAP. See `_revenue_tags` for why this list used
    # to be a problem. Divergence is impossible by construction here, which is why
    # there is no test asserting the two agree.
    probe_tags = _revenue_tags() + (
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
        # A non-200 here means SEC has nothing for this CIK, or could not be reached.
        # Both are "this provider cannot supply this company", which is what
        # NoFinancialsAvailable MEANS, and the provider chain is written to continue
        # past it.
        #
        # This raised RuntimeError instead, and RuntimeError is not what the chain
        # catches. So a CIK with no company facts -- an ordinary outcome, and one of
        # roughly one in seven tickers -- skipped every other provider and reached the
        # visitor as a raw HTTP 500. A 500 says the service is broken; the truth is that
        # one ticker has no filing at this provider and there are others to try.
        #
        # The distinction that matters is preserved: a 404 names a real answer (no
        # facts for that CIK) and is logged at info, while a 5xx or a timeout is an
        # outage and is logged as one, so an SEC brownout is still visible in the logs
        # rather than looking like a ticker with no filings.
        if resp.status_code == 404:
            raise NoFinancialsAvailable(
                f"SEC EDGAR has no company facts for CIK {cik} ({company_id}); "
                f"the CIK exists but carries no XBRL financials"
            )
        raise NoFinancialsAvailable(
            f"SEC EDGAR API HTTP {resp.status_code} for CIK {cik} ({company_id})"
        )

    facts_data = resp.json()
    all_facts = facts_data.get("facts", {})

    # A foreign private issuer filing a 20-F reports under IFRS, and its facts arrive
    # under `ifrs-full`. Only looking at `us-gaap` meant every one of them raised
    # `NoFinancialsAvailable` and fell through to a market feed:
    #
    #     TSMC      334 ifrs-full tags, 0 us-gaap
    #     Infosys   300 ifrs-full tags, 0 us-gaap
    #
    # So the marquee non-US names the index carries were reading a vendor feed for the
    # want of a taxonomy check. us-gaap is still preferred where a filer reports both,
    # because that is the taxonomy the rest of the tag map is written against.
    us_gaap = all_facts.get("us-gaap", {})
    ifrs_facts = all_facts.get("ifrs-full", {})
    if us_gaap:
        tag_map = US_GAAP_TAG_MAP
        tag_namespace_used = "us-gaap"
        capex_is_negative = False
    elif ifrs_facts:
        us_gaap = ifrs_facts  # the loop below only needs a tag->facts mapping
        # Same metric labels, different element names. Walking the us-gaap map and
        # substituting keeps ONE vocabulary, so a label cannot exist here without
        # existing in the taxonomy registry. The previous version declared its own
        # labels and two of them ("CapEx", "EPS") joined to nothing, so a filer
        # arrived with no capex line and every per-share figure rounded to zero --
        # while the ingestion reported success.
        tag_map = ifrs_tags.build_ifrs_map(US_GAAP_TAG_MAP)
        tag_namespace_used = ifrs_tags.IFRS_NAMESPACE
        # IFRS reports capex as a negative number, a cash OUTFLOW. The us-gaap
        # figures this engine already handles are positive magnitudes. Without the
        # flip a filer's capital expenditure arrives as a capital release and every
        # cash flow in the model inverts.
        capex_is_negative = True
        logger.info(
            "%s (%s) reports under IFRS; reading %d ifrs-full tags.",
            company_id, cik, len(ifrs_facts),
        )
    else:
        raise NoFinancialsAvailable(
            f"No us-gaap or ifrs-full facts found in SEC EDGAR response for CIK {cik}"
        )

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
        raise NoFinancialsAvailable(
            f"No annual fiscal periods found in SEC EDGAR facts for {company_id} (CIK {cik})"
        )

    target_ends = annual_period_ends[-HISTORICAL_PERIODS:]

    # Label each period from the company's own fiscal year end, so FY26 always
    # means the year that ended in 2026 rather than whichever filing happened to
    # carry the tag.
    target_labels = {end: _fiscal_label(end) for end in target_ends}

    datapoints: list[RawDatapoint] = []
    now = datetime.now()

    # Computed once, before the loop. A filer that tags only a combined debt
    # total still has to produce a "Borrowings" line, or the long-term debt
    # leaves the bridge and nothing downstream can tell "no debt" from "no tag".
    derived_borrowings = _derive_noncurrent_borrowings(us_gaap, set(target_ends))
    if derived_borrowings:
        logger.info(
            "derived non-current borrowings for %s from a combined debt tag: %s",
            company_id,
            {target_labels.get(e, e.isoformat()): f"{v:,.0f}" for e, v in sorted(derived_borrowings.items())},
        )

    for metric_label, tag_list, section in tag_map:
        selected_tag = None
        tag_data = None
        for tag in tag_list:
            if tag in us_gaap:
                # Check if this tag has items for our target period ends
                units_dict = us_gaap[tag].get("units", {})
                unit_items = _unit_items(units_dict)
                if _has_period(unit_items, target_ends):
                    selected_tag = tag
                    tag_data = us_gaap[tag]
                    break

        # Fallback: accept a tag that is present in us_gaap but carries no fact
        # for the target periods.
        #
        # It used to be "present in us_gaap", full stop. A tag can exist in a
        # filer's vocabulary and still hold nothing for the years being built,
        # and accepting it then produced an empty period map, so the metric was
        # emitted nowhere and nothing said so. Oracle's `LongTermDebt` is exactly
        # that: present, empty for FY24-FY26, and it was chosen anyway, which is
        # how the Borrowings line vanished for it while the engine still reported
        # a clean audit. The line is now only taken when it actually has data.
        if not selected_tag:
            for tag in tag_list:
                if tag not in us_gaap:
                    continue
                items = us_gaap[tag].get("units", {})
                probe = (
                    items.get("USD", [])
                    or items.get("shares", [])
                    or items.get("pure", [])
                )
                if _has_period(probe, target_ends):
                    selected_tag = tag
                    tag_data = us_gaap[tag]
                    break

        use_derived = (
            (not selected_tag or not tag_data)
            and metric_label == "Borrowings"
            and bool(derived_borrowings)
        )
        if not use_derived and (not selected_tag or not tag_data):
            continue

        if use_derived:
            # Already in millions; the loop body converts once, on the way in,
            # so this is scaled back up rather than introducing a second
            # conversion point that could drift from the first.
            resolved = {end: val * 1e6 for end, val in derived_borrowings.items()}
            # Provenance for a figure computed from two tags is a description of
            # how it was built, not a single tag. Anything reading this on the
            # derived path was getting an unbound name.
            tag_of_period = {}
            tag_of_period = {}
        else:
            units_dict = tag_data.get("units", {})
            unit_items = _unit_items(units_dict)
            resolved = _facts_at_period_ends(unit_items, target_ends)

            # A filer may spell one concept several ways and switch between them
            # partway through its history. Picking the first tag that has *any*
            # target year, then reading only that tag, leaves the other years
            # empty, so a line looks reported for one year and absent for two.
            #
            # One large-cap pharma tags InterestExpense through 2023 and
            # InterestExpenseNonoperating from 2024. Reading the first tag alone
            # gave finance cost for FY23 only, which made operating profit
            # unbridgeable in the two recent years, which left the forecast
            # anchoring a "three-year average" operating margin on that single
            # year. The years the chosen tag does not cover are therefore topped
            # up from its siblings in preference order, and never overwritten, so
            # the primary tag keeps ownership of every year it can supply.
            tag_by_period = {end: (selected_tag, item) for end, item in resolved.items()}
            for alt_tag in tag_list:
                if alt_tag == selected_tag or alt_tag not in us_gaap:
                    continue
                alt_units = us_gaap[alt_tag].get("units", {})
                alt_items = (
                    alt_units.get("USD", [])
                    or alt_units.get("shares", [])
                    or alt_units.get("pure", [])
                )
                for end, item in _facts_at_period_ends(alt_items, target_ends).items():
                    if end not in tag_by_period:
                        tag_by_period[end] = (alt_tag, item)
            resolved = {end: item for end, (_, item) in tag_by_period.items()}
            tag_of_period = {end: tag for end, (tag, _) in tag_by_period.items()}

        for period_end, item in resolved.items():
            period_lbl = target_labels[period_end]
            raw_val = float(item["val"])

            # Unit conversion: monetary values to USD millions; share counts are
            # likewise stored in millions so downstream per-share math stays consistent.
            #
            # A per-share amount is NEITHER. Dividing 4.90 dollars per share by a
            # million yields 0.0000, and the diluted share count derived from it
            # then divides by zero and falls through to the provider, which is the
            # state this line was added to end. EPS is stored as filed, in currency
            # per share.
            val = raw_val if metric_label in _PER_SHARE_LABELS else raw_val / 1e6

            # IFRS states capex as a negative outflow; this engine stores a positive
            # magnitude for every other filer, so the sign is normalised here rather
            # than in every consumer that reads the line. Without it an IFRS filer's
            # capital expenditure arrives as a capital RELEASE, free cash flow is
            # overstated by twice the capex, and every valuation built on it is wrong
            # in the flattering direction.
            if capex_is_negative and metric_label == ifrs_tags.CAPEX_LABEL and val < 0:
                val = -val

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
                        f"SEC_EDGAR_CompanyFacts!{tag_namespace_used}:"
                        f"{tag_of_period.get(period_end) or selected_tag or 'derived'}"
                        f"[period_end={end_d.isoformat()};form={item.get('form')}"
                        f";filed={item.get('filed')}]"
                    ),
                    status="reported",
                    update_date=now,
                )
            )

    if not datapoints:
        raise NoFinancialsAvailable(
          f"Failed to parse any valid 10-K datapoints from SEC EDGAR for {company_id}"
      )

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
