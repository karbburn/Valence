from __future__ import annotations

from typing import Tuple, Dict, FrozenSet

# Labels deliberately NOT mapped, and which must stay unmapped.
#
# WITHDRAWN_LABELS exists because removing an entry from RAW_METRIC_MAP does not
# actually withdraw it. `map_raw_datapoints` falls through to the confidence engine
# when the registry returns None, and that engine proposes these very labels at
# MEDIUM confidence:
#
#     "Investments"  -> canonical.bs.non_current_investments
#     "Other Assets"  -> canonical.bs.other_non_current_assets
#
# So the withdrawals recorded in this file were inert. Screener's "Investments"
# aggregate kept publishing -- it simply moved from the current-asset key to the
# non-current one, so Infosys showed 21,880 of non-current investments against a
# filed 8,930 and the double count survived the fix that was meant to end it.
#
# A medium-confidence suggestion is a guess, and it must not overrule a decision
# that was made on evidence. Each label here is one where the figure is an AGGREGATE
# the filer did not print as a caption, so mapping it to a narrow key states
# something the engine does not know. The reasoning for each is at its would-be entry
# below; `current_assets_reconcile` reports the resulting shortfall.
#
# "Other equity" and "Equity attributable to shareholders of the Company" are the
# same class of error from the other direction: genuine filed captions the engine
# maps to the WRONG key. TCS prints Share capital 362 + Other equity 106,878 =
# Equity attributable 107,240, + Non-controlling 1,238 = Total equity 108,478
# (FY26 consolidated), yet the engine suggests "Other equity" -> total_equity at
# 0.58 and the rupee subtotal "Equity attributable..." -> share_count at 0.47, and
# the mapper accepts both. The first double-counts the total; the second puts
# rupees in a share-count key. Neither has an unambiguous home in the current
# key set -- "Other equity" is a component with no component key, and the
# attributable subtotal differs from the total by the minority interest -- so both
# stay withdrawn until those keys exist.
#
# HCLTech's liabilities face adds three more of the same family, found by parsing
# printed page 6 caption by caption. "Equity attributable to owners of the Company"
# (7,761) is suggested to net_profit at 0.57 -- an equity subtotal mapped into the
# profit-and-loss statement, worse than the share_count case because the key is at
# least a rupee key. "Deferred tax liabilities (net)" (152) and "Current tax
# liabilities (net)" (363) are suggested to the corresponding ASSET keys at 0.58 --
# liabilities mapped across the balance sheet into assets. No liability key exists
# for either, and a liability parked in an asset key inverts the statement, so all
# three stay withdrawn. The current-liabilities face foots exactly (3,099) WITH these
# rows present, which is what makes their absence from the model a recorded shortfall
# rather than a rounding difference.
WITHDRAWN_LABELS: FrozenSet[str] = frozenset({
    "Investments",
    "Other Assets",
    "Other equity",
    "Equity attributable to shareholders of the Company",
    "Equity attributable to owners of the Company",
    "Deferred tax liabilities (net)",
    "Current tax liabilities (net)",
    # A second family: captions the FILER prints, read from the statement pages
    # themselves, where either no canonical key exists or the label cannot pick
    # one. Withdrawn rather than left unmapped because an unmapped caption reads
    # as an accident and these are decisions; the review queue records the name
    # either way.
    #
    # Cash-flow and OCI detail the model does not consume. The section totals they
    # roll into are mapped from the filing's own subtotal captions, so the statement
    # is complete without them, and the suggestion engine rates every one of these
    # low confidence (0.2, no key), so there is no adjacent key quietly waiting to
    # absorb them. The one adjacent-looking case is recorded here rather than
    # mapped: "Expenditure on property, plant and equipment and intangibles" is the
    # filing's capex line, and two documents word it differently for the same year
    # ("... and intangibles" against "... and intangibles, net of sale proceeds"),
    # so a single capex key would hold whichever caption parsed last under a
    # meaning that differs by document. Filling capex would also give the forecast
    # a new anchor where it currently falls back to depreciation, which is a
    # product decision, not a lookup.
    "Deposits placed with corporation",
    "Redemption of deposits placed with corporation",
    "Expenditure on property, plant and equipment and intangibles",
    "Expenditure on property, plant and equipment and intangibles, net of sale proceeds (Refer",
    "Impairment loss recognized/(reversed) under expected credit loss model",
    "Exchange differences on translation of assets and liabilities, net",
    "Other receipts",
    "Other payments",
    "Loan repayment of in-tech Holding GmbH",
    "Loan repayment of in-tech Holding GmbH (Refer to note 2.10)",
    "Shares issued on exercise of employee stock options",
    "Payment of dividends to non-controlling interests of subsidiary",
    "Payment towards purchase of non-controlling interest",
    # Comprehensive income and its components. The key set has no comprehensive-
    # income entry, so there is nowhere honest to file them, and "Equity
    # instruments through other comprehensive income, net" is printed on the
    # income-statement page while being an equity balance, which is the
    # cross-statement mistake the caption check exists to prevent.
    "Total comprehensive income",
    "Total other comprehensive income/(loss), net of tax",
    "Equity instruments through other comprehensive income, net",
    "Exchange differences on translation of foreign operations",
    "Fair value changes on investments, net",
    "Remeasurement of the net defined benefit liability/asset, net",
    # Balance-sheet lines without one unambiguous home. "Employee benefit
    # obligations" is printed TWICE per document under the same words with
    # different amounts (3,524 non-current against 117 current at FY26), and both
    # rows arrive tagged [noncurrent], so one key would hold two figures for one
    # period and the winner would be row order -- the ambiguity `bs_half` exists
    # to answer, which a label mapping cannot. "Share premium" is a component of
    # reserves, and the only reserve key already carries Screener's "Reserves"
    # aggregate, so filing the component beside the aggregate is the same shape
    # that put a whole equity stack under one line. "Right-of-use assets" has no
    # key at all.
    "Right-of-use assets",
    "Share premium",
    "Employee benefit obligations",
    # Third family: captions the engine does reach, at the wrong destination.
    # Each is a real printed line whose only suggestion states something false
    # about it, so the mapping is withdrawn rather than accepted, and the wrong
    # figure stays out of the model the same way as the families above. All
    # five are printed only by Infosys; no other company's rows are touched.
    #
    # "Cash generated from operations" (35,297 / 42,388 / 44,472) is the
    # operating section's pre-tax subtotal, and the filing prints the section's
    # own total on the line below it ("Net cash generated by operating
    # activities", 26,066 / 36,786 / 35,824): the two differ by exactly the
    # taxes-paid line the statement prints separately (9,231 / 5,602 / 8,648).
    # Both captions suggest operating_activities at the same score, so which
    # figure the key would publish is row order, and the pre-tax one is the
    # wrong answer for a line the statement labels Cash Flow from Operating
    # Activities.
    "Cash generated from operations",
    # "Deferred income tax liabilities" (1,794 / 1,722 / 1,679) is parked on
    # the DEFERRED TAX ASSET key. No liability key exists -- the same reason
    # HCLTech's "Deferred tax liabilities (net)" is withdrawn above -- and the
    # asset row wins each period only because assets print above liabilities
    # on the page, which is order again rather than evidence. A liability
    # parked in an asset key inverts the statement.
    "Deferred income tax liabilities",
    # "Interest and dividend income" ((1,138) / (1,168) / (1,125)) is the
    # operating-section adjustment that removes that income from profit before
    # tax, and the engine parks it on the Interest & Dividends Received line,
    # which counts cash coming in. The filing prints the cash line too
    # ("Interest and dividend received", 912 / 948 / 875), which is mapped, and
    # it wins each period today only on the positive-value boost; a deduction
    # should not be a rival of the receipt it adjusts.
    "Interest and dividend income",
    # "Total equity attributable to equity holders of the Company"
    # (88,116 / 95,818 / 92,852) is the total LESS non-controlling interests
    # (345 / 385 / 445, exact in all three years), and the engine parks it on
    # total_equity beside the filing's own "Total equity" caption
    # (88,461 / 96,203 / 93,297, mapped above). The primary-label boost keeps
    # the inclusive figure selected, but a component beside its own total in
    # one key is the "Other equity" shape recorded at the top of this file, and
    # there is no key for the attributable subtotal.
    "Total equity attributable to equity holders of the Company",
    # "authorized, issued and outstanding 4,143,607,528 (4,139,950,635) equity"
    # (2,071 / 2,073) is the equity share capital row read together with its
    # share-count note text; the figure itself is printed again by the filer's
    # own "Equity Share Capital" caption for the same periods (2,071 / 2,073,
    # mapped above), so nothing is lost by refusing the fragment, and the
    # engine parks it on total liabilities and equity.
    "authorized, issued and outstanding 4,143,607,528 (4,139,950,635) equity",
    # One more label for a different reason: the cash-flow statement keeps the
    # LAST canonical row it sees for a key and period instead of scoring the
    # candidates, so when both of these captions map to business_acquisitions
    # the page order decides which figure publishes. On the FY26 page the
    # contingent line prints BELOW the acquisition line (y=506.2 under y=495.2)
    # and its (13) overwrites the filing's own (637), so the model published
    # (13) under the label "Payment for Business Acquisitions" while the filing
    # prints (637) on the line that carries that name. The two figures are also
    # different things: the acquisition line is the year's purchases of
    # businesses net of cash acquired, while the contingent line settles
    # consideration for acquisitions already made (the (101) at FY24, the (13)
    # at FY26). With no ordering that prefers authority, the caption that IS
    # the line keeps the key and the settlement detail is withdrawn like the
    # other disclosed detail; the FY24 headline line prints a dash, so that
    # year's cell goes empty instead of holding a settlement. Printed by
    # Infosys only.
    "Payment of contingent consideration pertaining to acquisition of business",
    # And the escrow pair, where the same one-row-per-key rule publishes one
    # side of a movement the filing prints twice. FY26 shows deposits placed
    # (1,815) at y=517.2 and redemptions received 1,815 at y=528.3, netting to
    # zero for the year; the redemption prints last, so the model published
    # 1,815 as the year's escrow line while the deposit sat shadowed, a net
    # cash effect the filing contradicts with its own two lines. No printed
    # figure represents the net, so both captions go, the same disposition as
    # the deposit and redemption pair recorded above without a key. The line is
    # empty for this company rather than showing one side of a pair, and the
    # figures were published this same one-sided way before the migration, so
    # this corrects a standing figure. Printed by Infosys only.
    "Escrow and other deposits pertaining to Buyback",
    "Redemption of escrow and other deposits pertaining to Buyback",
})

