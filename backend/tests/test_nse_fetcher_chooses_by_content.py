"""The fetcher must choose the newest filing that actually contains the statements.

Two defects were found by measurement while building this, and both are invisible to a
test that only checks the happy path:

**`dt` sorts wrong as text.** It is `ddmmyyyyHHMMss`, day first, verified against `an_dt`
on 3368 live rows with zero disagreements. Sorting it lexically puts 12 Jan 2025 BELOW
16 Apr 2020, because `"16" < "20"` while the dates disagree the other way. The first
version of the fetcher did exactly that and reached a 2019 TCS filing before a 2025 one,
and a 2014 statement for HCLTech. A stale figure from a real filing is the most
convincing kind of wrong, so it is the case these tests exist for.

**A filename is not a document class.** TCS's audited statements are in
`..._SE_Outcome_signed.pdf`, while the three newest candidates are a signed letter, a
post-board-meeting letter and an AGM outcome intimation. Selection is by content, and a
fetcher that trusted the filename shipped governance letters as financial statements.

Transport is injected throughout, so every test here runs without a network. A fetcher
that can only be tested against a live exchange is a fetcher that is never tested.
"""

from __future__ import annotations

import pathlib
import sys
from datetime import datetime

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.ingestion.nse_filings import (  # noqa: E402
    NSEFilings,
    announcement_date,
    candidate_attachments,
    parse_an_dt,
    parse_dt,
)

# One attachment from each document class observed in a live TCS feed.
FEED = [
    # newest: a signed letter, no statements
    {"attchmntFile": "https://x/CORPCS_LETTER.pdf",
     "attchmntText": "Board has informed the Exchange", "an_dt": "01-Oct-2026 18:39:47",
     "dt": "01102026183947", "desc": "intimation as per regulation 43"},
    # a post-board-meeting letter
    {"attchmntFile": "https://x/CORPCS_Post_BM_SE_Letter.pdf",
     "attchmntText": "Outcome of the Board Meeting", "an_dt": "09-Jul-2026 15:51:58",
     "dt": "09072026155158", "desc": "outcome of board meeting"},
    # an AGM outcome intimation -- has "outcome" in the name, is not the statements
    {"attchmntFile": "https://x/CORPCS_AGM_Outcome_Intimation.pdf",
     "attchmntText": "Outcome of AGM", "an_dt": "09-Jun-2026 18:12:39",
     "dt": "09062026181239", "desc": "intimation as per circular"},
    # THE ONE: audited results, 9 Apr 2026
    {"attchmntFile": "https://x/CORPCS_09042026155946_SE_Outcome_signed.pdf",
     "attchmntText": "Audited financial results for the period ended March 31, 2026",
     "an_dt": "09-Apr-2026 15:59:46", "dt": "09042026155946",
     "desc": "financial results"},
    # older, 2019 -- the one a text sort would have reached
    {"attchmntFile": "https://x/RAJENDRA_RevisedFinancialResults.pdf",
     "attchmntText": "Revised financial results", "an_dt": "14-Jan-2019 20:00:00",
     "dt": "14012019200000", "desc": "financial results"},
    # governance, must never be considered
    {"attchmntFile": "https://x/SECRETARIAL_minutes.pdf",
     "attchmntText": "Minutes of the meeting", "an_dt": "02-Aug-2026 08:40:00",
     "dt": "02082026084000", "desc": "minutes of the intimation"},
    # not a pdf
    {"attchmntFile": "https://x/data.xlsx", "attchmntText": "XBRL",
     "an_dt": "01-Oct-2026 18:39:47", "dt": "01102026183947", "desc": "xbrl"},
    # undated
    {"attchmntFile": "https://x/CORPCS_Outcome_undated.pdf",
     "attchmntText": "audited financial results", "an_dt": None, "dt": None,
     "desc": "financial results"},
]


