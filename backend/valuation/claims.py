"""What ranks ahead of common equity, declared once.

Three places need this list and each had its own copy:

  - `valuation.dcf.compute_dcf_bridge` deducts these from enterprise value
  - `export.excel.render_val` shows them on the bridge row
  - `export.excel.self_check` re-derives net debt to verify the first

Mezzanine equity was missing from all three, and missing from the accounting check
too, so Uxin's equity value was overstated by its filed 48,056 while the balance
sheet carried the line correctly. That is the third time a claim class has been
added to the taxonomy and missed here -- minority interest, preferred stock,
mezzanine -- and the third time the cause was an enumeration nobody re-read.

The exporter and the self-check are the ones that matter most for this file. The
self-check exists to catch a bridge that does not reconcile, and it recomputes net
debt from the bridge's own fields. A copy of the claim list in that function is a
check that verifies the model against a list maintained separately from the model,
which is a check that agrees with a wrong answer -- and did, for every filer with
mezzanine, because the omission was in both places at once.

So the list lives here, the pipeline reads the canonical keys, and the two places
that must agree read the same declaration.
"""

from __future__ import annotations

from typing import NamedTuple


class ClaimAheadOfCommonEquity(NamedTuple):
    """One claim that enterprise value does not belong to common shareholders."""

    #: Canonical key on the historicals, which is what the ingestion populates.
    canonical_key: str
    #: Field on DCFBridge, which is what the bridge publishes and the exporter reads.
    bridge_field: str
    #: Label for the workbook. Kept here so a reader sees the same words the model
    #: means, rather than each surface inventing its own.
    label: str


#: Ordered. The order is the order they appear on the bridge, so the exporter can
#: walk this list and never needs its own ordering rule.
CLAIMS_AHEAD_OF_COMMON_EQUITY: tuple[ClaimAheadOfCommonEquity, ...] = (
    ClaimAheadOfCommonEquity(
        "canonical.bs.minority_interest",
        "minority_interest",
        "Minority Interest",
    ),
    ClaimAheadOfCommonEquity(
        "canonical.bs.preferred_stock",
        "preferred_stock",
        "Preferred Stock",
    ),
    ClaimAheadOfCommonEquity(
        "canonical.bs.mezzanine_equity",
        "mezzanine_equity",
        "Mezzanine Equity",
    ),
)


def resolve_claim(bridge, claim: "ClaimAheadOfCommonEquity") -> float:
    """The amount `bridge` carries for one declared claim, or 0.0.

    Two places exist for the amount. A claim with a named field on `DCFBridge` is
    read from it; a claim without one lives in `other_claims`, the open channel.

    Reading only the named field is what made a fourth claim class disappear after
    the bridge had already charged for it -- the arithmetic was right and the
    published figure was zero, so the workbook, the frontend and the export
    self-check would each have shown a reader that nothing stands ahead of them.
    The regression test caught that; this is the fix, shared rather than written
    twice.
    """
    named = getattr(bridge, claim.bridge_field, None)
    if named is not None:
        return float(named)
    return float((getattr(bridge, "other_claims", None) or {}).get(claim.bridge_field, 0.0))


def claims_total(bridge) -> float:
    """Everything that ranks ahead of common equity, on a published bridge."""
    return sum(resolve_claim(bridge, c) for c in CLAIMS_AHEAD_OF_COMMON_EQUITY)


def claims_label() -> str:
    """The workbook's caption for the combined row."""
    return "Less: " + ", ".join(c.label for c in CLAIMS_AHEAD_OF_COMMON_EQUITY)
