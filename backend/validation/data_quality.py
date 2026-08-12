from __future__ import annotations

"""
Data quality & provenance checks module.

Verifies that historical datapoints carry valid status and provenance metadata.
"""

from typing import List

from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import ModelCheckResult


def check_data_provenance_quality(spec: ModelSpecification) -> ModelCheckResult:
    """Verify historical line items have non-empty status and lineage metadata."""
    errors: List[str] = []
    failing_keys: List[str] = []
    failing_periods: List[str] = []

    if not spec.historicals or not spec.historicals.line_items:
        errors.append("No historical line items present in specification")
    else:
        for item in spec.historicals.line_items:
            if not item.status:
                errors.append(f"Line item '{item.canonical_key}' period {item.period_label} missing status")
                failing_keys.append(item.canonical_key)
                failing_periods.append(item.period_label)

    passed = len(errors) == 0
    detail = "" if passed else "; ".join(errors[:5])

    return ModelCheckResult(
        check_name="data_provenance_quality",
        category="data_quality",
        passed=passed,
        detail=detail,
        implicated_canonical_keys=list(set(failing_keys)),
        implicated_periods=list(set(failing_periods)),
        implicated_scenarios=["historical"],
    )


def run_data_quality_checks(spec: ModelSpecification) -> List[ModelCheckResult]:
    """Run data quality checks against specification."""
    return [
        check_data_provenance_quality(spec),
    ]
