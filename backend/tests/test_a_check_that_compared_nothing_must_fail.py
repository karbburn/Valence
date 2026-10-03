"""A reconciliation check that compared nothing must fail, not pass.

`check_current_assets_reconcile` skips any period with no filed current-asset subtotal:

    for p in spec.historicals.periods:
        subtotal = get_value("canonical.bs.total_current_assets", p)
        if subtotal is None:
            continue

If that is true of EVERY period then the loop body never runs, nothing accumulates into
`errors`, and `passed = not errors` returns True. The check reports "current assets
reconcile" without having read a single figure.

Measured across the 23 shipped models before this was fixed: **11 of them -- every India
name -- hold no `canonical.bs.total_current_assets` in any period, so all 11 passed
vacuously.** Every one of them is `opinion_only`, so no published figure was affected, which
is exactly why this could sit unnoticed: the check was green, the models were withheld for
other reasons, and nothing looked wrong.

That is the project's own rule inverted. It is written into `provenance.py` and
`test_publication_requires_a_filing.py`: a check that cannot find its subject has not
verified it, and an unverified check that reports success is believed. A red check gets
looked at; a green one that examined nothing does not.

The counter is deliberately about PERIODS EXAMINED rather than about which keys are missing.
A model with no current-asset lines at all is a different question -- it may simply not
carry them -- and that question is answered by `inputs_trace_to_a_filing`, not here. What
this check must never do is claim a reconciliation it did not perform.
"""

from __future__ import annotations

from datetime import date

from backend.models.spec.historicals import HistoricalLineItem, Historicals
from backend.models.spec.metadata import ModelMetadata
from backend.models.spec.model_specification import ModelSpecification
from backend.validation import accounting_checks as ac
from backend.validation.accounting_checks import check_current_assets_reconcile

COMPANY = "reconcile_probe"


def _spec(*, with_subtotal: bool, cash: float = 100.0) -> ModelSpecification:
    """A spec built through the real model classes.

    Deliberately not a stub: the check reads `Historicals.get_value`, so a fake object with
    a method of the same name would pass here while the production lookup behaved
    differently. That has happened in this suite before.
    """
    def _line(key: str, value: float) -> HistoricalLineItem:
        return HistoricalLineItem(
            canonical_key=key, period_label="FY26",
            period_end_date=date(2026, 3, 31), value=value,
            currency="INR", units="crores", status="reported",
            source_datapoint_ids=[],
        )

    lines = [_line("canonical.bs.cash_and_bank", cash)]
    if with_subtotal:
        lines.append(_line("canonical.bs.total_current_assets", 100.0))

    return ModelSpecification(
        metadata=ModelMetadata(company_id=COMPANY, ticker="PROBE", name="Probe",
                               market="india", currency="INR", units="crores",
                               fiscal_year_end="March 31"),
        historicals=Historicals(periods=["FY26"], line_items=lines),
    )


class TestTheCheckCannotPassHavingComparedNothing:
    def test_no_filed_subtotal_in_any_period_fails(self):
        """The defect, exactly as it occurred on 11 shipped models."""
        res = check_current_assets_reconcile(_spec(with_subtotal=False))
        assert not res.passed, (
            "the check PASSED with no filed current-asset subtotal in any period, so it "
            "compared nothing and reported a reconciliation it did not perform"
        )
        assert "No period carries a filed current-asset subtotal" in res.detail, (
            "the failure must say WHY, or a reader cannot tell a vacuous pass from a "
            "real gap. Got: %r" % res.detail
        )

    def test_the_failure_names_the_key_it_looked_for(self):
        res = check_current_assets_reconcile(_spec(with_subtotal=False))
        assert "canonical.bs.total_current_assets" in res.detail, (
            "the message must name the missing key so the gap is actionable: %r"
            % res.detail
        )

    def test_it_implicates_every_scenario(self):
        res = check_current_assets_reconcile(_spec(with_subtotal=False))
        assert set(res.implicated_scenarios or []) == {"base", "bull", "bear"}, (
            "a check that cannot verify its subject must implicate every scenario, "
            "otherwise a model can publish on a check that never ran: %r"
            % (res.implicated_scenarios,)
        )


class TestTheCheckStillDoesItsJobWhenItCan:
    """A guard that always fails is as useless as one that always passes."""

    def test_a_reconciling_model_still_passes(self):
        res = check_current_assets_reconcile(_spec(with_subtotal=True))
        assert res.passed, (
            "a model whose itemised current assets DO reach the filed subtotal must still "
            "pass. The counter must not turn a working reconciliation red: %r"
            % res.detail
        )

    def test_a_real_gap_is_still_reported(self):
        """Cash of 60 against a filed subtotal of 100 is a genuine 40-unit gap."""
        res = check_current_assets_reconcile(_spec(with_subtotal=True, cash=60.0))
        assert not res.passed, "a real 40-unit gap passed"
        assert "Itemised current assets do not reach" in res.detail, (
            "the gap must be reported as a gap, not as a vacuous pass: %r" % res.detail
        )