"""The fetcher must choose the newest filing that actually contains the statements.

Three defects were found by measurement while building this, and each shipped a wrong
answer before it was found:

**`dt` sorts wrong as text.** It is `ddmmyyyyHHMMss` -- DAY first -- verified against
`an_dt` (`"30-Aug-2018 08:40:00"`) on all 3368 rows of a live TCS feed: every row where
both parse agrees, zero disagreements. Lexical order inverts across centuries, because
`"16..." < "20..."` while 16 Apr 2020 is later than 12 Jan 2025. The first version of the
fetcher sorted the string and reached a 2019 TCS filing before a 2025 one, and a 2014
statement for HCLTech. A stale figure from a real filing is the most convincing kind of
wrong.

**A filename is not a document class.** TCS's audited statements are in
`..._SE_Outcome_signed.pdf`, while the three newest candidates are a signed letter, a
post-board-meeting letter and an AGM outcome intimation -- two of which contain
"outcome".

**One phrase does not identify a balance sheet.** An auditor's report or a board letter
refers to "total current assets" in passing, and a single-phrase substring test accepted
one as the statements. Both subtotals are required, plus an asset caption.

Fixtures are the real committed filings rather than synthesised ones. An earlier version
built them with reportlab and asserted in its own docstring that "reportlab is already a
dependency of the export tests". That was not checked: reportlab is installed locally and
absent from CI, so three tests passed here and failed on the runner. The assertion that
had produced the confidence was the false one.

Transport is injected, so nothing here touches the network.
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.ingestion.nse_filings import (  # noqa: E402
    NSEFilings,
    announcement_date,
    balance_sheet_pages,
    candidate_attachments,
    looks_like_balance_sheet,
    parse_an_dt,
    parse_dt,
)

TCS_PDF = REPO / "backend" / "data" / "filings" / "nse" / "tcs-outcome-2026-04.pdf"

# One attachment from each document class observed in a live TCS feed.
FEED = [
    {"attchmntFile": "https://x/CORPCS_LETTER.pdf",
     "attchmntText": "Board has informed the Exchange", "an_dt": "01-Oct-2026 18:39:47",
     "dt": "01102026183947", "desc": "intimation as per regulation 43"},
    {"attchmntFile": "https://x/CORPCS_Post_BM_SE_Letter.pdf",
     "attchmntText": "Outcome of the Board Meeting", "an_dt": "09-Jul-2026 15:51:58",
     "dt": "09072026155158", "desc": "outcome of board meeting"},
    {"attchmntFile": "https://x/CORPCS_AGM_Outcome_Intimation.pdf",
     "attchmntText": "Outcome of AGM", "an_dt": "09-Jun-2026 18:12:39",
     "dt": "09062026181239", "desc": "intimation as per circular"},
    # THE ONE: audited results, 9 Apr 2026
    {"attchmntFile": "https://x/CORPCS_09042026155946_SE_Outcome_signed.pdf",
     "attchmntText": "Audited financial results for the period ended March 31, 2026",
     "an_dt": "09-Apr-2026 15:59:46", "dt": "09042026155946",
     "desc": "financial results"},
    # older, 2019 -- the one a text sort would have reached first
    {"attchmntFile": "https://x/RAJENDRA_RevisedFinancialResults.pdf",
     "attchmntText": "Revised financial results", "an_dt": "14-Jan-2019 20:00:00",
     "dt": "14012019200000", "desc": "financial results"},
    {"attchmntFile": "https://x/SECRETARIAL_minutes.pdf",
     "attchmntText": "Minutes of the meeting", "an_dt": "02-Aug-2026 08:40:00",
     "dt": "02082026084000", "desc": "minutes of the intimation"},
    {"attchmntFile": "https://x/data.xlsx", "attchmntText": "XBRL",
     "an_dt": "01-Oct-2026 18:39:47", "dt": "01102026183947", "desc": "xbrl"},
    {"attchmntFile": "https://x/CORPCS_Outcome_undated.pdf",
     "attchmntText": "audited financial results", "an_dt": None, "dt": None,
     "desc": "financial results"},
]


def _statements_pdf() -> bytes:
    """A REAL filed statements document, committed in this repository."""
    assert TCS_PDF.exists(), (
        "the fixture filing is missing at %s. These tests need a real statements "
        "document and it is committed here." % TCS_PDF
    )
    return TCS_PDF.read_bytes()


def _unusable_pdf() -> bytes:
    """PDF magic followed by garbage: the "downloaded but useless" case.

    Real and common -- an attachment that is a PDF in name only. Exercises the same
    continue-past path as a readable document lacking the statements.
    """
    return b"%PDF-1.4\nthis is not a document\n%%EOF\n"


def _fetcher(tmp_path, bodies):
    """A fetcher whose downloads come from `bodies`, keyed by URL fragment.

    The same stub serves the announcements feed, because `acquire` fetches it through the
    same injected callable. A transport stub that only handled PDFs made the fetcher fail
    at its first step, and the test then reported "announcements unavailable" -- which
    says nothing about the behaviour under test.
    """
    def fetch(opener, url, timeout=300):
        if "corporate-announcements" in url:
            return json.dumps(FEED).encode("utf-8")
        for fragment, data in bodies.items():
            if fragment in url:
                return data
        raise AssertionError("unexpected url %s" % url)

    return NSEFilings(cache_dir=tmp_path, delay=0, opener=lambda: None, fetch=fetch)


class TestTheDateIsParsedNotSorted:
    def test_dt_is_day_first(self):
        # 30 Aug 2018, per the paired `an_dt` on a live row.
        assert parse_dt("30082018084000") == datetime(2018, 8, 30, 8, 40, 0)

    def test_the_two_fields_agree_on_a_known_pair(self):
        assert parse_an_dt("30-Aug-2018 08:40:00") == parse_dt("30082018084000")

    def test_text_sorting_would_invert_the_order(self):
        """The defect, as an assertion rather than a comment.

        A test that only checks the parser accepts `30082018084000` passes against code
        that sorts the string. The parser being right is not the property that matters --
        the ORDER is.
        """
        jan_2025 = parse_dt("20112025165953")
        apr_2020 = parse_dt("16042020191500")
        assert jan_2025 > apr_2020, "parsed order disagrees with the real chronology"
        assert "20112025165953" > "16042020191500", (
            "this premise no longer holds -- if the strings now sort correctly the "
            "parsing is defensive rather than necessary, and the comment in "
            "nse_filings.py should be revisited"
        )

    def test_announcement_date_prefers_the_human_field(self):
        row = {"an_dt": "30-Aug-2018 08:40:00", "dt": "01012000999999"}
        assert announcement_date(row) == datetime(2018, 8, 30, 8, 40, 0)

    def test_an_unparseable_date_is_none_not_a_guess(self):
        for bad in ("", None, "not-a-date", "99999999999999", "00000000000000"):
            assert parse_dt(bad) is None
        assert parse_an_dt("32-Xxx-2020 00:00:00") is None


class TestCandidatesAreOrderedNewestFirst:
    def test_the_2026_results_come_before_the_2019_one(self):
        files = [c.filename for c in candidate_attachments(FEED)]
        results = "CORPCS_09042026155946_SE_Outcome_signed.pdf"
        old = "RAJENDRA_RevisedFinancialResults.pdf"
        assert results in files and old in files, (
            "a candidate was filtered out that should not have been: %r" % files
        )
        assert files.index(results) < files.index(old), (
            "the 2019 filing was preferred to the 2026 one: %r" % files
        )

    def test_an_undated_attachment_sorts_last(self):
        """An unknown age cannot be called recent."""
        cands = candidate_attachments(FEED)
        assert any(c.announced is None for c in cands), (
            "the undated fixture row was filtered out entirely"
        )
        assert cands[-1].announced is None, (
            "the undated attachment sorted among the dated ones: %r"
            % [c.filename for c in cands]
        )

    def test_governance_documents_are_never_candidates(self):
        names = " ".join(c.filename for c in candidate_attachments(FEED))
        for excluded in ("SECRETARIAL_minutes", "data.xlsx"):
            assert excluded not in names

    def test_a_revision_filing_is_still_a_statements_filing(self):
        """"Revised financial results" is a correction, not a different document.

        Treating it as governance leaves a filer whose only results attachment happens to
        be a revision with no source at all -- a bug in the first version of the filter.
        """
        files = [c.filename for c in candidate_attachments(FEED)]
        assert "RAJENDRA_RevisedFinancialResults.pdf" in files, (
            "a revision filing was excluded as governance, so a filer whose newest "
            "results happen to be a correction would have no source at all: %r" % files
        )

    def test_an_intimation_circulating_letter_is_not_chosen_by_name_alone(self):
        """The trap: three of the newest names contain "outcome"."""
        files = [c.filename for c in candidate_attachments(FEED)]
        for excluded in ("CORPCS_AGM_Outcome_Intimation.pdf",
                         "CORPCS_Post_BM_SE_Letter.pdf"):
            assert excluded not in files, (
                "%r was offered as a statements candidate" % excluded
            )


class TestCandidatesThatNameThemselvesRankFirst:
    """Tata Steel's feed defeated a pure date ordering.

    Of 3025 announcements, 91 passed the statements filter and the twelve NEWEST were
    disposal notices -- `NIDHIFADNAVIS_..._BSENSE.pdf`, two pages each -- whose
    DESCRIPTIONS disclose the financial results of the divested unit. The audited results
    sat at `..._Board_Outcome_-_March_17_2026.pdf`, ranked below a year of notices.

    A filename that names itself as results now outranks one that only its description
    suggests. Ordering by size instead was measured and failed identically: the largest
    candidates were the notices too.
    """

    # Two documents from that feed: the results, and a notice that is newer.
    TATA = [
        # A disposal notice: newer, and its DESCRIPTION discloses financial results.
        # The filename is deliberately generic, because the real one is
        # `NIDHIFADNAVIS_..._BSENSE.pdf` and this fixture is about ORDERING, not about
        # which document classes the governance filter removes -- a separate test covers
        # that, and mixing the two made this one fail for an unrelated reason.
        {"attchmntFile": "https://x/DISPOSAL_29092026164617_Annexure.pdf",
         "attchmntText": "Tata Steel Limited has informed the Exchange of the outcome "
                         "and financial results of the divested unit",
         "an_dt": "29-Sep-2026 16:46:17", "dt": "29092026164617",
         "desc": "outcome and financial results of the divested unit"},
        {"attchmntFile": "https://x/AUDITED_17032026184358_Board_Outcome_-_"
                         "March_17_2026.pdf",
         "attchmntText": "Tata Steel Limited has informed the Exchange",
         "an_dt": "17-Mar-2026 18:43:58", "dt": "17032026184358",
         "desc": "Board Outcome"},
    ]

    def test_the_named_document_comes_first_despite_being_older(self):
        cands = candidate_attachments(self.TATA)
        assert cands[0].filename.startswith("AUDITED_17032026"), (
            "the disposal notice outranked the audited results: %r"
            % [c.filename for c in cands]
        )

    def test_the_score_records_where_the_signal_came_from(self):
        cands = candidate_attachments(self.TATA)
        # Keyed on the whole filename: both attachments share a long prefix
        # ("NIDHIFADNAVIS_"), so a truncated key silently collapsed them into one entry
        # and this test asserted against a set of one.
        scores = {c.filename: c.named for c in cands}
        assert len(scores) == 2, "the two fixtures collapsed into one key: %r" % scores
        assert sorted(scores.values()) == [1, 2], (
            "expected one candidate scoring 2 (named in the filename) and one scoring 1 "
            "(description only): %r" % scores
        )

    def test_nothing_is_discarded_by_the_ranking(self):
        """Ordering, not filtering -- a bigger budget must remain a fallback."""
        assert len(candidate_attachments(self.TATA)) == 2


class TestTheBalanceSheetDetector:
    """Tested on text directly, because that is the level the rule lives at."""

    def test_a_real_balance_sheet_is_recognised(self):
        assert looks_like_balance_sheet(
            "Consolidated Balance Sheet\n"
            "Current assets\n"
            "Cash and cash equivalents 872 964\n"
            "Total current assets 1,234 1,100\n"
            "Total assets 4,500 4,200\n"
        )

    def test_prose_mentioning_one_subtotal_is_not_a_balance_sheet(self):
        """An auditor's report refers to these in passing."""
        assert not looks_like_balance_sheet(
            "Independent Auditor's Report\n"
            "We have audited the total current assets and the cash and cash equivalents "
            "as presented in the financial statements.\n"
        ), (
            "a paragraph mentioning the subtotal and a caption was accepted as the "
            "balance sheet -- the single-phrase rule this replaced"
        )

    def test_prose_mentioning_both_subtotals_is_still_not_one(self):
        assert not looks_like_balance_sheet(
            "The total current assets and the total assets have been restated.\n"
        ), (
            "both subtotals in prose with no asset caption was accepted; every real "
            "balance sheet prints at least one caption beside them"
        )

    def test_a_subtotal_without_a_caption_is_not_enough(self):
        assert not looks_like_balance_sheet(
            "Statement of changes in equity\n"
            "Total current assets n/a\nTotal assets n/a\n"
        )

    def test_empty_text_is_not_a_balance_sheet(self):
        for empty in ("", None, "   \n  "):
            assert not looks_like_balance_sheet(empty)

    def test_a_statement_set_one_glyph_at_a_time_is_still_recognised(self):
        """Some filers position every glyph separately.

        Tata Steel's audited results extract as `T O T A L - A S SE T S` and
        `Sub-total - C urrent assets`, so no caption appears as a contiguous string even
        with whitespace collapsed, and a 30-page audited filing was reported as
        "no balance sheet in 30 pages". Letters alone are matched.
        """
        assert looks_like_balance_sheet(
            "6 1 % | T A T A\n"
            "T o t a l   c u r r e n t   a s s e t s   1 , 2 3 4\n"
            "c a s h   a n d   c a s h   e q u i v a l e n t s   8 7 2\n"
            "T o t a l   a s s e t s   4 , 5 0 0"
        )

    def test_a_figure_split_across_a_caption_does_not_hide_it(self):
        """The real Tata Steel layout, verbatim in shape.

        These are printed-page lines from `TATASTEEL_29052024190643_OUTCOME.pdf`, printed
        pages 17 and 21. Two separate normalisations are needed and neither alone is
        enough: the caption is hyphenated AND letter-spaced, and in the subtotal the
        figure sits between the two halves of the words.
        """
        face = (
            "61 TATA\n"
            "Sub-total - C urrent assets        36,765.14   40,515.56\n"
            "Inventories\n"
            "T O T A L - A S SE T S            2,45,634.06 2,42,695.73\n"
        )
        assert looks_like_balance_sheet(face), (
            "a real balance-sheet face was rejected. This is printed page 21 of a "
            "committed-shape document; rejecting it reports a filer as unreadable when "
            "its statements are plainly present."
        )

    def test_a_ratio_disclosure_is_not_a_balance_sheet(self):
        """What the looser matching must NOT let in.

        Tata Steel's Regulation 52(4) disclosures print "Total current assets" and
        "Total assets" as INPUTS to a current ratio, and they sit two pages away from the
        real face. Under the same letters-only match they carry both subtotals, so the
        caption requirement is the only thing separating them -- which is why it is
        asserted here rather than assumed.
        """
        ratio = (
            "Additional information pursuant to Regulation 52(4)\n"
            "Current ratio\n"
            "(Total current assets Current habhtes)\n"
            "0 80 0 78 0 90 0 80 0 90\n"
            "Long term debt to working capital ratio\n"
            "((Non-current borrowings Total current assets - Current hahes))\n"
        )
        assert not looks_like_balance_sheet(ratio), (
            "a Regulation 52(4) ratio table was accepted as a balance sheet. Both "
            "subtotals appear in it, so the caption requirement is the only guard."
        )

    def test_punctuation_dropping_does_not_weaken_the_prose_guard(self):
        """The blunt instrument, pinned.

        Dropping every non-letter could turn a paragraph naming both subtotals into a
        match, so the prose case is re-asserted in the letter-spaced form where that
        normalisation is the only route to a match.
        """
        assert not looks_like_balance_sheet(
            "T h e   t o t a l   c u r r e n t   a s s e t s   a n d   "
            "t h e   t o t a l   a s s e t s   w e r e   r e s t a t e d"
        ), (
            "punctuation-dropping made prose pass. Both subtotals in a paragraph and no "
            "caption is still not a balance sheet."
        )

    def test_it_finds_the_committed_filing_s_own_pages(self):
        """The rule against the document it will actually meet."""
        import pdfplumber

        assert TCS_PDF.exists()
        with pdfplumber.open(str(TCS_PDF)) as doc:
            pages = balance_sheet_pages(doc)
        assert pages == [11, 20], (
            "the committed TCS filing's balance sheet was not found at pages 11 and 20; "
            "got %r. If the fixture changed, update this." % pages
        )


