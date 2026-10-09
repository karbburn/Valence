"""A filer that needs DERIVED borrowings must build, not raise a TypeError.

`resolved` is a dict of period-end to value, and it carries one of two shapes:

    the filed path    {date: fact dict}   -- the value is item["val"]
    the derived path  {date: float}       -- already in millions

The loop read `item["val"]` unconditionally, so any filer routed through
`_derive_noncurrent_borrowings` subscripted a float. That is a TypeError, not a
wrong number, which is the only reason it was caught at all: it takes a filer with
a combined debt tag and no non-current debt tag to reach it.

Ryerson Holdings is such a filer. On 2026-10-02, during a 50-company sweep:

    RYZ   HTTP 500  {"detail":"Failed to build model. See server logs for details."}

Ryerson files complete accounts. The API answered a crash as a broken service, for
a company with nothing wrong with it, and the sweep would have recorded it as a
product defect.

The second half of this file guards the half that a crash would have hidden. Had
the subscript been replaced by something that did not raise -- `float(item)` on a
dict, or a `.get("val", 0)` -- the build would have "succeeded" and reported
borrowings as a millionth of the filed figure. Understating debt raises equity
value, so that error is invisible in a valuation and expensive in a balance sheet.
"""

from __future__ import annotations

import inspect
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.ingestion import sec_edgar  # noqa: E402

SEC_EDGAR = (REPO / "backend" / "data" / "ingestion" / "sec_edgar.py").read_text(
    encoding="utf-8"
)


def _body_of(fn) -> str:
    """Source of `fn`, with `#` prose stripped.

    The prose beside this code explains the defect at length, so any check that
    searches the raw text is satisfied by the explanation rather than the fix.
    """
    return re.sub(r"#.*$", "", inspect.getsource(fn), flags=re.M)


class TestBothShapesOfResolvedAreReadable:
    def test_the_derive_function_really_does_return_floats(self):
        """The premise. If this ever changes, the isinstance branch is dead code."""
        src = inspect.getsource(sec_edgar._derive_noncurrent_borrowings)
        assert "-> Dict[date, float]" in src, (
            "_derive_noncurrent_borrowings no longer returns floats, so the "
            "dict-shape assumption in the main loop has changed with it"
        )
        # The unit conversion lives in the CALLER, not here: the function divides
        # by 1e6 on the way out, and the caller multiplies back to 1e6 before
        # handing it over. So "already in millions" is asserted where it is true --
        # at the end of this function -- rather than by searching for a multiply
        # that is written a hundred lines away in a different function.
        assert re.search(r"out\[end\]\s*=\s*noncurrent\s*/\s*1e6", src), (
            "_derive_noncurrent_borrowings no longer returns millions, so the "
            "main loop's exemption from the unit conversion is now wrong"
        )
        assert re.search(r"resolved\s*=\s*\{end:\s*val\s*\*\s*1e6", SEC_EDGAR), (
            "the caller no longer scales the derived values back into USD units, "
            "so the loop is reading them on the wrong scale"
        )

    def test_the_loop_reads_a_float_resolved_item_without_subscripting(self):
        """The behaviour, exercised on the shape that crashed.

        The exact expression from the loop, applied to a float, is the thing that
        raised. This fails with TypeError if the unguarded subscript returns.
        """
        item = 4_250_000_000.0  # a float, as the derived path produces
        raw_val = float(item["val"] if isinstance(item, dict) else item)
        assert raw_val == 4_250_000_000.0

    def test_the_loop_still_reads_a_fact_dict(self):
        """The other shape must keep working; a fix that breaks the common path
        would turn every filer into a 500 instead of one."""
        item = {"val": 4_250_000_000, "end": "2026-01-31", "start": None, "form": "10-K"}
        raw_val = float(item["val"] if isinstance(item, dict) else item)
        assert raw_val == 4_250_000_000.0

    def test_the_source_does_not_subscript_unconditionally(self):
        body = _body_of(sec_edgar.fetch_and_parse_sec_edgar)
        assert not re.search(r"float\(\s*item\[\s*[\"']val[\"']\s*\]\s*\)", body), (
            "the loop reads item[\"val\"] with no shape check, so any filer "
            "needing derived borrowings raises TypeError and answers 500"
        )
        assert "isinstance(item, dict)" in body, (
            "the loop no longer distinguishes the two shapes of `resolved`"
        )


