"""A valuation must not be published on a balance sheet that carries no debt.

Zero is the most dangerous number in the equity bridge. It is not a neutral
placeholder: it means the enterprise value equals the equity value, so every
dollar of the company's obligations is silently worth nothing, and the implied
share price reads high by exactly the debt.

Infosys' ADR is the live case. Its only input is a market feed that carries no
debt rows at all, so the bridge published `total_debt = 0` against roughly $962m
of filed lease obligations, and -- until this was caught -- labelled the balance
sheet `filed_annual_balance_sheet` while reading no filing whatsoever. The model
was internally consistent: `debt_schedule_reconciles` passed, because a schedule
of zero balances reconciles perfectly, and `bridge_inputs_plausible` passed,
because zero is a plausible number. Nothing anywhere objected.

This check refuses to let that combination be published. It does not decide what
Infosys' debt is -- that needs the 20-F, which is a separate piece of work -- it
refuses to publish a bridge built on the absence of the input.

Three conditions must hold together before a zero-debt bridge is believable:
there is at least one debt line, the bridge is reading a filed balance sheet, and
the debt figure was itself computed rather than defaulted. A company with
genuinely no borrowings passes the first and third.
"""

from __future__ import annotations

from backend.models.spec.metadata import FILING_SOURCES
from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import ModelCheckResult

DEBT_KEYS = (
    "canonical.bs.borrowings",
    "canonical.bs.short_term_borrowings",
    "canonical.bs.long_term_debt",
    "canonical.bs.finance_lease_liabilities",
)


def check_debt_is_actually_sourced(spec: ModelSpecification) -> ModelCheckResult:
    """Refuse a zero-debt bridge that has no debt input behind it."""
    scen = (spec.valuation or [])
    bridge = None
    for s in scen:
        candidate = getattr(s, "dcf_bridge", None)
        if candidate is not None:
            bridge = candidate
            break
    if bridge is None:
        # Returned as PASSING, which is how this check shipped its first version:
        # it looked for `spec.scenarios`, which holds the forecast definitions and
        # carries no bridge, so it found nothing, took the early return, and
        # reported the very defect it was written to catch as clean.
        #
        # A check that cannot find its subject has not verified the subject. This
        # fails instead, so a rename on the model breaks the build rather than
        # quietly disarming the check.
        return ModelCheckResult(
            check_name="debt_is_actually_sourced",
            category="data_quality",
            passed=False,
            detail=(
                "No valuation bridge was found on the model, so debt sourcing could "
                "not be checked. This check is failing rather than passing because it "
                "verified nothing: an unverified check that reports success is worse "
                "than no check, because it is believed."
            ),
            implicated_scenarios=["base", "bull", "bear"],
        )

    total_debt = getattr(bridge, "total_debt", None)
    if total_debt:
        return ModelCheckResult(
            check_name="debt_is_actually_sourced",
            category="data_quality",
            passed=True,
            detail=f"Debt is {total_debt:,.0f} and is carried in the bridge.",
        )

    # Zero debt. Is that because the company has none, or because nothing supplied
    # it? Only the second is publishable-breaking, and the difference is whether any
    # debt line exists at all.
    lines = spec.historicals.line_items if spec.historicals else []
    latest = spec.historicals.periods[-1] if (spec.historicals and spec.historicals.periods) else None
    debt_lines = [
        li for li in lines
        if li.canonical_key in DEBT_KEYS and li.period_label == latest
    ]
    sources = set((spec.metadata.data_sources or {}).keys())

    if debt_lines:
        # The company filed borrowings and they came to zero. Believable.
        return ModelCheckResult(
            check_name="debt_is_actually_sourced",
            category="data_quality",
            passed=True,
            detail=(
                f"Debt is zero but {len(debt_lines)} debt/lease line(s) were supplied "
                f"in {latest}, so the figure is reported rather than defaulted."
            ),
            implicated_canonical_keys=sorted({li.canonical_key for li in debt_lines}),
            implicated_periods=[latest] if latest else [],
        )

    if sources & FILING_SOURCES:
        # No debt lines, but a filing supplied the balance sheet. A filer that
        # prints no borrowings has told us it has none, and the absence of the line
        # IS the disclosure. Ambarella is this case, and failing it would mean the
        # check objects to genuinely debt-free companies -- which would be a check
        # crying wolf, and would train everyone to ignore it.
        return ModelCheckResult(
            check_name="debt_is_actually_sourced",
            category="data_quality",
            passed=True,
            detail=(
                f"Debt is zero and no debt line was supplied for {latest}, but a filing "
                f"({', '.join(sorted(sources & FILING_SOURCES))}) sourced this balance "
                f"sheet. A filer that publishes no borrowings has disclosed that it has "
                f"none, so the zero is a filed position rather than a missing input."
            ),
            implicated_periods=[latest] if latest else [],
        )

    return ModelCheckResult(
        check_name="debt_is_actually_sourced",
        category="data_quality",
        passed=False,
        detail=(
            f"The bridge reports total debt of 0, and NO debt line was supplied for "
            f"{latest}: not one borrowing, short-term borrowing, long-term debt or "
            f"finance lease figure exists in this model. The zero is therefore the "
            f"absence of an input rather than a filed position, and it makes "
            f"enterprise value equal equity value -- every obligation the company has "
            f"is worth nothing to the valuation. The sources are "
            f"{sorted(sources) or ['none']}, none of which is a filing, so nothing "
            f"here tells us whether the company is debt-free or merely unsourced. "
            f"Two existing checks pass this model -- the debt schedule reconciles "
            f"because a schedule of zero balances reconciles, and the bridge inputs are "
            f"plausible because zero is a plausible number -- so nothing else objects. "
            f"Either source the debt from the issuer's accounts, or stop publishing a "
            f"valuation. Do not publish this bridge as it stands."
        ),
        implicated_canonical_keys=list(DEBT_KEYS),
        implicated_periods=[latest] if latest else [],
        implicated_scenarios=["base", "bull", "bear"],
    )
