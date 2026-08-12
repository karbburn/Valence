from __future__ import annotations

"""
Model and Valuation integrity checks module.

Checks:
1. dcf_bridge_reconciles: EV -> Equity Value -> Implied Share Price bridge arithmetic ties out exactly.
2. wacc_valid: WACC > 0%, capital weights sum to 100%, cost of equity > 0%, cost of debt >= 0%.
3. terminal_growth_lt_wacc: Terminal growth rate < WACC for Gordon Growth.
4. no_missing_critical_inputs: All required V1 drivers have assumptions populated without nulls.
"""

from typing import List

from backend.models.spec.drivers import V1_DRIVERS
from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import ModelCheckResult


def check_dcf_bridge_reconciles(spec: ModelSpecification) -> ModelCheckResult:
    """Verify DCF bridge arithmetic (EV -> Equity Value -> Share Price) ties out exactly."""
    errors: List[str] = []
    failing_scenarios: List[str] = []

    if not spec.valuation:
        errors.append("No valuation outputs present in specification")
    else:
        for val in spec.valuation:
            b = val.dcf_bridge
            if b.enterprise_value is None or b.equity_value is None or b.implied_share_price is None:
                errors.append(f"Scenario '{val.scenario}' has null bridge fields")
                failing_scenarios.append(val.scenario)
                continue

            expected_ev = (b.sum_pv_fcff or 0.0) + (b.pv_terminal_value or 0.0)
            if abs(b.enterprise_value - expected_ev) > 0.5:
                errors.append(f"Scenario '{val.scenario}' EV mismatch ({b.enterprise_value} vs {expected_ev:.2f})")
                failing_scenarios.append(val.scenario)

            expected_eq = b.enterprise_value - (b.less_net_debt or 0.0)
            if abs(b.equity_value - expected_eq) > 0.5:
                errors.append(f"Scenario '{val.scenario}' Equity Value mismatch ({b.equity_value} vs {expected_eq:.2f})")
                failing_scenarios.append(val.scenario)

            if b.shares_outstanding and b.shares_outstanding > 0:
                expected_price = b.equity_value / b.shares_outstanding
                if abs(b.implied_share_price - expected_price) > 0.1:
                    errors.append(f"Scenario '{val.scenario}' Price mismatch ({b.implied_share_price} vs {expected_price:.2f})")
                    failing_scenarios.append(val.scenario)

    passed = len(errors) == 0
    detail = "" if passed else "; ".join(errors)

    return ModelCheckResult(
        check_name="dcf_bridge_reconciles",
        category="valuation",
        passed=passed,
        detail=detail,
        implicated_canonical_keys=[],
        implicated_periods=[],
        implicated_scenarios=failing_scenarios,
    )


def check_wacc_valid(spec: ModelSpecification) -> ModelCheckResult:
    """Verify WACC > 0%, capital weights sum to 100%, and non-negative costs."""
    errors: List[str] = []
    failing_scenarios: List[str] = []

    if not spec.valuation:
        errors.append("No valuation outputs present in specification")
    else:
        for val in spec.valuation:
            w = val.wacc
            if w.wacc is None or w.wacc <= 0:
                errors.append(f"Scenario '{val.scenario}' invalid WACC ({w.wacc})")
                failing_scenarios.append(val.scenario)

            if w.equity_weight is not None and w.debt_weight is not None:
                weights_sum = w.equity_weight + w.debt_weight
                if abs(weights_sum - 1.0) > 0.001:
                    errors.append(f"Scenario '{val.scenario}' capital weights sum to {weights_sum:.4f} (expected 1.0)")
                    failing_scenarios.append(val.scenario)

            if w.cost_of_equity is None or w.cost_of_equity <= 0:
                errors.append(f"Scenario '{val.scenario}' non-positive Cost of Equity ({w.cost_of_equity})")
                failing_scenarios.append(val.scenario)

            if w.cost_of_debt is not None and w.cost_of_debt < 0:
                errors.append(f"Scenario '{val.scenario}' negative Cost of Debt ({w.cost_of_debt})")
                failing_scenarios.append(val.scenario)

    passed = len(errors) == 0
    detail = "" if passed else "; ".join(errors)

    return ModelCheckResult(
        check_name="wacc_valid",
        category="valuation",
        passed=passed,
        detail=detail,
        implicated_canonical_keys=[],
        implicated_periods=[],
        implicated_scenarios=failing_scenarios,
    )


def check_terminal_growth_lt_wacc(spec: ModelSpecification) -> ModelCheckResult:
    """Verify terminal growth rate < WACC for Gordon Growth method."""
    errors: List[str] = []
    failing_scenarios: List[str] = []

    if not spec.valuation:
        errors.append("No valuation outputs present in specification")
    else:
        for val in spec.valuation:
            wacc_val = val.wacc.wacc
            tv_g = val.terminal_value.terminal_growth_rate

            if wacc_val is not None and tv_g is not None:
                if tv_g >= wacc_val:
                    errors.append(
                        f"Scenario '{val.scenario}' terminal growth ({tv_g:.2f}%) >= WACC ({wacc_val:.2f}%)"
                    )
                    failing_scenarios.append(val.scenario)

    passed = len(errors) == 0
    detail = "" if passed else "; ".join(errors)

    return ModelCheckResult(
        check_name="terminal_growth_lt_wacc",
        category="valuation",
        passed=passed,
        detail=detail,
        implicated_canonical_keys=[],
        implicated_periods=["terminal"],
        implicated_scenarios=failing_scenarios,
    )


def check_no_missing_critical_inputs(spec: ModelSpecification) -> ModelCheckResult:
    """Verify every V1 driver has non-null assumption objects for all active scenarios."""
    errors: List[str] = []
    failing_keys: List[str] = []
    failing_scenarios: List[str] = []

    required_keys = {d.driver_key for d in V1_DRIVERS}
    for scenario in ["base", "bull", "bear"]:
        scen_assumptions = [a for a in spec.assumptions if a.scenario == scenario]
        found_keys = {a.driver_key for a in scen_assumptions if a.value is not None}
        missing_keys = required_keys - found_keys
        if missing_keys:
            failing_scenarios.append(scenario)
            sorted_missing = sorted(list(missing_keys))
            failing_keys.extend(sorted_missing)
            errors.append(f"Missing driver assumptions for {scenario} scenario: {', '.join(sorted_missing)}")

    passed = len(errors) == 0
    detail = "" if passed else "; ".join(errors)

    return ModelCheckResult(
        check_name="no_missing_critical_inputs",
        category="data_quality",
        passed=passed,
        detail=detail,
        implicated_canonical_keys=sorted(list(set(failing_keys))),
        implicated_periods=[],
        implicated_scenarios=failing_scenarios if failing_scenarios else ["base", "bull", "bear"],
    )



def run_model_checks(spec: ModelSpecification) -> List[ModelCheckResult]:
    """Run all model and valuation checks against specification."""
    return [
        check_dcf_bridge_reconciles(spec),
        check_wacc_valid(spec),
        check_terminal_growth_lt_wacc(spec),
        check_no_missing_critical_inputs(spec),
    ]
