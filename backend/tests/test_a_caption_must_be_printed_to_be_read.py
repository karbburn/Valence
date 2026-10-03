"""A tagged element is not necessarily a printed caption.

Amazon tags `PrepaidExpenseAndOtherAssetsCurrent` but does not PRINT it: its note places
the prepaid amount inside "Accounts receivable, net and other", and `trade_receivables`
already reads that element in full. So Amazon's itemised current assets exceeded its own
filed subtotal by exactly the receivables line -- 6,900 / 7,900 / 6,900 by year.

Four other filers use the SAME element, print it on the face, and reconcile. Ten of eleven
filers carrying the line were fine. So the answer is per-filer, and a shared taxonomy
cannot hold it: `get_canonical_mapping("Prepayments and other assets")` is one decision
for five companies whose filings disagree about it.

The reader therefore asks the filer, by reading the rendered face of its own balance sheet.
Verified live against EDGAR rather than assumed:

    AMZN  not printed        META / NVDA / DOX / AMBA  printed

Transport is stubbed throughout, so these tests never touch the network.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.ingestion import sec_face  # noqa: E402
from backend.data.ingestion.sec_edgar import (  # noqa: E402
    FACE_PRINTED_ELEMENTS,
    US_GAAP_TAG_MAP,
    _drop_captions_not_printed_on_the_face,
)

PREPAID_TAG = "PrepaidExpenseAndOtherAssetsCurrent"


def _tags_kept(tag_map, element: str = PREPAID_TAG) -> list:
    return [tags for _label, tags, _section in tag_map if element in tags]


def _face(ok: bool, text: str = "", reason: str = "") -> sec_face.FaceRead:
    return sec_face.FaceRead(ok=ok, text=text, reason=reason)


FACE_WITH_PREPAID = (
    "Consolidated Balance Sheets Cash and cash equivalents 86,810 Marketable securities "
    "36,219 Accounts receivable, net and other 38,325 Inventories 67,729 Prepaid expenses "
    "and other 1,234 Total current assets 229,083"
)
FACE_WITHOUT_PREPAID = (
    "Consolidated Balance Sheets Cash and cash equivalents 86,810 Marketable securities "
    "36,219 Accounts receivable, net and other 38,325 Inventories 67,729 Total current "
    "assets 229,083"
)


def _install(monkeypatch, face):
    """Point the reader's face lookup at `face`."""
    monkeypatch.setattr(
        "backend.data.ingestion.sec_face.SECFaces",
        lambda *a, **k: type("F", (), {"balance_sheet_face": staticmethod(lambda cik: face)})(),
    )


class TestTheDecisionIsPerFiler:
    def test_a_caption_the_filer_does_not_print_is_dropped(self, monkeypatch):
        _install(monkeypatch, _face(True, FACE_WITHOUT_PREPAID))
        kept = _tags_kept(_drop_captions_not_printed_on_the_face(US_GAAP_TAG_MAP, 1018724))
        assert not kept, (
            "Amazon's balance sheet does not print a prepaid caption, so the element "
            "must not be read -- keeping it is the over-count"
        )

    def test_a_caption_the_filer_does_print_is_kept(self, monkeypatch):
        _install(monkeypatch, _face(True, FACE_WITH_PREPAID))
        kept = _tags_kept(_drop_captions_not_printed_on_the_face(US_GAAP_TAG_MAP, 1326801))
        assert kept, (
            "the face prints a prepaid caption, so the element must still be read; "
            "dropping it would delete a correct figure for four working filers"
        )

    def test_the_two_filers_differ_only_in_their_own_faces(self, monkeypatch):
        """The same element, the same map, two answers -- from the filing alone."""
        amzn = sec_face.FaceRead(True, FACE_WITHOUT_PREPAID)
        meta = sec_face.FaceRead(True, FACE_WITH_PREPAID)
        _install(monkeypatch, amzn)
        assert not _tags_kept(
            _drop_captions_not_printed_on_the_face(US_GAAP_TAG_MAP, 1018724))
        _install(monkeypatch, meta)
        assert _tags_kept(
            _drop_captions_not_printed_on_the_face(US_GAAP_TAG_MAP, 1326801))


