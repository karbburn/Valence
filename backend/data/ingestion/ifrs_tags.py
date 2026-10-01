"""IFRS tags for filers that report under IFRS, not us-gaap.

A foreign private issuer filing a 20-F reports under IFRS. Its facts arrive in the
SEC companyfacts response under `ifrs-full`, and the parser only looked at
`us-gaap`. So it raised `NoFinancialsAvailable` and the company fell through to a
market feed.

That is not a rare edge case. It is the entire category:

    TSMC      334 ifrs-full tags, 0 us-gaap
    Infosys   300 ifrs-full tags, 0 us-gaap
    Apple     503 us-gaap tags, 0 ifrs-full

Every marquee non-US name the index carries -- TSMC, the Infosys ADR -- was reading a
vendor feed for the want of a taxonomy check, and the index holds 10,431 US tickers.

WHY THIS IS KEYED ON THE us-gaap LABELS
-----------------------------------------

The first two attempts at this declared their own metric labels. Both were wrong in
the way this codebase keeps finding things wrong: the taxonomy registry joins on the
METRIC LABEL, not the tag, so a label that is not in the registry maps to no canonical
key and the figure is dropped.

Both failures were invisible in a count of rows ingested. `CapEx` is not the
registry's label, so Infosys arrived with no capex line at all. `EPS` is not
`Diluted (in $)`, so every per-share figure was divided by a million and rounded to
zero. The ingestion reported "81 datapoints, IFRS working" in both cases. Only
reading the actual numbers showed two of them were zero and a whole line was missing.

So this keys on the SAME labels `US_GAAP_TAG_MAP` uses -- sentence case, and the
awkward ones: the capex line is `PaymentsToAcquirePropertyPlantAndEquipment`, not
"CapEx". One vocabulary, two taxonomies, and `_assert_labels_exist` below makes a
typo fail at import rather than silently drop a line.

The differences that are NOT one-to-one are documented at each entry, because those
are exactly the ones that would otherwise produce a plausible wrong figure.
"""

from __future__ import annotations

