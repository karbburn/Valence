"""Borrowings from a market feed, with any bundled lease taken back out.

A market feed publishes borrowings in one of two shapes. Where a filer reports
debt and lease obligations on separate captions, the feed carries a pure row
("Long Term Debt", "Current Debt"). Where it reports one combined caption, the
feed carries a bundled row ("...AndCapitalLeaseObligation") and, alongside it, the
lease half on its own. So the lease is always separable, and the arithmetic belongs
in one place rather than in whichever ingestion path reads the frame next.

Reading the bundled row as borrowings wholesale put leases into the debt the
valuation deducts. Meta reported 2,213 of "Current Debt And Capital Lease
Obligation" that was the current portion of its lease liability, and Ambarella's
entire 2,027 current row was a lease. Both were charging for an obligation that is
already inside the EBIT the cash flows are built from.

Dropping the bundled row instead is the same error pointed the other way and worse:
it deletes a filer's whole current-debt line rather than the lease part of it, so
Ambarella's debt went to nothing and its implied price rose. Understating debt
flatters a valuation, which is the direction that makes a price look better than
the work supports.

So the lease is subtracted when the feed publishes it and the row is refused when
it does not. Nothing is taken whole from a combined caption, on either market.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

# (canonical label, pure feed rows in preference order, bundled row, lease row)
BORROWING_ROWS = (
    (
        "Borrowings",
        ("Long Term Debt",),
        "Long Term Debt And Capital Lease Obligation",
        "Long Term Capital Lease Obligation",
    ),
    (
        "Short term borrowings",
        ("Current Debt", "Other Current Borrowings"),
        "Current Debt And Capital Lease Obligation",
        "Current Capital Lease Obligation",
    ),
)


def index_rows(index) -> Dict[str, object]:
    """Feed row labels keyed by their lowercased, stripped form."""
    return {str(idx).strip().lower(): idx for idx in index}


def _number(value) -> Optional[float]:
    if value is None or (isinstance(value, float) and value != value):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def resolve_borrowings(
    rows: Dict[str, object],
    cell: Callable[[object], Optional[float]],
) -> List[Tuple[str, str, float]]:
    """Each established borrowing line as (canonical label, feed row, value).

    A combined caption with no lease half beside it is NOT returned. The lease it
    contains cannot be identified from the feed, so the figure cannot be shown to
    be borrowings, and the two ways of handling it are both wrong in opposite
    directions: taking it whole charges the valuation for a lease of unknown
    nature, and dropping it deletes a filer's whole debt line and raises the
    implied share price. Publishing nothing is the only option that states what is
    actually known.

    The cost is that a filer reporting a single combined caption gets no debt line
    from this feed. That is stated rather than hidden, and it is the safe direction
    for a line the valuation deducts: the filed statement is preferred everywhere
    in this engine and supplies the figure wherever it has one.
    """
    out: List[Tuple[str, str, float]] = []

    def read(label: str) -> Optional[float]:
        idx = rows.get(label.lower())
        if idx is None:
            return None
        return _number(cell(idx))

    for canonical, pure_rows, bundled, lease_row in BORROWING_ROWS:
        for candidate in pure_rows:
            if candidate.lower() in rows:
                value = read(candidate)
                if value is not None:
                    out.append((canonical, candidate, value))
                    break
        else:
            combined = read(bundled)
            lease = read(lease_row)
            if combined is None or lease is None:
                continue
            value = max(0.0, combined - lease)
            if value:
                out.append((canonical, bundled, value))
    return out
