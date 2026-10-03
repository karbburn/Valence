"""A page whose column layout cannot be established must raise, not parse.

`_year_anchors` locates the figure columns by finding a period header to the right of the
label boundary, and derives the column window from those positions. A filer that prints a
full date instead of a bare year has no anchors, so there is no window, and the page raises
`no fiscal-year header row found` before a single row is read.

That is the correct behaviour, and this file exists because I got it wrong first.

WHAT WAS TRIED. A `_period_year` helper was added so `31.03.2024` would be recognised like
a bare `2026`. Measured after the change, everything looked like a clean win:

    TCS p.11/p.20      2 anchors  [2026, 2025]   unchanged
    HCLTECH p.5/p.6    2 anchors  [2026, 2026]   unchanged
    Infosys p.99/100/105                          unchanged
    TATASTEEL p.17     RAISES -> 1 anchor [2024]  now parses
    TATASTEEL p.21     RAISES -> 1 anchor [2024]  now parses

THEN THE OUTPUT WAS READ. `parse_predicted_statement_page` on that p.17 returned 36
datapoints including the filer's registered office, ingested as figures:

    Tel 91 22 6665 8282 Fax91 22                  -> 6665.0
    omhce Bombay House Hom Mody Street            ->    1.0
    (Purchase)/sale of current mvestments (net)   ->  2.667

p.17 IS the standalone balance sheet -- its own heading reads `Standalone Balance Sheet as at
3lst March 2024` -- so those are balance-sheet lines built from the wrong column. The reason
is one measurement: with a single anchor at x=386 the window is `336..436`, and 45 figure
words fall inside it while 40 fall outside. The prior-year column's header is `31.03.202.3`,
a dropped digit, so it is neither a date nor a year and only one column is ever found.

So the change turned an honest failure into 36 confident wrong numbers, on the page type
where a wrong figure is least likely to be noticed. It was reverted.

WHY NOT "REQUIRE TWO ANCHORS". Measured: Infosys p.99 and p.105 each carry exactly ONE
anchor and parse correctly today. A two-anchor rule would break two working pages to rescue
two that cannot be trusted anyway.

The guard here is therefore not "two anchors" but "do not parse a face whose own period
header is not legible". These tests pin that, and they are written to be re-run against any
future attempt at this.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.parsers import pdf_tables  # noqa: E402


class TestAnUnreadablePeriodHeaderRaises:
    """The honest failure, asserted so it cannot be quietly traded for output."""

    def test_a_page_with_no_bare_year_raises(self):
        """Tata Steel's shape: the header is a date, so no anchor is found.

        A stub page is used rather than the PDF, so the test states the rule rather than
        depending on a 15 MB download being present.
        """

        class _Page:
            """Words as pdfplumber returns them: x0, top, text."""

            def __init__(self, words):
                self._words = words

            def extract_words(self):
                return self._words

        # Header carries dates only, and both dates sit right of the label boundary.
        page = _Page([
            {"x0": 100.0, "top": 100.0, "text": "Standalone"},
            {"x0": 160.0, "top": 100.0, "text": "Balance"},
            {"x0": 200.0, "top": 100.0, "text": "Sheet"},
            {"x0": 386.5, "top": 126.8, "text": "31.03.2024"},
            {"x0": 448.9, "top": 126.8, "text": "31.03.202.3"},
            {"x0": 400.0, "top": 150.0, "text": "90,806"},
        ])
        try:
            anchors = pdf_tables._year_anchors(page)
        except ValueError:
            return
        raise AssertionError(
            "a header with no bare year produced anchors %r. A date-shaped header leaves "
            "the column window underived, and the page then parses figures from whichever "
            "column happens to fall inside a window built from one anchor -- which is how "
            "a registered-office phone number became a balance-sheet line."
            % (anchors,)
        )

    def test_a_bare_year_still_anchors(self):
        """The working path must keep working, or the guard above proves nothing."""

        class _Page:
            def extract_words(self):
                return [
                    {"x0": 100.0, "top": 100.0, "text": "BALANCE"},
                    {"x0": 450.0, "top": 126.9, "text": "2026"},
                    {"x0": 538.0, "top": 126.9, "text": "2025"},
                ]

        anchors = pdf_tables._year_anchors(_Page())
        assert [y for _, y in anchors] == [2026, 2025], (
            "bare-year anchoring changed: %r" % (anchors,)
        )

    def test_two_columns_may_share_one_year(self):
        """HCLTech's face reads "As at 30 June 2026" and "As at 31 March 2026".

        Both period ends fall in 2026, so the anchors are [(427.8, 2026), (530.2, 2026)].
        A fix that required distinct years would reject a filer that is correct today.
        """

        class _Page:
            def extract_words(self):
                return [
                    {"x0": 408.2, "top": 112.8, "text": "As"},
                    {"x0": 427.8, "top": 126.9, "text": "2026"},
                    {"x0": 530.2, "top": 126.9, "text": "2026"},
                ]

        anchors = pdf_tables._year_anchors(_Page())
        assert [y for _, y in anchors] == [2026, 2026], (
            "a filer with two columns in the same year was rejected: %r" % (anchors,)
        )

    def test_a_bare_year_is_matched_whole_not_substring(self):
        """`20\\d\\d` must not match inside a figure.

        Matching anywhere would let a DATA cell containing 2026 invent a column anchor, and
        a page with no header at all would then parse against an invented window.
        """

        class _Page:
            def extract_words(self):
                return [
                    {"x0": 400.0, "top": 150.0, "text": "2,026"},
                    {"x0": 450.0, "top": 151.0, "text": "12026"},
                ]

        try:
            anchors = pdf_tables._year_anchors(_Page())
        except ValueError:
            return
        raise AssertionError(
            "figures were accepted as period headers: %r. Only a standalone four-digit "
            "token in the header row is an anchor." % (anchors,)
        )


class TestTheRemainingDefectIsTheTextLayer:
    """Why anchor work is the wrong stage, recorded where the next person will read it.

    The blocking problem is not that the header is a date. It is that the glyphs are
    missing, so the column layout cannot be established at any resolution:

        Standalone Balance Sheet as at 3lst March 2024   (`1st` -> `3lst`)
        31.03.202.3                                      (2023 -> 202)
        Current habhtes                                 (liabilities)
        Cash and cash equalents                         (equivalents)

    A parser may recognise these; it may not invent the missing glyphs. Recovering figures
    from a layer that silently turns a year into a two-digit number risks a right-sized
    figure on the wrong period, which is harder to notice than a missing one and worse to
    publish.
    """

    def test_this_file_documents_the_reverted_attempt(self):
        src = (REPO / "backend" / "tests" /
               "test_a_page_whose_columns_are_unknown_must_raise.py").read_text(
                   encoding="utf-8")
        for marker in ("31.03.202.3", "6665.0", "reverted"):
            assert marker in src, (
                "this file is the record of a reverted change; it must keep saying why. "
                "Missing: %r" % marker
            )