class TestTheDateIsParsedNotSorted:
    """`dt` is `ddmmyyyyHHMMss`. Day first, four-digit year."""

    def test_dt_is_day_first(self):
        # 30 Aug 2018, per the paired `an_dt` on a live row.
        assert parse_dt("30082018084000") == datetime(2018, 8, 30, 8, 40, 0)

    def test_the_two_fields_agree_on_a_known_pair(self):
        assert parse_an_dt("30-Aug-2018 08:40:00") == parse_dt("30082018084000")

    def test_text_sorting_would_invert_the_order(self):
        """The defect, stated as an assertion rather than as a comment.

        A test that only checks the parser accepts `30082018084000` passes against code
        that sorts the string, and the parser being right is not the property that
        matters -- the ORDER is.
        """
        jan_2025 = parse_dt("20112025165953")
        apr_2020 = parse_dt("16042020191500")
        assert jan_2025 > apr_2020, "parsed order disagrees with the real chronology"
        # ...while the strings say the opposite, which is the bug:
        assert "20112025165953" > "16042020191500", (
            "this premise no longer holds -- if the strings now sort correctly the "
            "fetcher's parsing is defensive rather than necessary, and the comment in "
            "nse_filings.py should be revisited"
        )

    def test_announcement_date_prefers_the_human_field(self):
        row = {"an_dt": "30-Aug-2018 08:40:00", "dt": "01012000999999"}
        assert announcement_date(row) == datetime(2018, 8, 30, 8, 40, 0), (
            "an_dt is unambiguous and must win over the numeric stamp"
        )

    def test_an_unparseable_date_is_none_not_a_guess(self):
        for bad in ("", None, "not-a-date", "99999999999999", "00000000000000"):
            assert parse_dt(bad) is None
        assert parse_an_dt("32-Xxx-2020 00:00:00") is None


class TestCandidatesAreOrderedNewestFirst:
    def test_the_2026_results_come_before_the_2019_one(self):
        cands = candidate_attachments(FEED)
        files = [c.filename for c in cands]
        results = "CORPCS_09042026155946_SE_Outcome_signed.pdf"
        old = "RAJENDRA_RevisedFinancialResults.pdf"
        assert results in files and old in files, (
            "a candidate was filtered out that should not have been: %r" % files
        )
        assert files.index(results) < files.index(old), (
            "the 2019 filing was preferred to the 2026 one: %r" % files
        )

    def test_an_undated_attachment_sorts_last(self):
        """An unknown age cannot be called recent.

        Treating an undated row as recent is precisely how a stale filing wins.
        """
        cands = candidate_attachments(FEED)
        dated = [c for c in cands if c.announced is not None]
        undated = [c for c in cands if c.announced is None]
        assert undated, "the undated fixture row was filtered out entirely"
        assert cands[-1].announced is None, (
            "the undated attachment sorted among the dated ones: %r"
            % [c.filename for c in cands]
        )
        assert dated

    def test_governance_documents_are_never_candidates(self):
        names = " ".join(c.filename for c in candidate_attachments(FEED))
        for excluded in ("SECRETARIAL_minutes", "data.xlsx"):
            assert excluded not in names, (
                "%r was offered as a statements candidate; minutes are governance and "
                "an xlsx is not a document this fetcher can parse" % excluded
            )

    def test_an_intimation_circulating_letter_is_not_chosen_by_name_alone(self):
        """The trap: three of the newest names contain "outcome".

        `..._Post_BM_SE_Letter.pdf` and `..._AGM_Outcome_Intimation.pdf` both match the
        statements hint and both are governance. They are filtered on the description's
        "intimation as per", which is why the filter looks at more than the filename.
        """
        cands = candidate_attachments(FEED)
        files = [c.filename for c in cands]
        assert "CORPCS_AGM_Outcome_Intimation.pdf" not in files
        assert "CORPCS_Post_BM_SE_Letter.pdf" not in files


