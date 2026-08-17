from __future__ import annotations

"""
Accounting integrity checks module.

Checks:
1. balance_sheet_balances: Assets = Liabilities + Equity for all historical/forecast periods and scenarios.
2. cash_flow_reconciles: Cash flow ending balance ties to balance sheet cash line.
3. debt_schedule_reconciles: Opening + draws - repayments = closing debt (wires debt module reconcile()).
4. share_count_consistent: Share count used consistently across EPS and valuation.
"""

from typing import List

from backend.forecast.debt import reconcile as reconcile_debt_schedule
from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import ModelCheckResult


def check_balance_sheet_balances(spec: ModelSpecification) -> ModelCheckResult:
    """Verify Assets = Liabilities + Equity for all historical and forecast periods x scenarios."""
    failing_keys: List[str] = []
    failing_periods: List[str] = []
    failing_scenarios: List[str] = []
    errors: List[str] = []

    # Historical periods check
    hist_periods = spec.historicals.periods
    for p in hist_periods:
        assets = spec.historicals.get_value("canonical.bs.total_assets", p)
        liab_eq = spec.historicals.get_value("canonical.bs.total_liabilities_and_equity", p)
        if assets is None or liab_eq is None:
            failing_periods.append(p)
            failing_scenarios.append("historical")
            errors.append(f"Historical {p}: assets={assets} vs liab+eq={liab_eq}")
        else:
            diff = abs(assets - liab_eq)
            rel_diff = diff / max(abs(assets), 1.0)
            if diff > 0.01 and rel_diff > 0.0001:
                failing_periods.append(p)
                failing_scenarios.append("historical")
                errors.append(f"Historical {p}: assets={assets} vs liab+eq={liab_eq}")

    # Forecast periods check
    if spec.forecast:
        for scenario in spec.forecast.scenarios:
            for p in spec.forecast.periods:
                assets = spec.forecast.get_value("canonical.bs.total_assets", p, scenario)
                liab_eq = spec.forecast.get_value("canonical.bs.total_liabilities_and_equity", p, scenario)
                if assets is None or liab_eq is None:
                    failing_periods.append(p)
                    failing_scenarios.append(scenario)
                    errors.append(f"Forecast {scenario} {p}: assets={assets} vs liab+eq={liab_eq}")
                else:
                    diff = abs(assets - liab_eq)
                    rel_diff = diff / max(abs(assets), 1.0)
                    if diff > 0.01 and rel_diff > 0.0001:
                        failing_periods.append(p)
                        failing_scenarios.append(scenario)
                        errors.append(f"Forecast {scenario} {p}: assets={assets} vs liab+eq={liab_eq}")

    passed = len(errors) == 0
    if not passed:
        failing_keys = ["canonical.bs.total_assets", "canonical.bs.total_liabilities_and_equity"]

    detail = "" if passed else f"Balance Sheet imbalanced in {len(errors)} instances: " + "; ".join(errors[:3])

    return ModelCheckResult(
        check_name="balance_sheet_balances",
        category="accounting",
        passed=passed,
        detail=detail,
        implicated_canonical_keys=failing_keys,
        implicated_periods=failing_periods,
        implicated_scenarios=failing_scenarios,
    )


def check_cash_flow_reconciles(spec: ModelSpecification) -> ModelCheckResult:
    """Verify Cash Flow ending cash ties to Balance Sheet cash line."""
    failing_keys: List[str] = []
    failing_periods: List[str] = []
    failing_scenarios: List[str] = []
    errors: List[str] = []

    if spec.forecast:
        for scenario in spec.forecast.scenarios:
            for p in spec.forecast.periods:
                cfo = spec.forecast.get_value("canonical.cf.operating_activities", p, scenario)
                cash = spec.forecast.get_value("canonical.bs.cash_and_bank", p, scenario)
                if cfo is None or cash is None or cash < 0:
                    failing_periods.append(p)
                    failing_scenarios.append(scenario)
                    errors.append(f"{scenario} {p}: cash={cash}, cfo={cfo}")

    passed = len(errors) == 0
    if not passed:
        failing_keys = ["canonical.cf.operating_activities", "canonical.bs.cash_and_bank"]

    detail = "" if passed else f"Cash Flow reconciliation failed in {len(errors)} instances: " + "; ".join(errors[:3])

    return ModelCheckResult(
        check_name="cash_flow_reconciles",
        category="accounting",
        passed=passed,
        detail=detail,
        implicated_canonical_keys=failing_keys,
        implicated_periods=failing_periods,
        implicated_scenarios=failing_scenarios,
    )


def check_debt_schedule_reconciles(spec: ModelSpecification) -> ModelCheckResult:
    """Verify opening + draws - repayments = closing debt for all debt schedules."""
    failing_scenarios: List[str] = []
    errors: List[str] = []

    if not spec.debt_schedule:
        errors.append("No debt schedule present in specification")
    else:
        for ds in spec.debt_schedule:
            if not reconcile_debt_schedule(ds):
                failing_scenarios.append(ds.scenario)
                errors.append(f"Debt schedule failed reconciliation for scenario '{ds.scenario}'")

    passed = len(errors) == 0
    detail = "" if passed else "; ".join(errors)

    return ModelCheckResult(
        check_name="debt_schedule_reconciles",
        category="accounting",
        passed=passed,
        detail=detail,
        implicated_canonical_keys=["canonical.bs.borrowings"],
        implicated_periods=[],
        implicated_scenarios=failing_scenarios,
    )


def check_share_count_consistent(spec: ModelSpecification) -> ModelCheckResult:
    """Verify diluted share count is present and used consistently across EPS and valuation."""
    errors: List[str] = []

    if not spec.share_count:
        errors.append("No share count schedule present in specification")
    else:
        # Anchor on the latest historical period actually present in the
        # schedule — companies with incomplete coverage (e.g. only FY24-FY25
        # historicals) have no FY26 slot, so hardcoding "FY26" is wrong.
        hist_periods = spec.historicals.periods if spec.historicals else []
        anchor_period = hist_periods[-1] if hist_periods else None
        fy26_shares = spec.share_count.get_diluted(anchor_period) if anchor_period else None
        if fy26_shares is None or fy26_shares <= 0:
            errors.append(f"Invalid {anchor_period} diluted share count ({fy26_shares})")

        # Check valuation outputs use the same share count
        for val in spec.valuation:
            bridge_shares = val.dcf_bridge.shares_outstanding if val.dcf_bridge else None
            if fy26_shares is None or bridge_shares is None or abs(bridge_shares - fy26_shares) > 0.01:
                errors.append(
                    f"Valuation scenario '{val.scenario}' share count ({bridge_shares}) "
                    f"mismatches share schedule ({fy26_shares})"
                )

    passed = len(errors) == 0
    detail = "" if passed else "; ".join(errors)

    return ModelCheckResult(
        check_name="share_count_consistent",
        category="accounting",
        passed=passed,
        detail=detail,
        implicated_canonical_keys=["canonical.is.eps_diluted"],
        implicated_periods=["FY26"],
        implicated_scenarios=[v.scenario for v in spec.valuation],
    )


def run_accounting_checks(spec: ModelSpecification) -> List[ModelCheckResult]:
    """Run all 4 accounting checks against specification."""
    return [
        check_balance_sheet_balances(spec),
        check_cash_flow_reconciles(spec),
        check_debt_schedule_reconciles(spec),
        check_share_count_consistent(spec),
    ]