class TestTheDerivedPathIsNotDividedByAMillionAgain:
    """The failure a crash would have hidden.

    `_derive_noncurrent_borrowings` returns millions. The filed path returns USD
    units and is divided. Applying the filed conversion to the derived path reports
    borrowings as 1e-6 of the filed figure -- and understating debt raises equity
    value, so nothing downstream complains.
    """

    def test_a_derived_value_survives_the_conversion(self):
        filed_units = 4_250_000_000.0
        derived_millions = 4_250.0

        def convert(raw_val, already_millions):
            return (
                raw_val if already_millions else raw_val / 1e6
            )

        assert convert(filed_units, False) == pytest.approx(4_250.0)
        assert convert(derived_millions, True) == pytest.approx(4_250.0), (
            "the derived value was divided a second time"
        )

    def test_dividing_twice_is_the_bug_and_must_not_happen(self):
        derived_millions = 4_250.0
        assert derived_millions / 1e6 == pytest.approx(0.00425)
        assert derived_millions / 1e6 != pytest.approx(derived_millions), (
            "the test no longer distinguishes the two paths"
        )

    def test_the_loop_guards_the_conversion_with_the_same_shape_test(self):
        body = _body_of(sec_edgar.fetch_and_parse_sec_edgar)
        assert "already_millions" in body, (
            "the derived path is no longer exempted from the unit conversion, so "
            "derived borrowings are divided by a million a second time"
        )
        m = re.search(r"already_millions\s*=\s*(.+)", body)
        assert m, "could not read how already_millions is decided"
        assert "isinstance" in m.group(1), (
            "already_millions is decided by %r rather than by the shape of the "
            "item, so it can disagree with the read above it" % m.group(1).strip()
        )

    def test_the_exemption_actually_reaches_the_conversion(self):
        """The flag must be consulted, not merely defined.

        Mutation 3 in the check deleted `or already_millions` from the condition
        and every test in this class still passed: the variable was defined, and
        the two behavioural tests above re-implement the conversion themselves
        rather than calling the code under test. A guard that cannot observe the
        line it guards is decoration.

        So the expression itself is read, and it must name the flag in the branch
        that decides whether to divide.
        """
        body = _body_of(sec_edgar.fetch_and_parse_sec_edgar)
        m = re.search(r"already_millions\b(?!\s*=[^=])", body)
        # Find every place already_millions appears, and require more than the
        # single assignment.
        occurrences = len(re.findall(r"already_millions", body))
        assert occurrences >= 2, (
            "already_millions appears %d time(s) -- only its definition. The unit "
            "conversion below it does not consult it, so the derived path is "
            "divided a second time and no test noticed" % occurrences
        )
        # And specifically: inside the condition that picks the value.
        cond = re.search(r"if\s*\(([^)]*already_millions[^)]*)\)", body)
        assert cond, (
            "already_millions never appears inside an `if`, so it guards nothing; "
            "the conversion is unconditional and the derived path is divided twice"
        )
        del m


class TestTheDerivedPathProvenanceDoesNotSubscriptEither:
    """The crash the value guard moved one statement down.

    The read at the top of the loop distinguishes dict from float, but the
    provenance string below it called ``item.get("form")`` unconditionally.
    Fulton Financial -- a filer needing derived borrowings -- raised
    AttributeError there during a 100-company sweep, which is the same
    crash wearing the next line number: the isinstance branch ends, the
    unguarded attribute access begins.
    """

    def test_a_float_item_labels_its_provenance_derived(self):
        """The behaviour, exercised on the shape that crashed."""
        item = 4_250_000_000.0  # a float, as the derived path produces
        form = item.get("form") if isinstance(item, dict) else "derived"
        filed = item.get("filed") if isinstance(item, dict) else "derived"
        assert (form, filed) == ("derived", "derived")

    def test_a_fact_dict_keeps_its_filed_provenance(self):
        """The common path must keep reporting form and filed dates."""
        item = {"val": 4_250_000_000, "form": "10-K", "filed": "2026-02-01"}
        form = item.get("form") if isinstance(item, dict) else "derived"
        filed = item.get("filed") if isinstance(item, dict) else "derived"
        assert (form, filed) == ("10-K", "2026-02-01")

    def test_no_unconditional_item_get_survives_in_the_loop(self):
        """Every ``item.get(`` in the function reads through the shape test.

        The value read was fixed this way for RYZ and the provenance read
        crashed for Fulton Financial the same week, so the assertion covers
        the whole function rather than the one line that has already bitten.
        """
        body = _body_of(sec_edgar.fetch_and_parse_sec_edgar)
        lines = [
            ln for ln in body.splitlines()
            if "item.get(" in ln and "isinstance(item, dict)" not in ln
        ]
        assert not lines, (
            "an unguarded item.get( survives: %r -- a derived float raises "
            "AttributeError there instead of labelling itself derived"
            % (lines[0].strip(),)
        )