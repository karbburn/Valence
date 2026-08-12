from __future__ import annotations

"""
Self-check for Stage 8: QA / Model Checks Engine.

Acceptance criteria:
  1. All V1 checks pass for Infosys Base specification (summary_label == "MODEL VALID").
  2. Each check demonstrably fails against a synthetic bad input case.
  3. QAResults status rollup (all_passed, failed_count, summary_label) functions correctly.
  4. ModelSpecification serialization preserves spec.qa intact.
"""

from backend.forecast.debt import DebtPeriod, DebtSchedule
from backend.forecast.pipeline import run as run_forecast_pipeline
from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.forecast import ForecastLineItem
from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.valuation import WACCBreakdown
from backend.validation.accounting_checks import (
    check_balance_sheet_balances,
    check_cash_flow_reconciles,
    check_debt_schedule_reconciles,
    check_share_count_consistent,
)
from backend.validation.model_checks import (
    check_dcf_bridge_reconciles,
    check_no_missing_critical_inputs,
    check_terminal_growth_lt_wacc,
    check_wacc_valid,
)
from backend.validation.pipeline import run_qa
from backend.valuation.pipeline import run_valuation


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"Stage 8 self-check FAILED: {msg}")
    print(f"ok: {msg}")


def main() -> None:
    print("Running Stage 8 QA Engine self-check...")
    forecast_spec = run_forecast_pipeline()
    val_spec = run_valuation(forecast_spec)
    spec = run_qa(val_spec)

    # ------------------------------------------------------------------ #
    # 1. Infosys Base Model is MODEL VALID
    # ------------------------------------------------------------------ #
    _assert(spec.qa is not None, "spec.qa is populated")
    _assert(spec.qa.all_passed, "all QA checks passed for Infosys model")
    _assert(spec.qa.failed_count == 0, f"failed_count == 0 (got {spec.qa.failed_count})")
    _assert(spec.qa.summary_label == "MODEL VALID", f"summary_label == 'MODEL VALID' (got '{spec.qa.summary_label}')")

    # ------------------------------------------------------------------ #
    # 2. Synthetic Failure Tests — Each check fails on bad input
    # ------------------------------------------------------------------ #

    # 2a. Balance Sheet Imbalance Check Failure
    bad_spec_bs = spec.model_copy(deep=True)
    # Inject imbalanced forecast line item
    bad_item = ForecastLineItem(
        canonical_key="canonical.bs.total_assets",
        period_label="FY27",
        period_end_date="2027-03-31",  # type: ignore
        value=999999.0,  # Huge imbalance
        scenario="base",
    )
    bad_spec_bs.forecast.line_items.insert(0, bad_item)
    res_bs = check_balance_sheet_balances(bad_spec_bs)
    _assert(not res_bs.passed, "check_balance_sheet_balances correctly fails on imbalanced BS")
    _assert("canonical.bs.total_assets" in res_bs.implicated_canonical_keys, "Implicated keys tracked for BS check")

    # 2b. Cash Flow Reconciliation Failure
    bad_spec_cf = spec.model_copy(deep=True)
    bad_item_cf = ForecastLineItem(
        canonical_key="canonical.bs.cash_and_bank",
        period_label="FY27",
        period_end_date="2027-03-31",  # type: ignore
        value=-500.0,  # Negative cash
        scenario="base",
    )
    bad_spec_cf.forecast.line_items.insert(0, bad_item_cf)
    res_cf = check_cash_flow_reconciles(bad_spec_cf)
    _assert(not res_cf.passed, "check_cash_flow_reconciles correctly fails on negative/invalid cash")

    # 2c. Debt Schedule Reconciliation Failure
    bad_spec_debt = spec.model_copy(deep=True)
    broken_period = DebtPeriod(
        period="FY27",
        opening_balance=1000.0,
        draws=500.0,
        scheduled_repayment=200.0,
        optional_repayment=0.0,
        closing_balance=999.0,  # Wrong closing
        interest_expense=0.0,
        interest_rate=0.0,
    )
    broken_ds = DebtSchedule(scenario="base", interest_rate=0.0, periods=[broken_period])
    bad_spec_debt.debt_schedule = [broken_ds]
    res_debt = check_debt_schedule_reconciles(bad_spec_debt)
    _assert(not res_debt.passed, "check_debt_schedule_reconciles correctly fails on unreconciled debt")

    # 2d. Share Count Consistency Failure
    bad_spec_shares = spec.model_copy(deep=True)
    bad_spec_shares.share_count = None
    res_shares = check_share_count_consistent(bad_spec_shares)
    _assert(not res_shares.passed, "check_share_count_consistent correctly fails when share count is missing")

    # 2e. DCF Bridge Reconciliation Failure
    bad_spec_dcf = spec.model_copy(deep=True)
    bad_spec_dcf.valuation[0].dcf_bridge.enterprise_value = 999999.0  # Broken EV bridge
    res_dcf = check_dcf_bridge_reconciles(bad_spec_dcf)
    _assert(not res_dcf.passed, "check_dcf_bridge_reconciles correctly fails on broken EV bridge")

    # 2f. WACC Validity Failure
    bad_spec_wacc = spec.model_copy(deep=True)
    bad_spec_wacc.valuation[0].wacc = WACCBreakdown(
        wacc=-5.0, cost_of_equity=-5.0, equity_weight=0.5, debt_weight=0.5
    )
    res_wacc = check_wacc_valid(bad_spec_wacc)
    _assert(not res_wacc.passed, "check_wacc_valid correctly fails on negative WACC")

    # 2g. Terminal Growth >= WACC Failure
    bad_spec_tg = spec.model_copy(deep=True)
    bad_spec_tg.valuation[0].terminal_value.terminal_growth_rate = 15.0  # Higher than WACC (12.95%)
    res_tg = check_terminal_growth_lt_wacc(bad_spec_tg)
    _assert(not res_tg.passed, "check_terminal_growth_lt_wacc correctly fails when g >= WACC")

    # 2h. Missing Critical Inputs Failure
    bad_spec_inputs = spec.model_copy(deep=True)
    bad_spec_inputs.assumptions = [a for a in bad_spec_inputs.assumptions if a.driver_key != "revenue_growth"]
    res_inputs = check_no_missing_critical_inputs(bad_spec_inputs)
    _assert(not res_inputs.passed, "check_no_missing_critical_inputs correctly fails when driver assumption is missing")

    # ------------------------------------------------------------------ #
    # 3. Status Rollup Label Verification
    # ------------------------------------------------------------------ #
    bad_run_spec = run_qa(bad_spec_tg)
    _assert(not bad_run_spec.qa.all_passed, "bad_run_spec all_passed is False")
    _assert(bad_run_spec.qa.failed_count == 1, f"bad_run_spec failed_count == 1 (got {bad_run_spec.qa.failed_count})")
    _assert(bad_run_spec.qa.summary_label == "1 CHECK FAILED", f"bad_run_spec summary_label == '1 CHECK FAILED' (got '{bad_run_spec.qa.summary_label}')")

    # ------------------------------------------------------------------ #
    # 4. ModelSpecification JSON Serialization Preservation
    # ------------------------------------------------------------------ #
    raw = spec.serialize()
    spec2 = ModelSpecification.deserialize(raw)
    _assert(spec2.qa is not None, "qa section preserved in deserialized spec")
    _assert(spec2.qa.all_passed, "qa.all_passed preserved after serialization")
    _assert(spec2.qa.summary_label == "MODEL VALID", "qa.summary_label preserved after serialization")

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    print(f"\n  Stage 8 QA Engine summary:")
    print(f"    Total checks run   : {len(spec.qa.checks)}")
    print(f"    Passed count      : {len(spec.qa.checks) - spec.qa.failed_count}")
    print(f"    Summary Status    : {spec.qa.summary_label}")
    print(f"    Synthetic Tests   : All 8 failure modes verified")

    print("\nALL STAGE 8 SELF-CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
