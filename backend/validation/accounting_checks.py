from __future__ import annotations

"""
Accounting integrity checks module.

Checks:
1. balance_sheet_balances: Assets = Liabilities + Equity for all historical/forecast periods and scenarios.
2. cash_flow_reconciles: Cash flow ending balance ties to balance sheet cash line.
3. debt_schedule_reconciles: Opening + draws - repayments = closing debt (wires debt module reconcile()).
4. share_count_consistent: Share count used consistently across EPS and valuation.
5. current_assets_reconcile: the itemised current-asset lines sum to the filer's
   own current-asset subtotal.
"""

from collections import Counter
from collections import OrderedDict
from typing import Any, Callable, List

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

# The current-asset lines the workbook prints above the subtotal, in the order it
# prints them. A line added to the renderer belongs here, or this check stops
# describing the statement a reader actually sees.
CURRENT_ASSET_LINES: List[str] = [
    "canonical.bs.cash_and_bank",
    "canonical.bs.current_investments",
    "canonical.bs.trade_receivables",
    "canonical.bs.vendor_non_trade_receivables",
    "canonical.bs.unbilled_revenue",
    "canonical.bs.inventory",
    "canonical.bs.prepayments_other_current_assets",
    "canonical.bs.current_income_tax_assets",
    "canonical.bs.derivative_financial_assets_current",
]


# Lines whose figures are not money in the reporting currency, so a `units` of
# "millions" is not a claim that can be true or false. EPS of 2.31 in USD millions
# would be a different sort of wrong from a mislabelled revenue line, and forcing one
# onto it would make the check noisy on exactly the models with the most periods.
UNITLESS_LINES: set = {
    "canonical.is.eps_basic",
    "canonical.is.eps_diluted",
    "canonical.is.dividend_per_share",
}


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

        # The components, not just the two subtotals the filer prints.
        #
        # Comparing total assets to the filer's REPORTED total-liabilities-and-equity
        # is necessary and nowhere near sufficient. A filer can print both of those
        # and still have an engine that assembles the right-hand side out of
        # components that do not add to them: Tata Consultancy reported assets of
        # 174,162 and a total-liabilities-and-equity of 174,162, which ties, while
        # the engine's derived liabilities of 73,298 and derived equity of 108,562
        # came to 181,860 — a 7,698 hole that this comparison could not see, because
        # the two figures it looks at are both the filer's own and both correct.
        # Nothing else compared the parts, so the parts were free to be wrong.
        liabilities = spec.historicals.get_value("canonical.bs.total_liabilities", p)
        equity = spec.historicals.get_value("canonical.bs.total_equity", p)
        # Mezzanine equity sits BETWEEN liabilities and equity in a filer's own
        # presentation: redeemable preferred, redeemable noncontrolling interest. It
        # is neither, and it is a real claim on the enterprise, so it belongs on the
        # right-hand side of the identity.
        #
        # Omitting it made every genuine mezzanine filer fail this check by exactly
        # the mezzanine amount, on a balance sheet that is correct. Uxin is 48,056.
        mezzanine = spec.historicals.get_value("canonical.bs.mezzanine_equity", p) or 0.0
        if assets is not None and liabilities is not None and equity is not None:
            built = float(liabilities) + float(mezzanine) + float(equity)
            gap = built - float(assets)
            if abs(gap) > max(abs(float(assets)) * 0.001, BS_TOLERANCE_CR):
                failing_periods.append(p)
                failing_scenarios.append("historical")
                mezz_txt = (
                    f" + mezzanine {mezzanine:,.0f}" if mezzanine else ""
                )
                errors.append(
                    f"Historical {p}: liabilities {liabilities:,.0f}{mezz_txt} + equity "
                    f"{equity:,.0f} = {built:,.0f}, against total assets "
                    f"{assets:,.0f}, a gap of {gap:+,.0f}"
                )

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


