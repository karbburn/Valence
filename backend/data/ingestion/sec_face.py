"""Whether a filer PRINTS a caption on the face of its own balance sheet.

The Amazon defect: `PrepaidExpenseAndOtherAssetsCurrent` was mapped onto a current-asset
line, and Amazon's four printed current-asset lines then exceeded the filer's own subtotal
by exactly the value of "Accounts receivable, net and other" -- the line that already
contains the prepaid amount. Amazon's note puts prepaid INSIDE receivables; four other
filers use the SAME element and print it on the face, and reconcile.

So the question "is this caption printed above the subtotal?" is per-filer, and no entry in
a shared taxonomy can answer it. It can only be read off the filer's own statement.

SEC publishes the rendered face of every statement as an R-file, named in
FilingSummary.xml. Measured on the five filers that carry the line:

    AMZN   "Prepaid" on the face: NO
    META   yes      NVDA  yes      DOX  yes      AMBA  yes

which is precisely the split between the one filer that over-counts and the four that do
not. So this module reads that face and lets the reader decide, per filer, rather than
guessing from an element name.

FAIL-SAFE BY CONSTRUCTION: when the face cannot be read, the caption is KEPT. Dropping a
correct figure because a fetch failed would replace a known-good number with a silent
omission, which is the worse error in both directions.
"""

from __future__ import annotations

import gzip
import json
import re
import ssl
import urllib.request
from dataclasses import dataclass

SEC_UA = "Valence research (karbburn@gmail.com)"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK%010d.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/%d/%s"

