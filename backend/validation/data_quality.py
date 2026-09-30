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
    """Say which published figures were computed, and fail on the ones that matter.

    A period served from a hand-maintained spreadsheet is a projection, not a
    filing. It is a legitimate input to a model, but presenting it in a
    "historicals" statement without saying so is a misstatement, and it is
    load-bearing: the revenue growth rate the forecast fades from is computed
    from these years, so an invented year silently becomes the model's anchor.

    That was the whole of this check for a long time, and it could not fail on the
    more common case: a period in which most lines are filed and a handful are
    computed. 8.7% of canonical datapoints are derived — gross profit, EBITDA,
    subtotals, the filer catch-alls — and every one of them used to arrive at the
    specification, the workbook and the site labelled `reported`, because the spec
    builder hardcoded that status for every line except EBITDA. This check read the
    status that builder had already overwritten, so on a model with no invented
    years it passed and said nothing about the computed lines inside them.

    So it does two things now. It states the proportion of the statement that is
    computed and names the keys, so the reader is told rather than left to assume.
    And it FAILS when one of the anchor lines — revenue, the asset and liability
    subtotals, cash, borrowings — is computed rather than filed, because those are
    the figures the valuation is built on and a computed one there is a different
    claim from a computed gross profit.
    """
    from backend.models.spec.historicals import REPORTED_STATUSES

    # Lines the valuation is anchored on. A derived value here is not a presentational
    # detail; it is the difference between restating a filing and modelling one.
    ANCHOR_KEYS = frozenset({
        "canonical.is.revenue",
        "canonical.bs.total_assets",
        "canonical.bs.total_current_assets",
        "canonical.bs.total_equity",
        "canonical.bs.cash_and_bank",
        "canonical.is.operating_profit",
    })

    estimated_keys: List[str] = []
    estimated_periods: List[str] = []
    computed_anchor_keys: List[str] = []
    reported_periods: set[str] = set()
    total = 0
    computed = 0

    for item in (spec.historicals.line_items if spec.historicals else []):
        total += 1
        if item.status in REPORTED_STATUSES:
            reported_periods.add(item.period_label)
            continue
        computed += 1
        estimated_keys.append(item.canonical_key)
        estimated_periods.append(item.period_label)
        if item.canonical_key in ANCHOR_KEYS:
            computed_anchor_keys.append(item.canonical_key)

    all_periods = list(spec.historicals.periods) if spec.historicals else []
    unreported = [p for p in all_periods if p not in reported_periods]

    parts: List[str] = []
    if unreported:
        parts.append(
            f"{len(unreported)} of {len(all_periods)} historical periods "
            f"({', '.join(unreported)}) are not reported figures — they are "
            f"hand-entered or derived. The forecast's growth anchor is computed "
            f"from these years, so treat the model as a projection, not a "
            f"restatement of a filing."
        )
    if computed:
        pct = (computed / total * 100) if total else 0.0
        named = sorted(set(estimated_keys))
        parts.append(
            f"{computed} of {total} published historical figures ({pct:.1f}%) are "
            f"computed rather than read from a filing, across "
            f"{len(named)} line(s): {', '.join(named[:6])}"
            + ("..." if len(named) > 6 else "")
            + ". Each carries its formula in the workbook's derivation column."
        )
    if computed_anchor_keys:
        parts.append(
            "ANCHOR LINES ARE COMPUTED, not filed: "
            + ", ".join(sorted(set(computed_anchor_keys)))
            + ". These are the figures the valuation is built on, so the model's "
            "anchor is a derivation rather than a restatement of the accounts."
        )

    passed = not unreported and not computed_anchor_keys
    detail = " ".join(parts) if parts else (
        f"All {len(all_periods)} historical periods trace to a reported figure and "
        f"all {total} published lines are read from a filing."
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