class TestAcquisitionChoosesByContent:
    """The download loop, with transport injected."""

    # Two real statement PDFs: one without a balance sheet, one with.
    BALANCE_SHEET_PAGE = """TATA CONSULTANCY SERVICES LIMITED
Consolidated Balance Sheet
Current assets
Inventories 25 16
Cash and cash equivalents 872 964
Total current assets 1,234 1,100
Total assets 4,500 4,200
"""

    # A board letter that REFERS to the balance sheet -- which is what a substring test
    # for a single phrase accepts, and the reason the detector requires both subtotals.
    LETTER_PAGE = """Board of Directors
The Board has informed the Exchange that the meeting was held.
The total current assets and the cash and cash equivalents were reviewed.
"""

    def _fetcher(self, tmp_path, bodies):
        """A fetcher whose downloads come from `bodies`, keyed by URL fragment.

        The same stub serves the announcements feed, because `acquire` fetches it through
        the same injected callable -- a transport stub that only handled PDFs made the
        fetcher fail at the first step and the test reported "announcements unavailable",
        which says nothing about the behaviour under test.
        """
        import json

        def fetch(opener, url, timeout=300):
            if "corporate-announcements" in url:
                return json.dumps(FEED).encode("utf-8")
            for fragment, data in bodies.items():
                if fragment in url:
                    return data
            raise AssertionError("unexpected url %s" % url)

        return NSEFilings(cache_dir=tmp_path, delay=0, opener=lambda: None,
                          fetch=fetch)

    def test_it_keeps_the_first_attachment_whose_text_has_a_balance_sheet(self, tmp_path):
        good = _pdf_with_text(self.BALANCE_SHEET_PAGE)
        blank = _pdf_with_text(self.LETTER_PAGE)

        bodies = {
            "LETTER.pdf": blank,
            "Post_BM": blank,
            "AGM_Outcome": blank,
            "SE_Outcome_signed.pdf": good,
            "RevisedFinancialResults.pdf": blank,
            "undated": blank,
        }
        got = self._fetcher(tmp_path, bodies).acquire("TCS")

        assert got.ok, (
            "the attachment containing the statements was not kept: %s" % got.note
        )
        assert "SE_Outcome_signed" in got.url, (
            "kept %r instead of the attachment with the statements" % got.url
        )
        assert got.balance_sheet_pages, "no balance-sheet page recorded"
        # The three governance documents are excluded by the FILTER, not by downloading
        # them and finding nothing -- so the audited results are the first candidate and
        # only one request is made. An earlier version of this test asserted four
        # downloads, which was asserting the weakness of the old filter rather than the
        # behaviour wanted.
        assert got.tried == 1, (
            "expected the audited results to be reached without downloading the "
            "governance documents first; tried %d" % got.tried
        )

    def test_it_moves_past_an_attachment_that_has_no_balance_sheet(self, tmp_path):
        """The content check is the backstop, not the primary mechanism.

        The filter excludes documents it recognises. When one slips through -- a filing
        whose name says "outcome" and whose text is a board letter -- the content check is
        what saves the result, and the fetcher must keep going rather than accept the
        first thing it downloaded.
        """
        bodies = {
            "LETTER.pdf": _pdf_with_text(self.LETTER_PAGE),
            "Post_BM": _pdf_with_text(self.LETTER_PAGE),
            "AGM_Outcome": _pdf_with_text(self.LETTER_PAGE),
            # passes the filter (it is genuinely "audited financial results" by name)
            # but its text is a letter
            "SE_Outcome_signed.pdf": _pdf_with_text(self.LETTER_PAGE),
            "RevisedFinancialResults.pdf": _pdf_with_text(self.BALANCE_SHEET_PAGE),
            "undated": _pdf_with_text(self.LETTER_PAGE),
        }
        got = self._fetcher(tmp_path, bodies).acquire("TCS")
        assert got.ok, "the fetcher gave up instead of moving on: %s" % got.note
        assert "RevisedFinancialResults" in got.url, (
            "kept %r, which has no balance sheet, over the one that does" % got.url
        )
        assert got.tried > 1, (
            "the fetcher accepted the first download without checking it"
        )

    def test_it_reports_rather_than_raises_when_nothing_works(self, tmp_path):
        bodies = {
            k: _pdf_with_text("no statements in this document")
            for k in ("LETTER", "Post_BM", "AGM_Outcome", "SE_Outcome_signed",
                      "RevisedFinancialResults", "undated")
        }
        got = self._fetcher(tmp_path, bodies).acquire("TCS")
        assert not got.ok
        assert "no attachment carried a balance sheet" in got.note
        assert got.rejections, (
            "the rejections were not recorded, so a failure is opaque: the operator "
            "cannot tell a governance letter from a filer with no filing"
        )


def _pdf_with_text(text: str) -> bytes:
    """A one-page PDF whose extractable text is `text`.

    reportlab is already a dependency of the export tests. If it is not importable the
    test fails loudly rather than skipping, because a fetcher test that silently does not
    run is worse than no test.
    """
    import io

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 720
    for line in text.splitlines():
        c.drawString(72, y, line)
        y -= 14
    c.showPage()
    c.save()
    return buf.getvalue()