def _absent_lines_note(
    absent: "OrderedDict[str, Any]",
    failing_periods: List[str],
    missing_in: "Callable[[str, str], bool]",
) -> str:
    """Name the current-asset lines that carry no value, so the gap decomposes.

    Split by direction, because the two need opposite investigations and lumping them
    together hides that:

      * UNDER-count -- a line is absent. Either the filer does not print it, or the
        reader dropped it. Those are very different, and the first is not a defect.
      * OVER-count -- no line is absent, so the itemised block exceeds the filer's own
        subtotal, which means something is counted twice.

    Only lines absent in EVERY failing period are named. A line present in one period
    and missing in another is a period-specific ingestion problem, and listing it
    alongside lines missing everywhere would misdescribe it.
    """
    if not absent:
        return (
            " No current-asset line is absent, so the itemised block EXCEEDS the "
            "filer's own subtotal: something is counted twice."
        )
    everywhere = [
        k for k in absent
        if all(missing_in(k, p) for p in failing_periods)
    ]
    if not everywhere:
        return (
            " No current-asset line is absent in every failing period, so this is a "
            "period-specific ingestion gap rather than a line the filer never prints."
        )
    named = ", ".join(k.replace("canonical.bs.", "") for k in everywhere)
    return (
        f" Absent in every failing period: {named}. A line the filer does not print is "
        f"correctly absent; a line it does print is a reader that dropped it."
    )


def check_current_assets_reconcile(spec: ModelSpecification) -> ModelCheckResult:
    """The itemised current-asset lines must sum to the filer's own subtotal.

    The balance sheet balances in total, which says nothing about whether the lines
    printed above the current-asset subtotal add up to that subtotal. Two failures
    hide there, and both are invisible to every other check in this codebase because
    both are internally consistent:

    An OVER-count, when two of the lines are the same money at two levels of the
    taxonomy. Armstrong World Industries prints one line, "Other current assets
    23.9", of which prepaid expenses are 22.5. Held as two separate figures, the
    itemised block summed to 414.0 against a filed 391.5, and because the
    investment residual was clamped at zero, the 22.5 of overlap was reported by
    nothing at all.

    An UNDER-count, when the filer holds a current asset the engine never ingested.
    Apple's vendor non-trade receivables are the large example: nothing above the
    subtotal accounts for them, so the column falls short by tens of billions and
    the statement still balances.

    Reported as a signed gap per period rather than a verdict, because a gap of
    minus three is a missing line and a gap of plus three is a double count, and
    those need opposite fixes.

    And it NAMES the lines that are absent, because a gap a reader cannot decompose is
    a gap they cannot act on -- and from the outside it is indistinguishable from a
    figure that is simply wrong. Infosys' FY26 gap is 17,621, which is exactly:

        prepayments_other_current_assets            15,703
        current_income_tax_assets                    1,835
        derivative_financial_assets_current             83

    Three captions the filer prints on p.100, all dropped by the row-grouping defect in
    the PDF reader (assets/gsd/OPEN_DEFECTS.md section 6). Naming them is the difference
    between "this company is short 17,621" and "these three lines are missing and here is
    what each is worth" -- and the second one is a fix with an owner.
    """
    failing_keys: List[str] = []
    failing_periods: List[str] = []
    errors: List[str] = []
    # Which lines were missing in the periods that failed, and the first period seen,
    # so the message can list them once rather than per period.
    absent: "OrderedDict[str, None]" = OrderedDict()

    for p in spec.historicals.periods:
        subtotal = spec.historicals.get_value("canonical.bs.total_current_assets", p)
        if subtotal is None:
            continue
        itemised = 0.0
        seen_any = False
        for key in CURRENT_ASSET_LINES:
            v = spec.historicals.get_value(key, p)
            if v is not None:
                itemised += float(v)
                seen_any = True
        if not seen_any:
            continue
        gap = itemised - float(subtotal)
        # Relative to the subtotal, because a rupee of gap on a company reporting in
        # crores is nothing and a rupee on a company reporting in units is not.
        if abs(gap) > max(float(subtotal) * 0.005, 1.0):
            failing_periods.append(p)
            missing_here = [k for k in CURRENT_ASSET_LINES
                            if spec.historicals.get_value(k, p) is None]
            errors.append(
                f"{p}: itemised current assets {itemised:,.0f} against a filed "
                f"subtotal of {subtotal:,.0f}, gap {gap:+,.0f}"
            )
            for k in missing_here:
                absent.setdefault(k, p)
            failing_keys = list(CURRENT_ASSET_LINES)

    passed = not errors
    return ModelCheckResult(
        check_name="current_assets_reconcile",
        category="accounting",
        passed=passed,
        detail=(
            ""
            if passed
            else (
                f"Itemised current assets do not reach the filer's subtotal in "
                f"{len(errors)} period(s): " + "; ".join(errors[:3])
                + _absent_lines_note(
                    absent,
                    failing_periods,
                    lambda k, p: spec.historicals.get_value(k, p) is None,
                )
            )
        ),
        implicated_canonical_keys=failing_keys,
        implicated_periods=failing_periods,
    )


