"""A feed that bundles leases into borrowings must have the lease taken back out.

The feed publishes borrowings either as a pure row or bundled with a lease
obligation, and where the two differ it publishes both, so the lease is always
separable. Reading the bundled row as borrowings put leases into the debt the
valuation deducts: Meta reported 2,213 of "Current Debt And Capital Lease
Obligation" that was the current portion of its lease liability, and Ambarella's
entire 2,027 current row was a lease. Rent is already inside the EBIT these cash
flows are built from, so both charged for the same obligation twice.

These are the shapes the resolution has to get right. The figures are the ones
observed from the feed, not invented for the test.
"""

from __future__ import annotations

import pytest

from backend.data.ingestion.feed_borrowings import index_rows, resolve_borrowings


def _rows(*labels: str) -> dict:
    return index_rows(labels)


def _cell(values: dict):
    def read(label):
        return values.get(str(label).strip().lower())

    return read


def test_a_pure_row_is_taken_as_it_stands():
    """Nothing to take out, so the figure is the figure."""
    rows = _rows("Long Term Debt", "Long Term Debt And Capital Lease Obligation")
    got = resolve_borrowings(rows, _cell({"long term debt": 83_664.0}))

    assert got == [("Borrowings", "Long Term Debt", 83_664.0, False)]


def test_a_lease_bundled_into_the_borrowings_is_subtracted():
    """Meta's case: no pure row, and the whole combined figure is a lease."""
    rows = _rows(
        "Current Debt And Capital Lease Obligation",
        "Current Capital Lease Obligation",
    )
    got = resolve_borrowings(
        rows,
        _cell(
            {
                "current debt and capital lease obligation": 2_213.0,
                "current capital lease obligation": 2_213.0,
            }
        ),
    )

    # Entirely lease, so nothing is left to borrow: an issuer filing no current
    # debt must not be given some by reading a lease as one.
    assert got == []


def test_genuine_debt_survives_a_combined_caption():
    """The reason the combined row is subtracted rather than discarded.

    Discarding it deleted Ambarella's whole current-debt line, which left the
    company with no debt and its implied price rose. Understating the obligation
    is the direction that flatters a valuation.
    """
    rows = _rows(
        "Current Debt And Capital Lease Obligation",
        "Current Capital Lease Obligation",
    )
    got = resolve_borrowings(
        rows,
        _cell(
            {
                "current debt and capital lease obligation": 1_500.0,
                "current capital lease obligation": 200.0,
            }
        ),
    )

    assert got == [
        ("Short term borrowings", "Current Debt And Capital Lease Obligation", 1_300.0, False)
    ]


def test_a_combined_caption_with_no_lease_split_is_taken_whole_and_flagged():
    """It cannot be shown to be free of leases, so it is not presented as if it were.

    Taking it whole overstates the obligation, which is the recoverable direction;
    taking nothing understates it, which raises the implied share price.
    """
    rows = _rows("Long Term Debt And Capital Lease Obligation")
    got = resolve_borrowings(
        rows, _cell({"long term debt and capital lease obligation": 9_000.0})
    )

    assert got == [
        (
            "Borrowings",
            "Long Term Debt And Capital Lease Obligation",
            9_000.0,
            True,
        )
    ]


def test_a_pure_row_that_is_missing_falls_through_to_the_combined_caption():
    """A filer that publishes only the combined caption still gets a debt figure."""
    rows = _rows(
        "Current Debt And Capital Lease Obligation",
        "Current Capital Lease Obligation",
    )
    got = resolve_borrowings(
        rows,
        _cell(
            {
                "current debt and capital lease obligation": 4_000.0,
                "current capital lease obligation": 1_000.0,
            }
        ),
    )

    assert got[0][0] == "Short term borrowings"
    assert got[0][2] == 3_000.0


def test_a_pure_row_holding_nothing_falls_through_to_the_combined_caption():
    """The feed publishes the row and leaves it blank, which is not a value of zero.

    Treating a blank as zero would report a company as carrying no current debt
    and, on a filer that does carry some, understate the obligation by the whole
    of it.
    """
    rows = _rows(
        "Current Debt",
        "Current Debt And Capital Lease Obligation",
        "Current Capital Lease Obligation",
    )
    got = resolve_borrowings(
        rows,
        _cell(
            {
                "current debt": float("nan"),
                "current debt and capital lease obligation": 4_000.0,
                "current capital lease obligation": 1_000.0,
            }
        ),
    )

    assert got == [
        (
            "Short term borrowings",
            "Current Debt And Capital Lease Obligation",
            3_000.0,
            False,
        )
    ]


def test_a_pure_row_holding_zero_is_taken_as_zero():
    """Zero is an answer. The feed published the row and it says the filer owes nothing."""
    rows = _rows("Current Debt", "Current Debt And Capital Lease Obligation")
    got = resolve_borrowings(rows, _cell({"current debt": 0.0}))

    assert got == [("Short term borrowings", "Current Debt", 0.0, False)]


def test_a_lease_larger_than_the_combined_figure_does_not_produce_negative_borrowings():
    """A feed inconsistent with itself must not produce a negative liability."""
    rows = _rows(
        "Current Debt And Capital Lease Obligation",
        "Current Capital Lease Obligation",
    )
    got = resolve_borrowings(
        rows,
        _cell(
            {
                "current debt and capital lease obligation": 100.0,
                "current capital lease obligation": 400.0,
            }
        ),
    )

    assert got == []


def test_both_lines_are_resolved_independently():
    """One side having a pure row must not decide the other."""
    rows = _rows(
        "Long Term Debt",
        "Current Debt And Capital Lease Obligation",
        "Current Capital Lease Obligation",
    )
    got = resolve_borrowings(
        rows,
        _cell(
            {
                "long term debt": 5_000.0,
                "current debt and capital lease obligation": 900.0,
                "current capital lease obligation": 400.0,
            }
        ),
    )

    by_label = {label: value for label, _row, value, _u in got}
    assert by_label == {"Borrowings": 5_000.0, "Short term borrowings": 500.0}


def test_a_filer_with_no_debt_row_gets_no_borrowings_at_all():
    """Absence is not zero, and publishing nothing is better than publishing a row."""
    rows = _rows("Total Assets", "Total Equity")
    assert resolve_borrowings(rows, _cell({"total assets": 1.0})) == []


@pytest.mark.parametrize("label", ["long term debt", "current debt"])
def test_row_matching_ignores_case_and_surrounding_space(label: str):
    """The feed's labels are not reliably trimmed, and the arithmetic must still run."""
    rows = _rows(f"  {label.title()}  ")
    got = resolve_borrowings(rows, _cell({label: 42.0}))

    assert got and got[0][2] == 42.0
