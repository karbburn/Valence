from __future__ import annotations

from typing import Tuple, Dict

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
    "Investments": ("canonical.bs.current_investments", "bs"),
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
    "Payment of contingent consideration pertaining to acquisition of business": ("canonical.cf.business_acquisitions", "cf"),
    "Interest and dividend received": ("canonical.cf.interest_div_received", "cf"),
    "Escrow and other deposits pertaining to Buyback": ("canonical.cf.escrow_buyback_deposit", "cf"),
    "Redemption of escrow and other deposits pertaining to Buyback": ("canonical.cf.escrow_buyback_deposit", "cf"),
    "Cash from Financing Activity": ("canonical.cf.financing_activities", "cf"),
    "Dividend Amount": ("canonical.cf.dividends_paid", "cf"),
    "Other adjustments": ("canonical.cf.other_adjustments", "cf"),
    "Stock compensation expense": ("canonical.cf.stock_compensation", "cf"),
    "Stock Based Compensation": ("canonical.cf.stock_compensation", "cf"),
    "Share Based Compensation": ("canonical.cf.stock_compensation", "cf"),
    "Share-based compensation expense": ("canonical.cf.stock_compensation", "cf"),
    "Stock-based compensation expense": ("canonical.cf.stock_compensation", "cf"),
    "Net Cash Flow": ("canonical.cf.net_change_in_cash", "cf"),

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