class TestItFailsSafe:
    """A fetch failure must not delete a correct figure.

    The failure modes are asymmetric. Dropping an element that was correct replaces a
    figure the reader could check with a silent omission they cannot. So every unreadable
    case keeps everything.
    """

    def test_an_unreadable_face_keeps_everything(self, monkeypatch):
        _install(monkeypatch, _face(False, reason="no 10-K in submissions"))
        assert _tags_kept(
            _drop_captions_not_printed_on_the_face(US_GAAP_TAG_MAP, 1018724)), (
            "an unreadable face removed a caption. A failed request must not change a "
            "published figure."
        )

    def test_an_exception_from_the_face_reader_keeps_everything(self, monkeypatch):
        class Boom:
            def balance_sheet_face(self, cik):
                raise RuntimeError("network down")

        monkeypatch.setattr("backend.data.ingestion.sec_face.SECFaces", Boom)
        assert _tags_kept(
            _drop_captions_not_printed_on_the_face(US_GAAP_TAG_MAP, 1018724))

    def test_the_whole_map_survives_an_unreadable_face(self, monkeypatch):
        _install(monkeypatch, _face(False, reason="FilingSummary 404"))
        assert len(_drop_captions_not_printed_on_the_face(US_GAAP_TAG_MAP, 1018724)) == len(
            US_GAAP_TAG_MAP)

    def test_an_empty_face_text_is_not_evidence_of_absence(self, monkeypatch):
        """A face that read as empty is a failed read, not a filer that prints nothing."""
        _install(monkeypatch, _face(True, FACE_WITHOUT_PREPAID.replace("Total", "")))
        kept = _tags_kept(_drop_captions_not_printed_on_the_face(US_GAAP_TAG_MAP, 1018724))
        assert kept, (
            "a face with no subtotal in it is a failed read, but it was treated as proof "
            "that the filer prints no prepaid caption"
        )


class TestTheTableIsNarrow:
    def test_only_the_element_whose_absence_is_the_defect_is_listed(self):
        """This is not "every tagged element must be printed".

        Most us-gaap elements a filer tags are note items that legitimately roll into a
        face line, and requiring all of them to appear on the face would delete a great
        many correct figures.
        """
        assert list(FACE_PRINTED_ELEMENTS) == [PREPAID_TAG], (
            "the face-checked table grew to %r. Each addition needs the same evidence: a "
            "filer that over-counts because the element is not printed."
            % sorted(FACE_PRINTED_ELEMENTS)
        )

    def test_the_table_maps_to_a_word_that_proves_presence(self):
        for element, word in FACE_PRINTED_ELEMENTS.items():
            assert word and word.islower(), (
                "%r maps to %r, which is not a lowercase word to search the face for"
                % (element, word)
            )

    def test_the_filter_is_only_reachable_from_the_us_gaap_branch(self):
        """An IFRS filer is not silently filtered by a us-gaap face rule."""
        src = (REPO / "backend" / "data" / "ingestion" / "sec_edgar.py").read_text(
            encoding="utf-8")
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert code.count("_drop_captions_not_printed_on_the_face(") == 2, (
            "expected the definition and exactly one call site (the us-gaap branch); "
            "found %d references"
            % code.count("_drop_captions_not_printed_on_the_face(")
        )


class TestTheGuardCannotBeSilentlyDisabled:
    """The failure that shipped this module dead for one iteration.

    `sec_edgar` passes `cik` as a ZERO-PADDED STRING -- `"0001018724"` -- while both URL
    formats here use `%d`. So `"%d" % "0001018724"` raises TypeError, the reader's
    fail-safe catches it and keeps every element, and the face check NEVER FIRES.

    Nothing failed. The tests passed, the models built, and the guard was inert in the
    product while being live in the suite -- caught only by running the real reader and
    reading its log line, which said "not read (submissions: TypeError)".

    So the coercion is asserted on the string the reader really passes, and the fail-safe
    is asserted not to be the thing hiding it.
    """

    def test_a_zero_padded_string_cik_is_accepted(self):
        assert sec_face.SECFaces._cik("0001018724") == 1018724
        assert sec_face.SECFaces._cik(1018724) == 1018724
        assert sec_face.SECFaces._cik(" 1018724 ") == 1018724

    def test_the_reader_passes_a_string_and_the_check_still_fires(self, monkeypatch):
        """End to end through the real reader, with only the transport stubbed.

        A test that calls `balance_sheet_face(1018724)` with an int cannot see this: the
        product passes a string.
        """
        seen = {}

        def get(url, timeout=120):
            seen.setdefault("urls", []).append(url)
            if "submissions" in url:
                return (b'{"filings":{"recent":{"form":["10-K"],'
                        b'"filingDate":["2026-02-06"],'
                        b'"accessionNumber":["0001018724-26-000004"]}}}')
            if "FilingSummary" in url:
                return (b"<Document><Reports><Report><HtmlFileName>R7.htm</HtmlFileName>"
                        b"<ShortName>Consolidated Balance Sheets</ShortName></Report>"
                        b"</Reports></Document>")
            return ("<html>Total current assets 229,083 Accounts receivable, net and "
                    "other 38,325</html>").encode()

        monkeypatch.setattr(sec_face.SECFaces, "_http_get", staticmethod(get))
        read = sec_face.SECFaces().balance_sheet_face("0001018724")
        assert read.ok, (
            "the string CIK the reader passes was rejected: %s. The guard is inert "
            "again." % read.reason
        )
        assert read.prints("prepaid") is False, (
            "the face was read but the answer is not being used"
        )
        assert any("CIK0001018724" in u or "CIK0001018724" in u for u in seen["urls"]) or \
            any("1018724" in u for u in seen["urls"])

    def test_the_archive_url_is_built_from_the_coerced_cik(self, monkeypatch):
        """`ARCHIVE % (cik, accession)` was the second `%d` to raise."""
        urls = []

        def get(url, timeout=120):
            urls.append(url)
            if "submissions" in url:
                return (b'{"filings":{"recent":{"form":["10-K"],'
                        b'"filingDate":["2026-02-06"],'
                        b'"accessionNumber":["0001018724-26-000004"]}}}')
            if "FilingSummary" in url:
                return (b"<Document><Reports><Report><HtmlFileName>R7.htm</HtmlFileName>"
                        b"<ShortName>Consolidated Balance Sheets</ShortName></Report>"
                        b"</Reports></Document>")
            return b"<html>Total assets 1</html>"

        read = sec_face.SECFaces(get=get).balance_sheet_face("0001018724")
        assert read.ok
        archive = [u for u in urls if "/Archives/" in u]
        assert archive, "no archive URL was built"
        assert "1018724" in archive[0]