def check_units_agree_within_a_model(spec: ModelSpecification) -> ModelCheckResult:
    """Every published line carries the unit the model itself declares.

    A figure and its unit travel together through the engine, and every other check in
    this suite reads the figure alone. That is how 616 line items across 11 shipped
    models came to be labelled INR in crores while holding USD millions, with the
    model metadata on the same object saying USD/millions: nothing compared the two.

    Per-share figures and ratios are exempt. "millions" is not the unit of an EPS, so
    requiring one would be the same defect wearing a check's clothes -- and the first
    filers to hit it would be the ones with the most periods.
    """
    declared = (getattr(spec.metadata, "currency", None), getattr(spec.metadata, "units", None))
    if not declared[0] or not declared[1]:
        # Nothing to compare against. Say so rather than passing silently: a model that
        # declares no unit and one that was never asked are different states.
        return ModelCheckResult(
            check_name="units_agree_within_a_model",
            category="accounting",
            passed=True,
            detail=(
                "model declares no currency/units, so line units cannot be compared; "
                "no line disagrees with a declaration that does not exist"
            ),
        )

    disagree: List[str] = []
    seen = Counter()
    failing_keys: List[str] = []
    failing_periods: List[str] = []

    for it in spec.historicals.line_items:
        if it.value is None:
            continue
        if it.canonical_key in UNITLESS_LINES or it.canonical_key.startswith("canonical.ratio."):
            continue
        if not it.currency and not it.units:
            continue
        seen[(it.currency, it.units)] += 1
        if (it.currency, it.units) != declared:
            if len(disagree) < 8:
                disagree.append(
                    f"{it.canonical_key} {it.period_label}: labelled "
                    f"{it.currency or '?'}/{it.units or '?'} against a declared "
                    f"{declared[0]}/{declared[1]}"
                )
            if it.canonical_key not in failing_keys:
                failing_keys.append(it.canonical_key)
            if it.period_label not in failing_periods:
                failing_periods.append(it.period_label)

    passed = not disagree and not (seen - Counter({declared: sum(seen.values())}))
    if not seen:
        return ModelCheckResult(
            check_name="units_agree_within_a_model",
            category="accounting",
            passed=True,
            detail="no unit-bearing line items to compare",
        )

    mixed = {c: n for c, n in seen.items() if c != declared}
    return ModelCheckResult(
        check_name="units_agree_within_a_model",
        category="accounting",
        passed=passed,
        detail=(
            ""
            if passed
            else f"{sum(mixed.values())} of {sum(seen.values())} line items carry a "
            f"unit other than the declared {declared[0]}/{declared[1]} "
            f"({', '.join(f'{c[0] or chr(63)}/{c[1] or chr(63)}={n}' for c, n in sorted(mixed.items()))}): "
            + "; ".join(disagree[:3])
        ),
        implicated_canonical_keys=failing_keys,
        implicated_periods=failing_periods,
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
    """Run all accounting checks against specification."""
    return [
        check_balance_sheet_balances(spec),
        check_current_assets_reconcile(spec),
        check_cash_flow_reconciles(spec),
        check_debt_schedule_reconciles(spec),
        check_share_count_consistent(spec),
    ]