# A rendered report is identified by its ShortName. The balance sheet is the one whose
# name says so and is not a parenthetical -- the parenthetical restates the face and would
# answer the same question identically, so including it would only add a request.
_BALANCE_SHEET = re.compile(r"balance sheet", re.I)
_NOT_PARENTHETICAL = re.compile(r"parenthetical", re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_ENTITY = re.compile(r"&#\d+;|&[a-z]+;", re.I)

# A read is only trusted if it looks like a balance sheet at all.
#
# Without this, a report that came back wrong, truncated or empty reads as SUCCESS and
# then as PROOF OF ABSENCE -- so a caption is dropped on the strength of a page that never
# contained the statement. That is the worst direction for this module to fail in: the
# figure removed was correct, and its absence leaves nothing to notice.
#
# Checked in `FaceRead.prints` rather than in the reader, so it holds however a FaceRead
# was built. Caught by a test in this suite that removed "Total" from its fixture and
# watched a healthy filer's caption disappear.
_FACE_ANCHOR = re.compile(r"total\s+(current\s+)?assets", re.I)

# Where the XBRL element definitions begin inside a rendered report. Everything from the
# first of these to the end of the document is metadata about tags, not the statement, and
# is excluded from caption matching by `FaceRead.face_body`.
_DEFINITION_START = ("X - Definition", "X - Definitions", "X - References", "X - Label",
                     "X - ReferencesLink", "+ Details")


@dataclass
class FaceRead:
    """What could be read of a filer's rendered balance sheet."""

    ok: bool
    text: str = ""
    report: str = ""
    accession: str = ""
    reason: str = ""

    @property
    def face_body(self) -> str:
        """The statement itself, excluding the XBRL element definitions.

        Every SEC rendered report carries a definition appendix -- "X - Definition
        Aggregate carrying amount, as of the balance sheet date, of..." -- and it is the
        bulk of the document. Measured across six filers: the statement body is 1,530 to
        1,987 characters while the definitions run 53,898 to 72,345. So a caption absent
        from the face can still be present in the file, roughly 97% of which is not the
        face.

        That is not hypothetical. `Noncontrolling interests` appears ONLY in the
        definitions for aapl_us, amzn_us, googl_us, msft_us, meta_us and nvda_us -- not one
        of them prints that line on its balance sheet, yet a substring test over the whole
        document returns True for all six. A guard that answers "yes, this filer prints it"
        when the filer prints nothing is worse than no guard, because the answer looks
        checked.
        """
        text = self.text or ""
        cut = len(text)
        for marker in _DEFINITION_START:
            at = text.find(marker)
            if at != -1:
                cut = min(cut, at)
        return text[:cut]

    def prints(self, caption: str) -> "bool | None":
        """True/False if the face was read, None if it was not.

        None rather than False on failure, so a caller cannot mistake "could not read" for
        "the filer does not print it" -- which is the mistake that would drop a correct
        figure.

        Matched against the statement BODY only, never the XBRL definition appendix. See
        `face_body` for the measurement: without the restriction this returns True for
        "Noncontrolling interests" on all six filers measured, none of which print it.

        The anchor check lives HERE rather than in the reader, so it holds for any
        FaceRead however it was built. A test that constructs one directly would
        otherwise bypass it, which is exactly what happened: the check was first placed
        where `balance_sheet_face` applies it, and a test supplying its own FaceRead
        skipped it and deleted a healthy filer's caption.
        """
        if not self.ok or not self.text:
            return None
        if not _FACE_ANCHOR.search(self.text):
            return None
        return caption.lower() in self.face_body.lower()


def strip_html(html: str) -> str:
    text = _TAG.sub(" ", html)
    text = text.replace("&nbsp;", " ").replace("&#160;", " ")
    text = _ENTITY.sub(" ", text)
    return _WS.sub(" ", text).strip()


class SECFaces:
    """Reads a filer's rendered balance sheet from EDGAR.

    `get` is injectable so every test runs without a network, and so a caller can supply a
    cached transport rather than re-fetching on every build.
    """

    def __init__(self, get=None, timeout: int = 120):
        self.timeout = timeout
        self._get = get or self._http_get

    @staticmethod
    def _http_get(url: str, timeout: int = 120) -> bytes:
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        req = urllib.request.Request(url, headers={
            "User-Agent": SEC_UA, "Accept-Encoding": "gzip", "Accept": "*/*"})
        with opener.open(req, timeout=timeout) as r:
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return body

    @staticmethod
    def _cik(cik) -> int:
        """The CIK as an integer.

        The reader passes a ZERO-PADDED STRING here -- `cik` in `sec_edgar` is
        `"0001018724"`, not `1018724` -- and `"%010d" % "0001018724"` raises TypeError.
        That failure was swallowed by the fail-safe, so the face check silently never
        fired in production while its tests passed: the guard was live in the suite and
        dead in the product.
        """
        return int(str(cik).strip().lstrip("CIK").strip().zfill(10))

    def latest_10k(self, cik) -> "tuple[str, str] | None":
        """(accession-without-dashes, filing date) for the newest 10-K."""
        data = json.loads(self._get(SUBMISSIONS % self._cik(cik), self.timeout).decode("utf-8"))
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form") or []
        dates = recent.get("filingDate") or []
        accessions = recent.get("accessionNumber") or []
        best = None
        for i, f in enumerate(forms):
            if f == "10-K" and i < len(accessions) and i < len(dates):
                if best is None or dates[i] > best[1]:
                    best = (accessions[i].replace("-", ""), dates[i])
        return best

    def balance_sheet_face(self, cik) -> FaceRead:
        """The rendered face of the newest 10-K balance sheet."""
        # Coerced once, up front. BOTH URL formats use `%d`, and the reader passes a
        # zero-padded string; fixing only `latest_10k` left `ARCHIVE % (cik, ...)`
        # raising the same TypeError, so the check still never fired.
        cik = self._cik(cik)
        try:
            filing = self.latest_10k(cik)
        except Exception as exc:  # noqa: BLE001
            return FaceRead(False, reason="submissions: %s" % type(exc).__name__)
        if not filing:
            return FaceRead(False, reason="no 10-K in submissions")

        accession, _date = filing
        base = ARCHIVE % (cik, accession)
        try:
            summary = self._get(base + "/FilingSummary.xml", self.timeout).decode(
                "utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            return FaceRead(False, accession=accession,
                            reason="FilingSummary: %s" % type(exc).__name__)

        report = ""
        for block in re.findall(r"<Report[^>]*>(.*?)</Report>", summary, re.S):
            fname = re.search(r"<HtmlFileName>([^<]+)</HtmlFileName>", block)
            short = re.search(r"<ShortName>([^<]+)</ShortName>", block)
            if not fname or not short:
                continue
            name = short.group(1)
            if _BALANCE_SHEET.search(name) and not _NOT_PARENTHETICAL.search(name):
                report = fname.group(1)
                break
        if not report:
            return FaceRead(False, accession=accession,
                            reason="no balance-sheet report in FilingSummary")

        try:
            html = self._get("%s/%s" % (base, report), self.timeout).decode(
                "utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            return FaceRead(False, accession=accession, report=report,
                            reason="report: %s" % type(exc).__name__)

        return FaceRead(True, text=strip_html(html), report=report,
                        accession=accession)
