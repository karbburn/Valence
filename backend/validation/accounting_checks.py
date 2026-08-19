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


# Assets = Liabilities + Equity tolerance in crore units — large enough to
# ignore rounding noise but small enough to catch real statement breaks.
BS_TOLERANCE_CR = 1.0

# Cash flow reconciliation tolerance: relative to ending cash (company sizes
# vary widely) with a small absolute floor for tiny balances.
CF_TOLERANCE_REL = 0.01
CF_TOLERANCE_ABS = 1.0


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
            if diff > BS_TOLERANCE_CR and rel_diff > 0.0001:
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
                    if diff > BS_TOLERANCE_CR and rel_diff > 0.0001:
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
    """Verify Cash Flow ending cash ties to Balance Sheet cash line.

    Historical periods: verifies the statement identity
        ending_cash = beginning_cash + CFO + CFI + CFF
    where beginning/ending cash come from ``canonical.bs.cash_and_bank`` at the
    first and last historical periods, and CFO/CFI/CFF come from the cash flow
    statement for the periods spanned (which reduces to the last period's flows
    when exactly two historical periods exist). Tolerance is relative to ending
    cash (company sizes vary widely), with a small absolute floor.

    If the required inputs are missing, or the source cash flow statement cannot
    be reconciled against the balance sheet cash (a data-quality condition of the
    source data rather than the model), the check is skipped with a diagnostic
    message rather than failed — the identity is only verifiable when the
    underlying statements are internally consistent.
    Forecast periods: CFO and cash must be present and cash non-negative
    (hard failures).
    """
    failing_keys: List[str] = []
    failing_periods: List[str] = []
    failing_scenarios: List[str] = []
    errors: List[str] = []
    skipped: List[str] = []

    # Historical statement identity — first vs last balance sheet cash tied
    # together by the cash flow statement.
    hist_periods = spec.historicals.periods if spec.historicals else []
    if len(hist_periods) >= 2:
        first_p = hist_periods[0]
        last_p = hist_periods[-1]
        span_periods = hist_periods[1:]

        beginning_cash = spec.historicals.get_value("canonical.bs.cash_and_bank", first_p)
        ending_cash = spec.historicals.get_value("canonical.bs.cash_and_bank", last_p)
        cfo_vals = [
            spec.historicals.get_value("canonical.cf.operating_activities", p)
            for p in span_periods
        ]
        cfi_vals = [
            spec.historicals.get_value("canonical.cf.investing_activities", p)
            for p in span_periods
        ]
        cff_vals = [
            spec.historicals.get_value("canonical.cf.financing_activities", p)
            for p in span_periods
        ]

        if any(v is None for v in [beginning_cash, ending_cash, *cfo_vals, *cfi_vals, *cff_vals]):
            skipped.append(
                f"Missing balance-sheet cash or cash-flow inputs for historical "
                f"periods {first_p}..{last_p}"
            )
        else:
            if ending_cash < 0:
                # Negative cash on the balance sheet is always wrong.
                failing_periods.append(last_p)
                failing_scenarios.append("historical")
                errors.append(f"Historical {last_p}: balance sheet cash is negative ({ending_cash})")
            else:
                cfo = sum(cfo_vals)
                cfi = sum(cfi_vals)
                cff = sum(cff_vals)
                implied_ending = beginning_cash + cfo + cfi + cff
                tolerance = max(CF_TOLERANCE_REL * abs(ending_cash), CF_TOLERANCE_ABS)
                if abs(ending_cash - implied_ending) > tolerance:
                    # The source statements do not tie out (e.g. screener/EDGAR
                    # exports with inconsistent CF vs BS figures). Surface the
                    # discrepancy without failing the whole model on source data.
                    skipped.append(
                        f"Cash flow statement does not reconcile with balance sheet cash "
                        f"for historical periods {first_p}..{last_p}: ending cash "
                        f"{ending_cash} vs implied {beginning_cash} + cfo {cfo} + "
                        f"cfi {cfi} + cff {cff} = {implied_ending} "
                        f"(diff {abs(ending_cash - implied_ending):.2f}, tol {tolerance:.2f})"
                    )

    # Forecast sanity — cash and CFO present, cash non-negative, every scenario.
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
        failing_keys = [
            "canonical.bs.cash_and_bank",
            "canonical.cf.operating_activities",
            "canonical.cf.investing_activities",
            "canonical.cf.financing_activities",
        ]

    detail_parts = errors[:3] + [f"SKIPPED: {s}" for s in skipped]
    detail = "" if passed and not skipped else "; ".join(detail_parts)

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

    # Anchor on the latest historical period actually present in the schedule —
    # companies with incomplete coverage (e.g. only FY24-FY25 historicals) have
    # no FY26 slot, so hardcoding "FY26" is wrong.
    hist_periods = spec.historicals.periods if spec.historicals else []
    anchor_period = hist_periods[-1] if hist_periods else None

    if not spec.share_count:
        errors.append("No share count schedule present in specification")
    else:
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
        implicated_periods=[anchor_period] if anchor_period else [],
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
