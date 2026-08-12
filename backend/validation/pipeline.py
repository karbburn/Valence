from __future__ import annotations

"""
QA Engine Top-Level Pipeline.

Runs accounting checks, model checks, and data quality checks against a ModelSpecification,
populating spec.qa with structured QAResults and logging summary status.
"""

from typing import List

from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import ModelCheckResult, QAResults
from backend.validation.accounting_checks import run_accounting_checks
from backend.validation.data_quality import run_data_quality_checks
from backend.validation.model_checks import run_model_checks


def run_qa(spec: ModelSpecification) -> ModelSpecification:
    """Run all QA checks against specification and populate spec.qa."""
    checks: List[ModelCheckResult] = []

    # 1. Accounting Integrity Checks
    checks.extend(run_accounting_checks(spec))

    # 2. Model & Valuation Integrity Checks
    checks.extend(run_model_checks(spec))

    # 3. Data Quality Checks
    checks.extend(run_data_quality_checks(spec))

    # Populate QAResults on ModelSpecification
    spec.qa = QAResults(checks=checks)

    print(
        f"QA Engine Pipeline Complete:\n"
        f"  - Total checks run  : {len(checks)}\n"
        f"  - Passed count     : {len(checks) - spec.qa.failed_count}\n"
        f"  - Failed count     : {spec.qa.failed_count}\n"
        f"  - Status Rollup    : {spec.qa.summary_label}"
    )

    return spec
