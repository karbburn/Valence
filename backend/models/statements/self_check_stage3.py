from __future__ import annotations

from backend.models.statements.pipeline import run


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"Historical model self-check FAILED: {msg}")
    print(f"ok: {msg}")


def main() -> None:
    print("Running Historical 3-Statement Model Pipeline...")
    model = run(target_periods=["FY24", "FY25", "FY26"])

    _assert(len(model.periods) >= 3, f"At least 3 historical periods present ({model.periods})")

    # 1. Income Statement Checks
    for p in model.periods:
        rev = model.income_statement.get_value("canonical.is.revenue", p)
        op = model.income_statement.get_value("canonical.is.operating_profit", p)
        da = model.income_statement.get_value("canonical.is.depreciation_amortization", p)
        ebitda = model.income_statement.get_value("canonical.is.ebitda", p)
        np = model.income_statement.get_value("canonical.is.net_profit", p)

        _assert(rev is not None and rev > 0, f"{p} Revenue present ({rev} Cr)")
        _assert(ebitda is not None and ebitda > 0, f"{p} EBITDA present ({ebitda} Cr)")
        _assert(np is not None and np > 0, f"{p} Net Profit present ({np} Cr)")

        if op is not None and da is not None and ebitda is not None:
            _assert(abs((op + da) - ebitda) <= 1.0, f"{p} P&L Subtotal Check: Operating Profit ({op}) + D&A ({da}) == EBITDA ({ebitda})")

    # 2. Balance Sheet Equality Checks
    for p in model.periods:
        is_balanced = model.balance_sheet.is_balanced_by_period.get(p, False)
        imbalance = model.balance_sheet.imbalance_amount_by_period.get(p, 0.0)
        tot_assets = model.balance_sheet.get_value("canonical.bs.total_assets", p)
        tot_liab_eq = model.balance_sheet.get_value("canonical.bs.total_liabilities_and_equity", p)

        _assert(tot_assets is not None and tot_assets > 0, f"{p} Total Assets present ({tot_assets} Cr)")
        _assert(tot_liab_eq is not None and tot_liab_eq > 0, f"{p} Total Liabilities & Equity present ({tot_liab_eq} Cr)")
        _assert(is_balanced, f"{p} Balance Sheet balances (Assets: {tot_assets} vs Liab+Eq: {tot_liab_eq}, imbalance: {imbalance})")

    # 3. Cash Flow Checks
    for p in model.periods:
        cfo = model.cash_flow_statement.get_value("canonical.cf.operating_activities", p)
        _assert(cfo is not None and cfo > 0, f"{p} Operating Cash Flow present ({cfo} Cr)")

    # 4. Historical Ratio Checks
    for p in model.periods:
        ebitda_m = model.ratios.get_value("ebitda_margin_pct", p)
        net_m = model.ratios.get_value("net_margin_pct", p)
        dso = model.ratios.get_value("dso_days", p)

        _assert(ebitda_m is not None and 15.0 <= ebitda_m <= 40.0, f"{p} EBITDA Margin % valid ({ebitda_m}%)")
        _assert(net_m is not None and 10.0 <= net_m <= 30.0, f"{p} Net Margin % valid ({net_m}%)")
        _assert(dso is not None and dso > 0, f"{p} DSO days valid ({dso} days)")

    if "FY26" in model.periods and "FY25" in model.periods:
        rev_growth = model.ratios.get_value("revenue_growth_yoy", "FY26")
        _assert(rev_growth is not None, f"FY26 Revenue Growth YoY computed ({rev_growth}%)")

    # 5. Lineage Check
    all_items = model.income_statement.line_items + model.balance_sheet.line_items + model.cash_flow_statement.line_items
    has_lineage = any(len(lineage) > 0 for item in all_items for lineage in item.lineage_ids_by_period.values())
    _assert(has_lineage, "Lineage IDs present across statement line items")

    print("\nALL HISTORICAL MODEL SELF-CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