class TestTheDownloadLoop:
    def test_it_keeps_the_first_attachment_whose_text_has_a_balance_sheet(self, tmp_path):
        good = _statements_pdf()
        bodies = {k: good for k in
                  ("LETTER.pdf", "Post_BM", "AGM_Outcome", "SE_Outcome_signed",
                   "RevisedFinancialResults", "undated")}
        got = _fetcher(tmp_path, bodies).acquire("TCS")

        assert got.ok, (
            "the attachment containing the statements was not kept: %s" % got.note
        )
        assert "SE_Outcome_signed" in got.url, (
            "kept %r instead of the attachment with the statements" % got.url
        )
        # Read off the real committed filing, so this asserts the detector works on the
        # document shape it will actually meet rather than on a drawn one.
        assert got.balance_sheet_pages == [11, 20], (
            "the balance sheet of the committed filing was not found at the pages its "
            "own metadata records: got %r" % got.balance_sheet_pages
        )
        # The governance documents are excluded by the FILTER, not by downloading them and
        # finding nothing, so the audited results are the first candidate. An earlier
        # version asserted four downloads, which was asserting the old filter's weakness
        # rather than the behaviour wanted.
        assert got.tried == 1, (
            "expected the results to be reached without downloading the governance "
            "documents first; tried %d" % got.tried
        )

    def test_it_moves_past_an_attachment_it_cannot_use(self, tmp_path):
        """The content check is the backstop, not the primary mechanism.

        The filter excludes documents it recognises. When one slips through, the fetcher
        must keep going rather than accept the first thing it downloaded.
        """
        good = _statements_pdf()
        bodies = {
            "LETTER.pdf": good,
            "Post_BM": good,
            "AGM_Outcome": good,
            # passes the filter, but is not a usable document
            "SE_Outcome_signed.pdf": _unusable_pdf(),
            "RevisedFinancialResults.pdf": good,
            "undated": good,
        }
        got = _fetcher(tmp_path, bodies).acquire("TCS")
        assert got.ok, "the fetcher gave up instead of moving on: %s" % got.note
        assert "RevisedFinancialResults" in got.url, (
            "kept %r, which could not be read, over one that could" % got.url
        )
        assert got.tried > 1, "the fetcher accepted the first download unchecked"
        assert any("unreadable" in r.reason for r in got.rejections), (
            "the reason the unusable attachment was skipped was not recorded: %r"
            % [r.reason for r in got.rejections]
        )

    def test_it_reports_rather_than_raises_when_nothing_works(self, tmp_path):
        bodies = {k: _unusable_pdf() for k in
                  ("LETTER", "Post_BM", "AGM_Outcome", "SE_Outcome_signed",
                   "RevisedFinancialResults", "undated")}
        got = _fetcher(tmp_path, bodies).acquire("TCS")
        assert not got.ok
        assert "no attachment carried a balance sheet" in got.note
        assert got.rejections, (
            "the rejections were not recorded, so a failure is opaque: the operator "
            "cannot tell a governance letter from a filer with no filing"
        )
