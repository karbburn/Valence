"""A published capital-structure figure must be one that can be believed.

Two ways the platform was telling a reader something untrue about a company's
debt, both on the enterprise value bridge — the one page whose whole job is to
show how enterprise value becomes a share price.

The stated basis described a convention the engine did not apply. It said debt
was borrowings plus finance and operating lease liabilities. The engine uses the
issuer's own reported total debt. So the note described a calculation the
platform was not performing, and a reader reconciling against it would be
reconciling against a fiction.

The lease figure was published as a component of debt when it was not one. For
one large Indian listing the feed's lease row equalled the entire debt balance
to the rupee, which is a restatement of the total rather than a subset of it.
Published as "lease liabilities" it told a reader that all of that company's
debt was leases.
"""

from __future__ import annotations

import pytest

from backend.data.bridge_inputs import _build, _drop_claims_at_or_above_total
from backend.valuation.pipeline import DEBT_BASIS_NOTE


class _Col:
    def __init__(self, value):
        self._value = value

    def strftime(self, fmt):
        return self._value

    def to_pydatetime(self):
        import datetime

        return datetime.datetime(2026, 6, 30)


class _Loc:
    """Subscriptable stand-in for a frame's ``.loc``.

    Readers subscript it — ``frame.loc[label, column]`` — so it must be
    indexable. A plain method raises a TypeError that the row reader catches and
    skips, so every lookup would come back empty and the snapshot would look
    like the balance sheet reported nothing.
    """

    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        label, _column = key
        return self._data[label]


class _Frame:
    """A balance sheet carrying one value per row, as a feed publishes it."""

    def __init__(self, data: dict[str, float]):
        self.index = list(data)
        self.columns = [_Col("2026-06-30")]
        self.loc = _Loc(data)


def _snapshot(data: dict[str, float]):
    return _build(_Frame(data), _Col("2026-06-30"), "reported_quarter")


# --------------------------------------------------------------------------- #
# A component cannot be as large as the whole
# --------------------------------------------------------------------------- #

def test_a_lease_row_equal_to_total_debt_is_not_published_as_a_component():
    """One listing's lease row WAS its total debt.

    Published as a lease component it stated that the company's entire debt was
    lease obligations, which is not a capital structure any company has.
    """
    snapshot = _snapshot({
        "Long Term Debt": 112_830_000_000.0,
        "Cash Cash Equivalents And Short Term Investments": 413_730_000_000.0,
        "Capital Lease Obligation": 112_830_000_000.0,
    })

    assert "lease_liabilities" not in snapshot.terms, (
        "a lease balance equal to the whole debt total restates the aggregate "
        "and must not be published as a component of it"
    )
    assert snapshot.total_debt == pytest.approx(112_830_000_000.0)


def test_a_genuine_lease_component_is_still_reported():
    """Dropping the unreliable case must not drop the reliable one."""
    snapshot = _snapshot({
        "Long Term Debt": 40_294_000_000.0,
        "Cash Cash Equivalents And Short Term Investments": 76_651_000_000.0,
        "Operating Lease Liability": 16_532_000_000.0,
    })

    assert snapshot.terms["lease_liabilities"] == pytest.approx(16_532_000_000.0)


def test_a_zero_current_leg_beside_an_unread_combined_total_is_not_no_debt():
    """The case that produced a company published with no debt at all.

    The feed reports `Current Debt` at exactly 0.0 while the filer's non-current
    borrowings sit unread in the combined caption this module does not use. Testing
    for the presence of the key passes it, so the company is published with 28,654
    of borrowings discarded and a net cash position invented, and an enterprise
    value and an EV/EBITDA are computed from that. A feed reporting zero on a row
    it also reports a combined total for has not established that the filer owes
    nothing; it has established that it does not separate the two.
    """
    assert _snapshot({
        "Current Debt": 0.0,
        "Long Term Debt And Capital Lease Obligation": 28_654_000_000.0,
        "Cash Cash Equivalents And Short Term Investments": 76_651_000_000.0,
    }) is None


def test_both_legs_at_zero_is_a_real_answer():
    """A filer stating it owes nothing on either side has said so."""
    snapshot = _snapshot({
        "Long Term Debt": 0.0,
        "Current Debt": 0.0,
        "Cash Cash Equivalents And Short Term Investments": 500.0,
    })

    assert snapshot is not None
    assert snapshot.total_debt == pytest.approx(0.0)


def test_a_nonzero_leg_beside_an_absent_one_is_established():
    """One leg reported and not the other is a figure, not a gap."""
    snapshot = _snapshot({
        "Long Term Debt": 40_294_000_000.0,
        "Cash Cash Equivalents And Short Term Investments": 76_651_000_000.0,
    })

    assert snapshot is not None
    assert snapshot.total_debt == pytest.approx(40_294_000_000.0)


