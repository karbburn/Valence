"""A reconciliation gap must be decomposable, or it reads as a wrong figure.

`check_current_assets_reconcile` reported Infosys FY26 as 17,621 short and named nothing.
From the outside that is indistinguishable from a figure that is simply wrong, and the
two invite opposite reactions: distrust of the model, or a fix to the reader.

The gap decomposes exactly:

    prepayments_other_current_assets            15,703
    current_income_tax_assets                    1,835
    derivative_financial_assets_current             83
                                                 -----
                                                17,621   and unexplained 0.0

All three are captions the filer prints on p.100 and all three are dropped by the row
grouping defect in the PDF reader. So the engine now says which lines are absent, and
distinguishes an absent line from an over-count, because those need opposite fixes.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.validation import accounting_checks as ac  # noqa: E402


def _code_of(fn) -> str:
    """A function's source with docstrings and comments removed.

    Comments and docstrings are stripped because they are where source-scanning
    assertions go wrong. `check_current_assets_reconcile`'s docstring names
    `_absent_lines_note`, and an earlier version of the order assertion searched the
    WHOLE MODULE -- so it found the docstring's mention at module line 145, concluded
    the note was built before the collection, and a mutation that genuinely reversed the
    order passed.

    Stripping the prose and searching the function body is what makes the assertion
    about the CODE rather than about a sentence describing the code.
    """
    import inspect

    src = inspect.getsource(fn)
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    return re.sub(r"#.*$", "", code, flags=re.M)


def _spec_short_by(gap: float, absent: list[str]):
    """A specification whose itemised current assets fall short by `gap`.

    Built through the real model classes so the check reads the same `get_value` path it
    reads in production -- a stub with the right method name would pass while the real
    lookup behaved differently.

    `absent` names current-asset lines to leave out, which is how the "which lines are
    missing" question is posed at all.
    """
    from datetime import date

    from backend.models.spec.historicals import HistoricalLineItem, Historicals
    from backend.models.spec.metadata import ModelMetadata
    from backend.models.spec.model_specification import ModelSpecification

    present = [k for k in ac.CURRENT_ASSET_LINES if k not in absent]

    def _line(key: str, value: float) -> HistoricalLineItem:
        return HistoricalLineItem(
            canonical_key=key,
            period_label="FY26",
            period_end_date=date(2026, 3, 31),
            value=value,
            currency="INR",
            units="crores",
            status="reported",
            source_datapoint_ids=[],
        )

    # One line carries the whole subtotal-minus-gap figure; the rest are zero.
    lines = [_line(k, 0.0) for k in present[:-1]]
    lines.append(_line(present[-1], 100_000.0 - gap))
    lines.append(_line("canonical.bs.total_current_assets", 100_000.0))

    return ModelSpecification(
        metadata=ModelMetadata(company_id="probe", ticker="PROBE", name="Probe",
                               market="india", currency="INR", units="crores",
                               fiscal_year_end="March 31"),
        historicals=Historicals(periods=["FY26"], line_items=lines),
    )


class TestTheNoteNamesTheAbsentLines:
    def test_an_absent_line_is_named(self):
        note = ac._absent_lines_note(
            absent={"canonical.bs.inventory": "FY26"},
            failing_periods=["FY26"],
            missing_in=lambda k, p: True,
        )
        assert "inventory" in note, (
            "the absent line is not named, so the gap cannot be decomposed by whoever "
            "reads it: %r" % note
        )

    def test_the_key_prefix_is_stripped(self):
        """`canonical.bs.inventory` is noise in a message about a balance sheet."""
        note = ac._absent_lines_note(
            absent={"canonical.bs.prepayments_other_current_assets": "FY26"},
            failing_periods=["FY26"],
            missing_in=lambda k, p: True,
        )
        assert "canonical.bs." not in note, (
            "the canonical key prefix leaks into a reader-facing message: %r" % note
        )
        assert "prepayments_other_current_assets" in note

    def test_several_absent_lines_are_all_listed(self):
        keys = [
            "canonical.bs.prepayments_other_current_assets",
            "canonical.bs.current_income_tax_assets",
            "canonical.bs.derivative_financial_assets_current",
        ]
        note = ac._absent_lines_note(
            absent={k: "FY26" for k in keys},
            failing_periods=["FY26"],
            missing_in=lambda k, p: True,
        )
        for k in keys:
            assert k.replace("canonical.bs.", "") in note, (
                "%s is missing from the note %r" % (k, note)
            )

    def test_a_line_present_in_any_failing_period_is_not_called_always_absent(self):
        """Present in one period and absent in another is a DIFFERENT fault.

        Calling it "absent in every failing period" would misdescribe a period-specific
        ingestion gap as a caption the filer never prints.
        """
        note = ac._absent_lines_note(
            absent={"canonical.bs.inventory": "FY25"},
            failing_periods=["FY25", "FY26"],
            missing_in=lambda k, p: p != "FY26",   # present in FY26
        )
        assert "Absent in every failing period" not in note, (
            "a line present in FY26 was reported as absent everywhere: %r" % note
        )
        assert "period-specific" in note, (
            "the note should distinguish a per-period gap from a caption the filer "
            "never prints: %r" % note
        )


class TestTheNoteDistinguishesUnderFromOver:
    """A gap of minus three is a missing line; plus three is a double count."""

    def test_no_absent_line_means_the_block_exceeds_the_subtotal(self):
        note = ac._absent_lines_note(
            absent={},
            failing_periods=["FY26"],
            missing_in=lambda k, p: False,
        )
        assert "EXCEEDS" in note, (
            "with nothing absent the itemised block is too LARGE, and the note should "
            "say so -- the opposite diagnosis needs the opposite fix: %r" % note
        )
        assert "counted twice" in note

    def test_an_under_count_is_not_described_as_a_double_count(self):
        note = ac._absent_lines_note(
            absent={"canonical.bs.inventory": "FY26"},
            failing_periods=["FY26"],
            missing_in=lambda k, p: True,
        )
        assert "EXCEEDS" not in note, (
            "an under-count was described as an over-count: %r" % note
        )
        assert "counted twice" not in note

    def test_it_says_a_missing_line_may_be_correct(self):
        """Half the point of naming the line.

        A caption the filer does not print is correctly absent. Without that sentence a
        reader concludes every named line is a bug.
        """
        note = ac._absent_lines_note(
            absent={"canonical.bs.inventory": "FY26"},
            failing_periods=["FY26"],
            missing_in=lambda k, p: True,
        )
        assert "does not print" in note and "correctly absent" in note, (
            "the note does not say an unprinted caption is correctly absent: %r" % note
        )


class TestTheCheckStillReportsTheNumbers:
    """Naming lines must not displace the arithmetic."""

    def test_the_gap_and_subtotal_are_still_in_the_detail(self):
        src = (REPO / "backend" / "validation" / "accounting_checks.py").read_text(
            encoding="utf-8")
        assert "itemised current assets" in src and "gap {gap:+,.0f}" in src, (
            "the reconciliation no longer reports the signed gap per period, so the "
            "named lines arrive with no figure to attribute them to"
        )

    def test_the_helper_is_reachable_from_the_check(self):
        """A helper that exists and is never called is the defect this project keeps meeting."""
        import inspect

        code = _code_of(ac.check_current_assets_reconcile)
        assert "_absent_lines_note(" in code, (
            "the reconciliation does not call the helper, so the message is unchanged "
            "and the named lines appear nowhere"
        )

    def test_absent_lines_are_collected_before_the_note_is_built(self):
        """The note must be built from the collection, not from a fresh empty one.

        Asserted BEHAVIOURALLY, by running the check over a specification whose current
        assets genuinely fall short, and requiring the absent lines to appear in the
        message. Three source-scanning attempts at this assertion each failed:

          - one searched the whole module and found the DOCSTRING's mention of
            `_absent_lines_note` rather than the call
          - one moved the collection past an adjacent assignment, which does not
            reverse the relationship at all
          - one replaced the argument with `OrderedDict()`, and passed -- because every
            other test in this file calls the helper DIRECTLY, so nothing ever observed
            what the check itself passes in

        The last is the general lesson: a test that exercises a helper by calling the
        helper cannot see the caller getting the helper's argument wrong. This one runs
        the check.
        """
        spec = _spec_short_by(18_770.0, absent=[
            "canonical.bs.prepayments_other_current_assets",
            "canonical.bs.current_income_tax_assets",
        ])
        result = ac.check_current_assets_reconcile(spec)
        assert not result.passed, "the fixture is supposed to be short; it reconciles"
        detail = result.detail or ""
        for key in ("prepayments_other_current_assets", "current_income_tax_assets"):
            assert key in detail, (
                "%s is absent from the message, so the gap was not decomposed from the "
                "collection the check built. detail=%r" % (key, detail)
            )

    def test_the_collection_is_inside_the_failing_branch(self):
        """A line is only 'absent' if its period FAILED.

        Collecting absent lines for passing periods would name lines that are absent from
        a period that reconciles fine, which is noise at best and a wrong diagnosis at
        worst.
        """
        import inspect

        code = _code_of(ac.check_current_assets_reconcile)
        i_branch = code.find("if abs(gap) > max(")
        i_collect = code.find("absent.setdefault(")
        assert -1 < i_branch < i_collect, (
            "absent lines are collected at %r but the failing-period branch starts at "
            "%r; a line absent from a period that PASSES must not be named as missing"
            % (i_collect, i_branch)
        )
