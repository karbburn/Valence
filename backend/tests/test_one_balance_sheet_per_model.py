"""The forecast and the valuation must open on the same balance sheet.

Two numbers for the same debt in one model is not a rounding question. The debt
schedule carried what the filed borrowings were while the enterprise-value bridge
deducted a market feed's "total debt", which capitalises every lease it can find.
They agreed for two companies in six and disagreed by up to 50,062 for the rest,
so the schedule charged interest on a balance the valuation never deducted and
the valuation deducted obligations the schedule never serviced.

The fix is structural rather than numerical: there is one list of the components
that make up debt, and both sides read it. These tests state the relationship, not
the figures that happened to break, because the figures move with every filing
and the relationship does not.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from backend.forecast import engine as forecast_engine
from backend.forecast import pipeline as forecast_pipeline
from backend.forecast.debt import OPENING_BALANCE_KEYS
from backend.valuation import pipeline as valuation_pipeline


def _historical_model(company_id: str):
    from backend.models.statements.historical_model import build_historical_model
    from backend.normalization.taxonomy.models import CanonicalDatapoint

    rows = [
        ("canonical.is.revenue", "revenue", 61_000.0),
        ("canonical.is.operating_profit", "operating profit", 33_000.0),
        ("canonical.bs.cash_and_bank", "cash and bank", 10_605.0),
        # NVIDIA's filed FY26: 7,469 non-current, 999 current, no finance leases,
        # 2,572 of operating leases that are not debt.
        ("canonical.bs.borrowings", "borrowings", 7_469.0),
        ("canonical.bs.short_term_borrowings", "short term borrowings", 999.0),
        ("canonical.bs.finance_lease_liabilities", "finance leases", 0.0),
        ("canonical.bs.operating_lease_liabilities", "operating leases", 2_572.0),
    ]
    dps = [
        CanonicalDatapoint(
            id=f"{company_id}-{key}-FY26",
            company_id=company_id,
            canonical_key=key,
            metric_raw=raw,
            period_label="FY26",
            period_end_date=date(2026, 1, 25),
            value=value,
            currency="USD",
            units="millions",
            status="reported",
            source_datapoint_ids=[f"{company_id}-fixture"],
        )
        for key, raw, value in rows
    ]
    return build_historical_model(dps, target_periods=["FY26"])


def test_both_sides_read_the_one_debt_definition():
    """No module may name the debt components itself.

    The failure this replaces was three hand-written tuples with a comment in each
    asserting they must match. A comment cannot hold three lists together; a
    shared constant can. All three call sites are checked because two agreeing
    while the third drifts is still a model with two debts in it.
    """
    for module in (forecast_pipeline, forecast_engine, valuation_pipeline):
        source = inspect.getsource(module)
        assert "canonical.bs.short_term_borrowings" not in source, (
            f"{module.__name__} names a debt component itself instead of reading "
            f"OPENING_BALANCE_KEYS, so it can drift from the debt schedule and the "
            f"valuation bridge"
        )


def test_operating_leases_are_not_part_of_debt():
    """Rent is already inside the EBIT these cash flows are built from.

    Deducting the operating lease liability as well charges for the same
    obligation twice. NVIDIA's balance sheet carried 4,985 of it and Microsoft's
    21,925 for exactly this reason, before the bridge stopped reading a feed's
    aggregate.
    """
    assert "canonical.bs.operating_lease_liabilities" not in OPENING_BALANCE_KEYS
    assert all("operating_lease" not in key for key in OPENING_BALANCE_KEYS)


def test_finance_leases_are_part_of_debt():
    """A finance lease is borrowing in substance and is interest-bearing.

    Leaving it out would understate the obligation the valuation charges for, and
    understating debt overstates equity value, which is the direction that makes a
    price look better than the work supports. Microsoft reports 66,594 of them.
    """
    assert "canonical.bs.finance_lease_liabilities" in OPENING_BALANCE_KEYS


def test_the_definition_sums_to_the_filed_borrowings():
    """7,469 + 999 + 0. The 2,572 of operating leases stays out."""
    model = _historical_model("nvda_us")
    opening = 0.0
    for key in OPENING_BALANCE_KEYS:
        item = next(
            (i for i in model.balance_sheet.line_items if i.canonical_key == key),
            None,
        )
        if item is not None:
            opening += item.values_by_period.get("FY26", 0.0)
    assert opening == pytest.approx(8_468.0)


def test_the_operating_lease_is_still_reported():
    """Excluding a material liability silently is as much an error as including it.

    Meta's operating leases are 25,153 against 59,928 of debt, so a reader is
    choosing between two conventions and needs the number to do it.
    """
    model = _historical_model("meta_us")
    item = next(
        i for i in model.balance_sheet.line_items
        if i.canonical_key == "canonical.bs.operating_lease_liabilities"
    )
    assert item.values_by_period["FY26"] == pytest.approx(2_572.0)