# Mapping entry type: (canonical_key, statement)
RAW_METRIC_MAP: Dict[str, Tuple[str, str]] = {
    # --- Income Statement ---
    "Revenues": ("canonical.is.revenue", "is"),
    "Sales": ("canonical.is.revenue", "is"),
    "Cost of sales": ("canonical.is.cost_of_sales", "is"),
    "Raw Material Cost": ("canonical.is.cost_of_sales", "is"),
    "Gross profit": ("canonical.is.gross_profit", "is"),
    "Research and development": ("canonical.is.research_development", "is"),
    "Selling and admin": ("canonical.is.selling_admin_exp", "is"),
    "Selling and marketing": ("canonical.is.sales_marketing", "is"),
    "General and administrative": ("canonical.is.general_admin", "is"),
    "Administrative expenses": ("canonical.is.selling_admin_exp", "is"),
    "Employee Cost": ("canonical.is.employee_cost", "is"),
    "Other Mfr. Exp": ("canonical.is.other_mfr_exp", "is"),
    "Power and Fuel": ("canonical.is.power_fuel", "is"),
    "Other Expenses": ("canonical.is.other_exp", "is"),
    "Total operating expenses": ("canonical.is.total_opex", "is"),
    "Operating profit": ("canonical.is.operating_profit", "is"),
    "Depreciation": ("canonical.is.depreciation_amortization", "is"),
    "Depreciation and amortization": ("canonical.is.depreciation_amortization", "is"),
    "Finance cost": ("canonical.is.finance_cost", "is"),
    "Interest": ("canonical.is.finance_cost", "is"),
    "Other Income": ("canonical.is.other_income", "is"),
    "Other income, net": ("canonical.is.other_income", "is"),
    "Interest receivable on income tax refund": ("canonical.is.other_income", "is"),
    "Profit before tax": ("canonical.is.pbt", "is"),
    "Profit before income taxes": ("canonical.is.pbt", "is"),
    "Tax": ("canonical.is.tax", "is"),
    "Income tax expense": ("canonical.is.tax", "is"),
    "Net Profit": ("canonical.is.net_profit", "is"),
    "Net profit": ("canonical.is.net_profit", "is"),
    "Owners of the Company": ("canonical.is.net_profit", "is"),
    "Non-controlling interests": ("canonical.is.non_controlling_interests", "is"),
    "Basic (₹)": ("canonical.is.eps_basic", "is"),
    "Basic (in shares) 2.13 4,046,019,309": ("canonical.is.eps_basic", "is"),
    "Basic (in Rs)": ("canonical.is.eps_basic", "is"),
    # The SEC ingestion emits these for a US filer, in dollars per share. Without
    # them the diluted share count cannot be derived from the filed figures and
    # falls through to the live provider, which is where NVIDIA's 24,147m came from
    # while its filing carried 24,304m shares outstanding.
    "Basic (in $)": ("canonical.is.eps_basic", "is"),
    "Diluted (in $)": ("canonical.is.eps_diluted", "is"),
    "Diluted (₹)": ("canonical.is.eps_diluted", "is"),
    "Diluted (in Rs)": ("canonical.is.eps_diluted", "is"),
    "EPS in Rs": ("canonical.is.eps_diluted", "is"),
    "EPS in Rs.": ("canonical.is.eps_diluted", "is"),

    # --- Balance Sheet (Assets) ---
    "Net Block": ("canonical.bs.ppe", "bs"),
    # Gross asset base and accumulated depreciation. Both are needed to measure the
    # depreciation rate the steady-state capex target is built on; see
    # backend/forecast/assumptions.py.
    "Gross Block": ("canonical.bs.ppe_gross", "bs"),
    "Accumulated Depreciation": ("canonical.bs.accumulated_depreciation", "bs"),
    "Capital Work in Progress": ("canonical.bs.cwip", "bs"),
    "Goodwill": ("canonical.bs.goodwill", "bs"),
    "Intangible assets": ("canonical.bs.intangible_assets", "bs"),
    "Non-current investments": ("canonical.bs.non_current_investments", "bs"),
    "Deferred income tax assets": ("canonical.bs.deferred_tax_assets", "bs"),
    "Income tax assets": ("canonical.bs.income_tax_assets", "bs"),
    "Other non-current assets": ("canonical.bs.other_non_current_assets", "bs"),
    "Total non-current assets": ("canonical.bs.total_non_current_assets", "bs"),
    "Current investments": ("canonical.bs.current_investments", "bs"),
    # NOT "Investments", for the same reason as "Other Assets" above: Screener's
    # Data Sheet prints an aggregate, not the filer's caption.
    #
    # Infosys' own balance sheet separates them -- "Current investments 12,950" and
    # "Non-current investments 8,930" -- and Screener collapses both into one
    # "Investments" row reading 21,880. Mapped to the CURRENT line that is the
    # whole total, and `Non-current investments` is read separately, so the money is
    # counted twice:
    #
    #     FY24  12,915 current + 11,708 non-current = 24,623  published as current
    #     FY25  12,482 current + 11,059 non-current = 23,541  published as current
    #     FY26  12,950 current +  8,930 non-current = 21,880  published as current
    #
    # Exact to the rupee in all three years, which is what identifies it: the
    # published current figure equals current PLUS non-current precisely.
    #
    # The honest position is the one taken for "Other Assets": the engine does not
    # know how much of that total is current, so it does not claim to. An
    # under-count is visible and checkable, and `current_assets_reconcile` reports
    # the shortfall. An over-count wearing a filed caption's name is neither.
    #
    # A filer that prints a line genuinely captioned "Current investments" reaches
    # this key through that caption, below.
    "Current investments": ("canonical.bs.current_investments", "bs"),
    "- Certificates of deposit": ("canonical.bs.current_investments", "bs"),
    "- Commercial paper": ("canonical.bs.current_investments", "bs"),
    "- Mutual fund units": ("canonical.bs.current_investments", "bs"),
    "- Other investments": ("canonical.bs.current_investments", "bs"),
    "- Quoted debt securities": ("canonical.bs.current_investments", "bs"),
    "- Target maturity funds units": ("canonical.bs.current_investments", "bs"),
    "Vendor non-trade receivables": ("canonical.bs.vendor_non_trade_receivables", "bs"),
    "Receivables": ("canonical.bs.trade_receivables", "bs"),
    "Trade receivables": ("canonical.bs.trade_receivables", "bs"),
    "Trade receivables and unbilled revenue": ("canonical.bs.trade_receivables", "bs"),
    "Unbilled revenue": ("canonical.bs.unbilled_revenue", "bs"),
    "Inventory": ("canonical.bs.inventory", "bs"),
    "Cash & Bank": ("canonical.bs.cash_and_bank", "bs"),
    "Cash and cash equivalents": ("canonical.bs.cash_and_bank", "bs"),
    "Prepayments and other assets": ("canonical.bs.prepayments_other_current_assets", "bs"),
    # The filer's own caption. Screener and the PDF reader print different words for
    # the same line, and only one of them was listed, so Infosys' balance sheet lost
    # the line entirely: it prints "Prepayments and other current assets 15,703" and
    # that label matched nothing, leaving the key to be filled by the cash-flow
    # statement's "Prepayments and other assets (2,312)".
    #
    # With both captions present the filed figure wins and the movement is refused
    # for being a cash-flow caption (see mapper._statement_agrees).
    "Prepayments and other current assets": ("canonical.bs.prepayments_other_current_assets", "bs"),
    # NOT "Other Assets". Screener.in's Data Sheet groups the balance sheet by
    # analysis rather than by caption, and its "Other Assets" row is a broad
    # aggregate: for Infosys at 2026-03-31 it reads 98,112 while the lines beneath
    # it on the same sheet are cash 22,201, investments 21,880 and receivables
    # 35,234, so it already contains them. Mapped to the narrow current-asset
    # catch-all it made the itemised block sum to 192,910 against a filed
    # current-asset subtotal of 103,489, and the engine published a balance sheet
    # that nearly doubled the filer's own total.
    #
    # The honest position is that the engine does not know what that money is. An
    # under-count is visible and checkable; an over-count dressed as a named line is
    # neither, and `current_assets_reconcile` now reports the shortfall rather than
    # leaving it to be found by a reader.
    #
    # A filer whose own balance sheet prints a line captioned "Other Assets" is a
    # different thing, and reaches the same key through that filer's own caption
    # list rather than through this aggregator.
    "Current income tax assets": ("canonical.bs.current_income_tax_assets", "bs"),
    "Current derivative financial assets": ("canonical.bs.derivative_financial_assets_current", "bs"),
    # The filer's own caption. Infosys prints "Derivative financial instruments" on
    # both sides of its balance sheet -- 83 in current assets and 593 in current
    # liabilities -- without the word "current" on the asset side. Without this the
    # 83 did not reach the reconciliation at all, leaving it short by exactly that.
    "Derivative financial instruments": ("canonical.bs.derivative_financial_assets_current", "bs"),
    "Total current assets": ("canonical.bs.total_current_assets", "bs"),
    "Total assets": ("canonical.bs.total_assets", "bs"),
    "Total Assets": ("canonical.bs.total_assets", "bs"),
    "Total_Asset": ("canonical.bs.total_assets", "bs"),

    # --- Balance Sheet (Liabilities & Equity) ---
    "Equity Share Capital": ("canonical.bs.equity_capital", "bs"),
    "Retained earnings": ("canonical.bs.retained_earnings", "bs"),
    "Reserves": ("canonical.bs.other_reserves", "bs"),
    "Other reserves": ("canonical.bs.other_reserves", "bs"),
    "Capital redemption reserve": ("canonical.bs.other_reserves", "bs"),
    "Cash flow hedge reserves": ("canonical.bs.other_reserves", "bs"),
    "Total equity": ("canonical.bs.total_equity", "bs"),
    "Borrowings": ("canonical.bs.borrowings", "bs"),
    "Short term borrowings": ("canonical.bs.short_term_borrowings", "bs"),
    "Finance lease liabilities": ("canonical.bs.finance_lease_liabilities", "bs"),
    "Operating lease liabilities": ("canonical.bs.operating_lease_liabilities", "bs"),
    "Mezzanine equity": ("canonical.bs.mezzanine_equity", "bs"),
    "Total mezzanine equity": ("canonical.bs.mezzanine_equity", "bs"),
    "Mezzanine": ("canonical.bs.mezzanine_equity", "bs"),
    "Redeemable noncontrolling interest": ("canonical.bs.mezzanine_equity", "bs"),
    "Minority interest": ("canonical.bs.minority_interest", "bs"),
    "Non-controlling interests": ("canonical.bs.minority_interest", "bs"),
    "Non-controlling interest": ("canonical.bs.minority_interest", "bs"),
    "Preference share capital": ("canonical.bs.preferred_stock", "bs"),
    "Preferred stock": ("canonical.bs.preferred_stock", "bs"),
    "Trade payables": ("canonical.bs.trade_payables", "bs"),
    "Unearned revenue": ("canonical.bs.unearned_revenue", "bs"),
    "Lease liabilities": ("canonical.bs.lease_liabilities", "bs"),
    "Other current liabilities": ("canonical.bs.other_current_liabilities", "bs"),
    "Other Liabilities": ("canonical.bs.other_current_liabilities", "bs"),
    "Other non-current liabilities": ("canonical.bs.other_non_current_liabilities", "bs"),
    "Other liabilities and provisions": ("canonical.bs.other_non_current_liabilities", "bs"),
    "Provision for post sale client support and other provisions": ("canonical.bs.provisions", "bs"),
    "Provisions": ("canonical.bs.provisions", "bs"),
    "Billed": ("canonical.bs.trade_receivables", "bs"),
    "Inventories": ("canonical.bs.inventory", "bs"),
    "Capital work-in-progress": ("canonical.bs.cwip", "bs"),
    "Class B compulsorily convertible preference shares": ("canonical.bs.preferred_stock", "bs"),
    "Dues of creditors other than small enterprises and micro enterprises": ("canonical.bs.trade_payables", "bs"),
    "Dues of small enterprises and micro enterprises": ("canonical.bs.trade_payables", "bs"),
    "Other balances with banks": ("canonical.bs.cash_and_bank", "bs"),
    "Investments accounted for using the equity method": ("canonical.bs.non_current_investments", "bs"),
    "Total current liabilities": ("canonical.bs.total_current_liabilities", "bs"),
    "Total non-current liabilities": ("canonical.bs.total_non_current_liabilities", "bs"),
    "Total liabilities": ("canonical.bs.total_liabilities", "bs"),
    "Total liabilities and equity": ("canonical.bs.total_liabilities_and_equity", "bs"),
    "Total Liabilities & Equity": ("canonical.bs.total_liabilities_and_equity", "bs"),
    "Total_Liab": ("canonical.bs.total_liabilities", "bs"),

    # --- Cash Flow Statement ---
    "Cash from Operating Activity": ("canonical.cf.operating_activities", "cf"),
    "Income taxes paid": ("canonical.cf.taxes_paid", "cf"),
    "Cash from Investing Activity": ("canonical.cf.investing_activities", "cf"),
    "PaymentsToAcquirePropertyPlantAndEquipment": ("canonical.cf.capex", "cf"),
    "PaymentsToAcquireProductiveAssets": ("canonical.cf.capex", "cf"),
    "Capital Expenditure": ("canonical.cf.capex", "cf"),
    "Purchase of Property, Plant and Equipment": ("canonical.cf.capex", "cf"),
    "Fixed Assets Purchased": ("canonical.cf.capex", "cf"),
    "Payment for acquisition of business, net of cash acquired": ("canonical.cf.business_acquisitions", "cf"),
    "Interest and dividend received": ("canonical.cf.interest_div_received", "cf"),
    "Cash from Financing Activity": ("canonical.cf.financing_activities", "cf"),
    "Dividend Amount": ("canonical.cf.dividends_paid", "cf"),
    # The filing's own caption, read from the financing section on the continuation
    # page of both Infosys documents (printed 105 under 104, printed 111 under 110):
    # (14,692) FY24, (20,287) FY25, (18,653) FY26. The key was empty for this
    # company until now -- the aggregator's "Dividend Amount" rows are refused by
    # the statement guard, so the model's dividends line fell back to whatever the
    # forecast assumed. The dividends-to-minority line printed beside it is
    # withdrawn (see WITHDRAWN_LABELS) so the key carries one figure per period
    # rather than two rivals the selector would order arbitrarily.
    "Payment of dividends": ("canonical.cf.dividends_paid", "cf"),
    "Other adjustments": ("canonical.cf.other_adjustments", "cf"),
    "Stock compensation expense": ("canonical.cf.stock_compensation", "cf"),
    "Stock Based Compensation": ("canonical.cf.stock_compensation", "cf"),
    "Share Based Compensation": ("canonical.cf.stock_compensation", "cf"),
    "Share-based compensation expense": ("canonical.cf.stock_compensation", "cf"),
    "Stock-based compensation expense": ("canonical.cf.stock_compensation", "cf"),
    "Net Cash Flow": ("canonical.cf.net_change_in_cash", "cf"),
    # The filing prints its own section totals on the statement page, and the
    # confidence engine sends three of the four captions to net_change_in_cash,
    # where a section total would rival the actual bottom line -- the operating
    # one wins it, 35,824 at FY26 against the reported net change. Mapped to
    # their own sections the statement adds up, which is the relationship the
    # model derives the bottom line from: the three filed sections sum to the
    # filing's own printed net-increase caption exactly, (3,854) at FY26,
    # 9,587 at FY25 and 2,697 at FY24, each verified against the documents
    # (operating + investing + financing, and the captions carry one figure per
    # period).
    "Net cash generated by operating activities": ("canonical.cf.operating_activities", "cf"),
    "Net cash generated/(used) in investing activities": ("canonical.cf.investing_activities", "cf"),
    "Net cash generated from investing activities": ("canonical.cf.investing_activities", "cf"),
    "Net cash used in financing activities": ("canonical.cf.financing_activities", "cf"),
    # The filing's printed bottom line, on the continuation page under the three
    # sections. It disagrees with the aggregator's "Net Cash Flow" ((3,854)
    # against (2,254) at FY26) because the aggregator's figure folds in the
    # exchange effect the filing prints on its own line, (1,600) at FY26: the
    # roll-forward closes either way, 24,455 + (3,854) + 1,600 = 22,201. The
    # model publishes the sum of the three sections for this line, so choosing
    # the filing's caption keeps the reported figure identical to that sum
    # instead of logging a disagreement on every rebuild.
    "Net increase/(decrease) in cash and cash equivalents": ("canonical.cf.net_change_in_cash", "cf"),

    "No. of Equity Shares": ("canonical.meta.share_count", "meta"),
    "Basic (in shares)": ("canonical.meta.share_count", "meta"),
    "4,052,169,447": ("canonical.meta.share_count", "meta"),
    "Face value": ("canonical.meta.face_value", "meta"),
    "New Bonus Shares": ("canonical.meta.bonus_shares", "meta"),
    "Total Liabilities Net Minority Interest": ("canonical.bs.total_liabilities", "bs"),
    "Total Non Current Liabilities Net Minority Interest": ("canonical.bs.total_non_current_liabilities", "bs"),
}


def get_canonical_mapping(metric_raw: str) -> Tuple[str, str] | None:
    """Return (canonical_key, statement) for a raw metric label, or None if unmapped."""
    return RAW_METRIC_MAP.get(metric_raw.strip())