class TestFaceReading:
    def test_prints_returns_none_when_the_face_was_not_read(self):
        """None, not False -- the distinction is the whole fail-safe."""
        assert _face(False, reason="no 10-K").prints("prepaid") is None

    def test_prints_is_case_insensitive(self):
        assert _face(True, FACE_WITH_PREPAID).prints("PREPAID") is True
        assert _face(True, FACE_WITH_PREPAID).prints("Prepaid") is True

    def test_a_report_without_a_balance_sheet_reads_as_unavailable(self, monkeypatch):
        summary = b"<Document><Reports></Reports></Document>"

        def get(url, timeout=120):
            if "submissions" in url:
                return (b'{"filings":{"recent":{"form":["10-K"],'
                        b'"filingDate":["2026-02-06"],'
                        b'"accessionNumber":["0001018724-26-000004"]}}}')
            if "FilingSummary" in url:
                return summary
            raise AssertionError(url)

        read = sec_face.SECFaces(get=get).balance_sheet_face(1018724)
        assert not read.ok
        assert "no balance-sheet report" in read.reason
        assert read.prints("prepaid") is None

    def test_a_parenthetical_report_is_not_mistaken_for_the_face(self, monkeypatch):
        """It restates the face, so it answers identically -- but it is a second request."""
        summary = (
            b"<Document><Reports>"
            b"<Report><HtmlFileName>R4.htm</HtmlFileName>"
            b"<ShortName>Consolidated Balance Sheets (Parenthetical)</ShortName></Report>"
            b"<Report><HtmlFileName>R7.htm</HtmlFileName>"
            b"<ShortName>Consolidated Balance Sheets</ShortName></Report>"
            b"</Reports></Document>"
        )
        seen = []

        def get(url, timeout=120):
            seen.append(url)
            if "submissions" in url:
                return (b'{"filings":{"recent":{"form":["10-K"],'
                        b'"filingDate":["2026-02-06"],'
                        b'"accessionNumber":["0001018724-26-000004"]}}}')
            if "FilingSummary" in url:
                return summary
            return b"<html>Total current assets 229,083 Prepaid 1,234</html>"

        read = sec_face.SECFaces(get=get).balance_sheet_face(1018724)
        assert read.ok and read.report == "R7.htm", (
            "picked %r; the parenthetical was excluded" % read.report
        )

    def test_the_newest_10k_is_the_one_read(self, monkeypatch):
        summary = (b"<Document><Reports><Report><HtmlFileName>R7.htm</HtmlFileName>"
                   b"<ShortName>Consolidated Balance Sheets</ShortName></Report>"
                   b"</Reports></Document>")
        seen = []

        def get(url, timeout=120):
            seen.append(url)
            if "submissions" in url:
                return (b'{"filings":{"recent":{"form":["8-K","10-K","10-K"],'
                        b'"filingDate":["2026-06-01","2025-02-07","2026-02-06"],'
                        b'"accessionNumber":["a","b","c"]}}}')
            if "FilingSummary" in url:
                return summary
            return b"<html>Total assets 1</html>"

        read = sec_face.SECFaces(get=get).balance_sheet_face(1018724)
        assert read.ok
        assert read.accession == "c", (
            "read accession %r; 'c' is filed 2026-02-06 and is the newest 10-K"
            % read.accession
        )