#: us-gaap metric label -> IFRS element names, in preference order.
#:
#: Order matters: the first element the filer actually reports wins, so a specific
#: element is always ahead of the broader one it nests inside.
IFRS_ALTERNATIVES: dict[str, tuple[str, ...]] = {
    # ---------------- Income statement ----------------
    "Revenues": ("RevenueFromContractsWithCustomers", "Revenue"),
    # IFRS splits cost of sales where us-gaap often reports one line. Taking only the
    # narrower element would drop part of the cost base and overstate gross profit.
    "Cost of sales": ("CostOfSales", "CostOfGoodsAndServicesSold"),
    "Gross profit": ("GrossProfit",),
    "Total operating expenses": ("OperatingExpense",),
    "Operating profit": (
        "ProfitLossFromOperatingActivities",
        "OperatingIncomeLoss",
    ),
    "Depreciation": (
        "DepreciationAndAmortisationExpense",
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLoss",
    ),
    "Profit before tax": (
        "ProfitLossBeforeTax",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
        "ExtraordinaryItemsNoncontrollingInterest",
    ),
    "Tax": ("IncomeTaxExpenseContinuingOperations", "IncomeTaxExpenseBenefit"),
    "Net Profit": (
        "ProfitLoss",
        "ProfitLossAttributableToOwnersOfParent",
        "NetIncomeLoss",
    ),
    # Per-share, so the ingestion must NOT divide these by a million. `Basic (in
    # shares)` is deliberately absent: in the us-gaap map that label is the share
    # COUNT, not basic EPS, and reusing it here would put a share count on the
    # earnings line.
    "Diluted (in $)": ("DilutedEarningsLossPerShare", "EarningsPerShareDiluted"),

    # ---------------- Balance sheet ----------------
    # IFRS `PropertyPlantAndEquipment` is the GROSS figure; the net one is
    # `...AfterAccumulatedDepreciationAndAmortisation`. Mapping the gross element onto
    # the net label would overstate the asset base by the whole accumulated
    # depreciation, so Gross Block and Net Block list different elements.
    "Net Block": (
        "PropertyPlantAndEquipmentAfterAccumulatedDepreciationAndAmortisation",
        "PropertyPlantAndEquipmentNet",
    ),
    "Gross Block": ("PropertyPlantAndEquipment",),
    "Accumulated Depreciation": (
        "AccumulatedDepreciationAndAmortisation",
        "AccumulatedDepreciationDepletionAndAmortisation",
    ),
    "Cash & Bank": (
        "CashAndCashEquivalents",
        "CashAndCashEquivalentsAtCarryingValue",
    ),
    "Inventory": ("Inventories",),
    "Trade receivables": (
        "TradeAndOtherCurrentReceivables",
        "AccountsReceivable",
        "TradeReceivables",
    ),
    "Total current assets": ("CurrentAssets", "CurrentAssetsTotal"),
    "Total assets": ("Assets",),
    "Total non-current assets": ("NoncurrentAssets", "NoncurrentAssetsTotal"),
    "Borrowings": ("Borrowings", "LongtermBorrowings"),
    "Total current liabilities": ("CurrentLiabilities", "CurrentLiabilitiesTotal"),
    "Total liabilities": ("Liabilities",),
    "Total equity": ("Equity", "EquityAttributableToOwnersOfParent"),

    # ---------------- Cash flow ----------------
    # IFRS states capex as a NEGATIVE number, a cash outflow. The us-gaap figures this
    # engine already handles are positive magnitudes, so the ingestion normalises the
    # sign. Without it a filer's capital expenditure arrives as a capital RELEASE and
    # free cash flow is overstated by twice the capex -- in the flattering direction.
    "PaymentsToAcquirePropertyPlantAndEquipment": (
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "PurchaseOfPropertyPlantAndEquipment",
    ),
    "Cash from Operating Activity": (
        "CashFlowsFromUsedInOperatingActivities",
        "NetCashFlowsFromUsedInOperatingActivities",
    ),
    "Cash from Investing Activity": (
        "CashFlowsFromUsedInInvestingActivities",
        "NetCashFlowsFromUsedInInvestingActivities",
    ),
    "Cash from Financing Activity": (
        "CashFlowsFromUsedInFinancingActivities",
        "NetCashFlowsFromUsedInFinancingActivities",
    ),
}

#: The namespace recorded in `source_location`, so a reader told where a figure came
#: from is told the truth about which taxonomy it came from.
IFRS_NAMESPACE = "ifrs-full"

#: The metric label whose IFRS figure is a negative outflow and must be flipped.
CAPEX_LABEL = "PaymentsToAcquirePropertyPlantAndEquipment"


def labels_with_ifrs() -> set[str]:
    return set(IFRS_ALTERNATIVES)


def unknown_labels(known: set[str]) -> set[str]:
    """Labels here that the us-gaap map does not define.

    A label with no us-gaap counterpart joins to nothing in the taxonomy registry, so
    its figure is silently dropped while the ingestion reports success. That is how
    `CapEx` and `EPS` produced a missing line and a column of zeros.
    """
    return set(IFRS_ALTERNATIVES) - known


def _assert_labels_exist(known: set[str]) -> None:
    missing = unknown_labels(known)
    if missing:
        raise AssertionError(
            "IFRS_ALTERNATIVES names metric labels that US_GAAP_TAG_MAP does not "
            f"define: {sorted(missing)}. Each would join to no canonical key and be "
            f"silently dropped. Use the us-gaap label verbatim."
        )


def build_ifrs_map(us_gaap_entries):
    """`tag_map` for an IFRS filer: the us-gaap map with IFRS element names.

    Walks `us_gaap_entries` rather than declaring its own list, so there is one
    vocabulary and a metric added to the us-gaap map simply has no IFRS counterpart
    until one is written -- which is honest, rather than silently mismatched.
    """
    _assert_labels_exist({m for m, _, _ in us_gaap_entries})
    out = []
    for metric_label, _tags, section in us_gaap_entries:
        alternatives = IFRS_ALTERNATIVES.get(metric_label)
        if alternatives:
            out.append((metric_label, alternatives, section))
    return out