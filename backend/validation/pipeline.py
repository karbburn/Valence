from __future__ import annotations

"""
QA Engine Top-Level Pipeline.

Runs accounting checks, model checks, and data quality checks against a ModelSpecification,
populating spec.qa with structured QAResults and logging summary status.
"""

import logging
from typing import Callable, List, Tuple

from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import ModelCheckResult, QAResults
from backend.validation.accounting_checks import (
    check_balance_sheet_balances,
    check_cash_flow_reconciles,
    check_debt_schedule_reconciles,
    check_share_count_consistent,
)
from backend.validation.data_quality import check_data_provenance_quality
from backend.validation.model_checks import (
    check_dcf_bridge_reconciles,
    check_no_missing_critical_inputs,
    check_terminal_growth_lt_wacc,
    check_wacc_valid,
)

logger = logging.getLogger("valence.validation")

# All checks run by the QA pipeline as (category, callable) pairs. Checks are
# executed one at a time so a single broken check cannot crash the whole run —
# unexpected exceptions are converted into a failed check result.
CHECK_SUITE: List[Tuple[str, Callable[[ModelSpecification], ModelCheckResult]]] = [
    ("accounting", check_balance_sheet_balances),
    ("accounting", check_cash_flow_reconciles),
    ("accounting", check_debt_schedule_reconciles),
    ("accounting", check_share_count_consistent),
    ("valuation", check_dcf_bridge_reconciles),
    ("valuation", check_wacc_valid),
    ("valuation", check_terminal_growth_lt_wacc),
    ("data_quality", check_no_missing_critical_inputs),
    ("data_quality", check_data_provenance_quality),
]


def run_qa(spec: ModelSpecification) -> ModelSpecification:
    """Run all QA checks against specification and populate spec.qa."""
    checks: List[ModelCheckResult] = []

    for category, check_fn in CHECK_SUITE:
        try:
            checks.append(check_fn(spec))
        except Exception as exc:  # noqa: BLE001 — one broken check must not crash the pipeline
            logger.error(
                "QA check '%s' raised an unexpected exception: %s",
                check_fn.__name__,
                exc,
                exc_info=True,
            )
            checks.append(
                ModelCheckResult(
                    check_name=check_fn.__name__,
                    category=category,
                    passed=False,
                    detail=f"Check raised unexpected exception: {exc}",
                )
            )

    # Populate QAResults on ModelSpecification
    spec.qa = QAResults(checks=checks)

    logger.info(
        "QA Engine Pipeline Complete:\n"
        "  - Total checks run  : %d\n"
        "  - Passed count     : %d\n"
        "  - Failed count     : %d\n"
        "  - Status Rollup    : %s",
        len(checks),
        len(checks) - spec.qa.failed_count,
        spec.qa.failed_count,
        spec.qa.summary_label,
    )

    return spec
