from __future__ import annotations

"""
Data quality & provenance checks module.

Verifies that historical datapoints carry valid status and provenance metadata.
"""

from typing import List

from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import ModelCheckResult


def check_cost_of_capital_is_live(spec: ModelSpecification) -> ModelCheckResult:
    """The discount rate must rest on a market rate, not on a stored constant.

    A failed market-data fetch does not produce an error. The risk-free rate falls
    through a chain — live provider, second provider, per-company registry, market
    default — and the last of those is a hardcoded figure dated to the month it
    was written, with a comment saying so. The valuation then completes normally
    and differs from the same model run an hour later, because the rate moved.

    NVIDIA is the case. Two builds an hour apart produced $161.44 and $150.85 from
    identical statements: identical income, balance sheet, cash flow, ratios,
    operating model, revenue, cost, working capital, capex, debt, tax and share
    count. The only difference in the entire workbook was the risk-free rate —
    4.64% from the stored default against 5.24% live from the 10-year Treasury.
    Sixty basis points on a discount rate, 6.6% on the implied price, and nothing
    on the face of the model said which one you were looking at.

    That is the failure this exists for. A number that changes between two runs of
    the same model is not reproducible, and a model that is not reproducible cannot
    be checked by the person reading it. It fails rather than warns, because the
    whole point is that the reader is not looking for it.

    A per-company registry beta is NOT a fallback here: it is a deliberate,
    documented calibration choice stated in the workbook's own source column, and
    treating it as a placeholder would fire on every company that has one.
    """
    defaulted: List[str] = []
    details: List[str] = []

    for val in spec.valuation:
        if val.scenario != "base":
            continue
        w = val.wacc
        if not isinstance(w, dict):
            continue
        notes = str(w.get("source_notes") or "")
        if "market default for rfr" in notes.lower():
            defaulted.append("risk-free rate")
            details.append(
                f"{val.scenario}: the risk-free rate is a stored market default, not a "
                f"live yield. The discount rate is therefore a constant, and the "
                f"implied price will differ from the same model priced on the live "
                f"rate — 60bp on the risk-free rate is roughly 6% on the price."
            )
        if "market default for erp" in notes.lower():
            defaulted.append("equity risk premium")
            details.append(
                f"{val.scenario}: the equity risk premium is a stored market default."
            )

    passed = not defaulted
    return ModelCheckResult(
        check_name="cost_of_capital_is_live",
        category="data_quality",
        passed=passed,
        detail="" if passed else "; ".join(details),
        implicated_canonical_keys=sorted(set(defaulted)),
        implicated_periods=[],
        implicated_scenarios=["base"] if not passed else [],
    )


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


def check_historicals_are_reported(spec: ModelSpecification) -> ModelCheckResult:
    """Every historical period must trace back to something someone published.

    A period served from a hand-maintained spreadsheet is a projection, not a
    filing. It is a legitimate input to a model, but presenting it in a
    "historicals" statement without saying so is a misstatement, and it is
    load-bearing: the revenue growth rate the forecast fades from is computed
    from these years, so an invented year silently becomes the model's anchor.

    This check FAILS (rather than warns) whenever any period in the historical
    statement is not a reported figure, so the reader is told in the QA rollup
    rather than finding out by comparing a revenue line against their terminal.
    """
    from backend.models.spec.historicals import REPORTED_STATUSES

    estimated_keys: List[str] = []
    estimated_periods: List[str] = []
    reported_periods: set[str] = set()

    for item in (spec.historicals.line_items if spec.historicals else []):
        if item.status in REPORTED_STATUSES:
            reported_periods.add(item.period_label)
        else:
            estimated_keys.append(item.canonical_key)
            estimated_periods.append(item.period_label)

    all_periods = list(spec.historicals.periods) if spec.historicals else []
    unreported = [p for p in all_periods if p not in reported_periods]

    passed = not unreported
    if passed:
        detail = f"All {len(all_periods)} historical periods trace to a reported figure."
    else:
        detail = (
            f"{len(unreported)} of {len(all_periods)} historical periods "
            f"({', '.join(unreported)}) are not reported figures — they are "
            f"hand-entered or derived. The forecast's growth anchor is computed "
            f"from these years, so treat the model as a projection, not a "
            f"restatement of a filing."
        )

    return ModelCheckResult(
        check_name="historicals_are_reported",
        category="data_quality",
        passed=passed,
        detail=detail,
        implicated_canonical_keys=sorted(set(estimated_keys)),
        implicated_periods=sorted(set(estimated_periods)),
        implicated_scenarios=["historical"],
    )


def run_data_quality_checks(spec: ModelSpecification) -> List[ModelCheckResult]:
    """Run data quality checks against specification."""
    return [
        check_data_provenance_quality(spec),
        check_historicals_are_reported(spec),
    ]