def test_a_component_larger_than_the_total_is_also_dropped():
    """Larger than the total is at least as impossible as equal to it."""
    values = {"lease_liabilities": 200.0}
    _drop_claims_at_or_above_total(values, total_debt=100.0)
    assert "lease_liabilities" not in values


def test_minority_interest_at_or_above_total_debt_is_dropped():
    """Same reasoning: a claim on the company cannot exceed the company's debt."""
    snapshot = _snapshot({
        "Long Term Debt": 1_000.0,
        "Cash Cash Equivalents And Short Term Investments": 500.0,
        "Minority Interest": 1_000.0,
    })

    assert "minority_interest" not in snapshot.terms


def test_a_filer_publishing_only_the_combined_debt_caption_is_dropped():
    """No debt row means no debt figure, which is not the same as no debt.

    The combined caption carries a lease the feed cannot identify, so it cannot be
    used. Publishing a balance of zero instead would state that the company carries
    no debt, and that figure flows into an enterprise value, an EV/EBITDA and a
    benchmark median, flattering every one of them.
    """
    assert _snapshot({
        "Total Debt": 56_826_000_000.0,
        "Long Term Debt And Capital Lease Obligation": 56_826_000_000.0,
        "Cash Cash Equivalents And Short Term Investments": 76_651_000_000.0,
    }) is None


def test_the_combined_debt_caption_is_never_read_as_borrowings():
    """The sum it publishes is borrowings plus a lease of unidentifiable nature."""
    snapshot = _snapshot({
        "Long Term Debt And Capital Lease Obligation": 40_294_000_000.0,
        "Long Term Capital Lease Obligation": 16_532_000_000.0,
        "Cash Cash Equivalents And Short Term Investments": 76_651_000_000.0,
    })

    assert snapshot is None, (
        "a combined caption with no pure row beside it must not become a debt "
        "figure, because the lease inside it cannot be removed"
    )


def test_a_small_minority_interest_is_kept():
    """Ordinary claims are untouched."""
    snapshot = _snapshot({
        "Long Term Debt": 1_000.0,
        "Cash Cash Equivalents And Short Term Investments": 500.0,
        "Minority Interest": 120.0,
    })

    assert snapshot.terms["minority_interest"] == pytest.approx(120.0)


def test_nothing_is_dropped_when_debt_is_unknown():
    """With no debt total there is nothing to compare a component against, so a
    component must not be discarded on a comparison that cannot be made."""
    values = {"lease_liabilities": 500.0}
    _drop_claims_at_or_above_total(values, total_debt=0.0)
    assert values["lease_liabilities"] == pytest.approx(500.0)


# --------------------------------------------------------------------------- #
# The stated basis must match what is done
# --------------------------------------------------------------------------- #

def test_the_basis_note_does_not_claim_leases_are_added_to_debt():
    """The note described a convention the engine does not apply.

    The basis used to be a market feed's debt total, which capitalises every
    lease it can find while the note claimed leases were not added on top. It now
    says what is actually deducted: the filed borrowings, with finance and capital
    leases in because they are interest-bearing, and operating leases out because
    rent is already inside the EBIT these cash flows are built from.
    """
    lowered = DEBT_BASIS_NOTE.lower()

    assert "operating lease liabilities are excluded" in lowered, (
        f"the note must say operating leases are excluded from debt: {DEBT_BASIS_NOTE!r}"
    )
    assert "finance and capital lease" in lowered, (
        f"the note must say finance and capital leases are debt: {DEBT_BASIS_NOTE!r}"
    )
    assert "double count" in lowered or "rent already sits in operating expense" in lowered, (
        f"the note must say why operating leases are not also deducted: "
        f"{DEBT_BASIS_NOTE!r}"
    )


def test_the_basis_note_states_the_balance_sheet_date_is_published():
    """A net cash figure without its date cannot be reconciled with anything."""
    assert "date" in DEBT_BASIS_NOTE.lower()


def test_the_basis_note_discloses_the_lease_limitation():
    """The limitation is real and a reader comparing providers will hit it.

    A feed's debt total does not carry every issuer's full lease obligation, so a
    provider that capitalises all leases shows higher debt. Saying so is the
    difference between a difference the reader can explain and one they cannot.
    """
    lowered = DEBT_BASIS_NOTE.lower()
    assert "lease" in lowered
    assert "capitalis" in lowered or "capitaliz" in lowered, (
        f"the note must acknowledge providers that capitalise leases: {DEBT_BASIS_NOTE!r}"
    )
