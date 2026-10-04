"""Fetch audited Indian financial statements from NSE.

Ten of the twelve shipped India models read a market feed, because no filing was
available to read. That was a documents problem, and it turned out to be a FETCHING
problem: NSE serves the audited results as PDF attachments, and the only thing standing
between this module and eleven more filing-derived models was a session cookie.

Three findings shaped this module, each measured rather than assumed:

**`dt` is `ddmmyyyyHHMMss`, day first.** Verified against `an_dt` (`"30-Aug-2018
08:40:00"`) on all 3368 rows of a TCS feed: every row where both parse agrees, zero
disagreements. Sorting `dt` as TEXT is not merely inexact -- it is inverted across
centuries, because `"16..." < "20..."` lexically while 16 Apr 2020 is later than
12 Jan 2025. An earlier version of this fetcher sorted the string and reached a 2019
filing before a 2025 one, and a 2014 statement for HCLTech. A stale figure from a real
filing is the most convincing kind of wrong, so the date is parsed and never sorted as
text.

**A filename is not a document class.** TCS's audited statements are in
`TCS_CORPCS_09042026155946_SE_Outcome_signed.pdf`, while the three newest candidates are a
signed letter, a post-board-meeting letter and an AGM outcome intimation. Selection is
therefore by CONTENT -- an attachment is kept only if a page carries the balance sheet's
own subtotal -- and the filename regex is only used to avoid downloading a thousand
irrelevant PDFs.

**Some attachments have unrecoverable text.** A font with no `/ToUnicode` CMap and no
embedded font file makes pdfplumber emit `(cid:100)(cid:4)...`, and pdfminer's own
extraction does the same, so the characters are not in the file. TCS's Q4 outcome is such
a document while another TCS attachment parses perfectly -- so this is per-attachment,
not per-filer, and the fetcher tries several and keeps the readable one.

Polite by construction: one request at a time with a delay, a bounded number of
candidates per company, and a browser User-Agent because NSE 403s anything else.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import ssl
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Where acquired documents and their metadata live.
#
# A named constant rather than a default argument, because the INGESTION side needs to find
# what this module downloaded. `<symbol>.json` beside `<symbol>-<label>.pdf` is the only
# thing connecting an acquired statement to the company it belongs to, and until the
# ingestion side read it the fetcher's whole output went nowhere: the balance-sheet pages
# were located by content, recorded, and never parsed. Twelve India models were
# `opinion_only` because their audited statements were on disk and unread.
NSE_CACHE_DIR = Path(__file__).resolve().parents[1] / "filings" / "nse"
NSE_HOME = "https://www.nseindia.com/"
ANNOUNCEMENTS = ("https://www.nseindia.com/api/corporate-announcements"
                 "?index=equities&symbol=%s")

# One request at a time with a pause. NSE rate-limits aggressively and a fetcher that
# trips it gets 403s for everyone behind it, not just for itself.
POLITE_DELAY_SECONDS = 2.0
MAX_CANDIDATES = 12

# Filename and description fragments worth downloading. Deliberately loose: it excludes
# the obvious non-statements and nothing more. The decision is made on content.
STATEMENTS_HINT = re.compile(
    r"(outcome|auditedfinancial|financialresult|seintfinancial|audfs|fs_signed|"
    r"integrated_filing|financials|financial_results|bmoutcome)", re.I)

# Filings that are never the financial statements. Each exclusion is a document class
# observed in real feeds, not a guess at one.
#
# NOT excluded: "revised financial results". A correction filing is still the statements,
# and excluding it would leave a filer whose only results attachment happens to be a
# revision with no source at all -- which was a bug in the first version of this filter.
GOVERNANCE = re.compile(
    r"(secretarial|\bcsr\b|minutes|regulation ?43|acquisition|insider|pledge|"
    r"intimation as per|intimation[_-]?(auditor|outcomeofbm|outcome)|"
    r"newpaper_advt|open ?offer|scheme of arrangement|scheme of arrangement|"
    r"calendar|analyst|broker|intimationauditor|auditorchange|"
    r"post_?bm|board ?meeting|agm_?outcome)", re.I)

# The balance sheet identifies itself by its own subtotals.
#
# BOTH are required, not one. A single phrase is not enough: an auditor's report or a
# board letter refers to "total current assets" in passing, and a substring test for one
# phrase accepted such a document as the statements. A page carrying BOTH the current-asset
# subtotal and the grand total is a balance sheet -- prose mentions one, not both, and
# every Indian filer prints both on the same page.
_BS_CURRENT_SUBTOTAL = re.compile(r"total current assets", re.I)
_BS_TOTAL = re.compile(r"total assets", re.I)

# One pattern per caption rather than a single alternation: the squashed match below
# strips whitespace from each pattern individually and looks for it as a substring, and
# an alternation cannot be squashed that way. These five replaced `_BS_CAPTION`, which
# became dead the moment the squashed form was added -- a pattern that no code consults
# is a second, quieter definition of what a balance sheet is.
_BS_CAPTION_PATTERNS = (
    re.compile(r"cash and cash equivalents", re.I),
    re.compile(r"bank balances", re.I),
    re.compile(r"inventor", re.I),
    re.compile(r"prepaid", re.I),
    re.compile(r"trade receiv", re.I),
)

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def parse_an_dt(value) -> "datetime | None":
    """`an_dt` is `"30-Aug-2018 08:40:00"`. Returns None rather than guessing."""
    m = re.match(r"\s*(\d{1,2})-([A-Za-z]{3})-(\d{4})\s+(\d{2}):(\d{2}):(\d{2})",
                 str(value or ""))
    if not m:
        return None
    mon = _MONTHS.get(m.group(2)[:3].title())
    if not mon:
        return None
    try:
        return datetime(int(m.group(3)), mon, int(m.group(1)),
                        int(m.group(4)), int(m.group(5)), int(m.group(6)))
    except ValueError:
        return None


def parse_dt(value) -> "datetime | None":
    """`dt` is `ddmmyyyyHHMMss` -- DAY first, four-digit year.

    Cross-checked against `parse_an_dt` on every row of a live TCS feed: 3368 agree, 0
    disagree. Sorting this field as text inverts the order across centuries, which is how
    an earlier version of this fetcher preferred a 2019 filing to a 2025 one.
    """
    s = str(value or "")
    if not re.fullmatch(r"\d{14}", s):
        return None
    try:
        return datetime(int(s[4:8]), int(s[2:4]), int(s[0:2]),
                        int(s[8:10]), int(s[10:12]), int(s[12:14]))
    except ValueError:
        return None


def announcement_date(row: dict) -> "datetime | None":
    """`an_dt` preferred, `dt` as the fallback. Undated rows return None.

    None sorts LAST rather than first. An attachment whose age is unknown cannot be
    called the most recent one, and treating it as recent is how a stale filing wins.
    """
    return parse_an_dt(row.get("an_dt")) or parse_dt(row.get("dt"))


@dataclass
class Candidate:
    url: str
    announced: "datetime | None"
    label: str = ""
    # How strongly the FILENAME itself claims to be a statements document: 2 if it does,
    # 1 if only the description does, 0 if neither (which the filter has already excluded).
    named: int = 0

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]


@dataclass
class Rejection:
    url: str
    reason: str
    pages: "int | None" = None


@dataclass
class Acquisition:
    symbol: str
    attachment: "Path | None" = None
    url: str = ""
    announced: "datetime | None" = None
    pages: "int | None" = None
    balance_sheet_pages: list = field(default_factory=list)
    tried: int = 0
    rejections: list = field(default_factory=list)
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.attachment is not None


def candidate_attachments(rows: Iterable[dict]) -> list:
    """PDF attachments worth downloading, best-NAMED first, then newest first.

    The `named` score exists because Tata Steel's feed defeated a date ordering. Of 3025
    announcements, 91 passed the statements filter and the twelve newest were all disposal
    notices -- `NIDHIFADNAVIS_..._BSENSE.pdf`, two pages each, whose DESCRIPTIONS disclose
    the financial results of the divested unit. The audited results were in the set the
    whole time, at `..._Board_Outcome_-_March_17_2026.pdf`, ranked below a year of
    notices, and the fetcher reported "no attachment carried a balance sheet".

    So a filename that names itself as results outranks one that only its description
    suggests. This is a property of the DOCUMENT rather than of the filing date, and it
    discards nothing. Ordering by size instead was measured and failed identically: the
    largest candidates were the notices too.

    Undated rows sort LAST within their score: an unknown date cannot be called recent.
    """
    out = []
    for row in rows:
        url = row.get("attchmntFile") or ""
        if not url.lower().endswith(".pdf"):
            continue
        blob = " ".join([url, row.get("desc") or "", row.get("attchmntText") or ""])
        if GOVERNANCE.search(blob) or not STATEMENTS_HINT.search(blob):
            continue
        name = url.rsplit("/", 1)[-1]
        out.append(Candidate(
            url=url,
            announced=announcement_date(row),
            label=(row.get("attchmntText") or row.get("desc") or "")[:90],
            named=2 if STATEMENTS_HINT.search(name) else 1,
        ))
    out.sort(key=lambda c: (c.named, c.announced is not None,
                            c.announced or datetime.min), reverse=True)
    return out


def _letters(text: str) -> str:
    """Lowercase letters only, so a caption survives punctuation and spacing.

    Not merely whitespace. Tata Steel's faces print

        Sub-total - C urrent assets        36,765.14   40,515.56
        T O T A L - A S SE T S

    where the figure sits between the two halves of a caption and the words are both
    hyphenated and letter-spaced. Dropping whitespace alone leaves `total-assets` and
    `2,45,634.06` between the halves and neither matches -- which is why squashing
    whitespace was measured here and rejected, while dropping non-letters was measured
    and accepted. An earlier claim that whitespace-squashing fixed this filing was wrong.
    """
    return re.sub(r"[^a-z]", "", text.lower())


def _present(pattern: re.Pattern, text: str, letters: str) -> bool:
    """True when `pattern` occurs in the text, as written or with punctuation dropped."""
    if pattern.search(text):
        return True
    return re.sub(r"[^a-z]", "", pattern.pattern) in letters


def looks_like_balance_sheet(text: str) -> bool:
    """True when `text` is a balance sheet rather than a document mentioning one.

    Each of the three checks is tried against the text as extracted and again against its
    letters alone. The second form exists because some filers position every glyph
    separately and pdfplumber then inserts a space between each one, so `T O T A L - A S
    SE T S` is not the string `total assets` under any reading that keeps the punctuation.

    Dropping non-letters is blunt, so the false-positive risk is pinned by measurement
    rather than by argument. Across the committed TCS (25pp) and HCLTech (45pp) fixtures
    this rule accepts exactly the pages the previous rule accepted -- 11 and 20, and 5 --
    and gains none. Across Tata Steel's 30-page outcome it accepts printed pages 17 and
    21, which are the two real faces, while still REJECTING printed pages 19 and 25:
    those are Regulation 52(4) ratio disclosures, which print "Total current assets" and
    "Total assets" as inputs to a current ratio, and they are the reason this rule demands
    a caption as well as both subtotals. A ratio table is not a balance sheet, and a
    normalisation loose enough to find `Sub-total - Current assets` could easily have let
    them in.
    """
    if not text:
        return False
    letters = _letters(text)
    if not _present(_BS_CURRENT_SUBTOTAL, text, letters):
        return False
    if not _present(_BS_TOTAL, text, letters):
        return False
    return any(_present(p, text, letters) for p in _BS_CAPTION_PATTERNS)


def balance_sheet_pages(pdf, limit: int = 6) -> list:
    """Printed page numbers carrying the balance sheet, found by content."""
    found = []
    for i in range(len(pdf.pages)):
        try:
            text = pdf.pages[i].extract_text() or ""
        except Exception:  # noqa: BLE001 -- a page that will not extract is not a match
            continue
        if looks_like_balance_sheet(text):
            found.append(i + 1)
            if len(found) >= limit:
                break
    return found


class NSEFilings:
    """Fetches one usable statements attachment per symbol.

    `opener` and `fetch` are injectable so the selection logic can be tested without a
    network. Every test in the suite does exactly that, because a fetcher that can only
    be tested against the live exchange is a fetcher that is never tested.
    """

    def __init__(self, cache_dir: Path, delay: float = POLITE_DELAY_SECONDS,
                 max_candidates: int = MAX_CANDIDATES,
                 opener: "Callable | None" = None,
                 fetch: "Callable | None" = None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.max_candidates = max_candidates
        self._opener = opener or self._default_opener
        self._fetch = fetch or self._default_fetch

    # ---------------------------------------------------------------- transport

    @staticmethod
    def _default_opener():
        o = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        o.addheaders = [
            ("User-Agent", BROWSER_UA),
            ("Accept", "*/*"),
            ("Accept-Encoding", "gzip"),
            # NSE 403s a request with no Referer, which is why the session cookie alone
            # was not enough in the first attempt.
            ("Referer", NSE_HOME),
        ]
        return o

    def _default_fetch(self, opener, url: str, timeout: int = 300) -> bytes:
        req = urllib.request.Request(url, headers={
            "User-Agent": BROWSER_UA, "Accept": "*/*", "Referer": NSE_HOME})
        with opener.open(req, timeout=timeout) as resp:
            return resp.read()

    def announcements(self, symbol: str) -> list:
        opener = self._opener()
        # The session cookie comes from the homepage. Without it the API answers 403,
        # which is what made this look unreachable in the first place.
        try:
            opener.open(NSE_HOME, timeout=30).read(2048)
        except Exception:  # noqa: BLE001 -- the API request below is the real test
            pass
        raw = self._fetch(opener, ANNOUNCEMENTS % symbol.upper(), timeout=60)
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        data = json.loads(raw)
        if isinstance(data, dict):
            return data.get("data") or data.get("rows") or []
        return data if isinstance(data, list) else []

    # ---------------------------------------------------------------- selection

    def acquire(self, symbol: str, refresh: bool = False) -> Acquisition:
        symbol = symbol.upper()
        pdf_path = self.cache_dir / ("%s.pdf" % symbol.lower())
        meta_path = self.cache_dir / ("%s.json" % symbol.lower())

        if not refresh and pdf_path.exists() and meta_path.exists():
            info = json.loads(meta_path.read_text(encoding="utf-8"))
            return Acquisition(
                symbol=symbol,
                attachment=pdf_path if pdf_path.exists() else None,
                url=info.get("url", ""),
                announced=parse_an_dt(info.get("announced_text")) or parse_dt(
                    info.get("announced_stamp")),
                pages=info.get("pages"),
                balance_sheet_pages=info.get("balance_sheet_pages") or [],
                tried=info.get("tried", 0),
                note="from cache",
            )

        result = Acquisition(symbol=symbol)
        try:
            rows = self.announcements(symbol)
        except Exception as exc:  # noqa: BLE001
            result.note = "announcements unavailable: %s" % type(exc).__name__
            return result

        candidates = candidate_attachments(rows)
        if not candidates:
            result.note = "no candidate attachments in %d announcements" % len(rows)
            return result

        import pdfplumber  # imported here so the selection logic stays importable alone

        for candidate in candidates[: self.max_candidates]:
            if self.delay:
                time.sleep(self.delay)
            result.tried += 1
            try:
                body = self._fetch(self._opener(), candidate.url)
            except Exception as exc:  # noqa: BLE001
                result.rejections.append(
                    Rejection(candidate.url, "download failed: %s" % type(exc).__name__))
                continue

            if body[:4] != b"%PDF":
                result.rejections.append(Rejection(candidate.url, "not a PDF"))
                continue

            try:
                with pdfplumber.open(io.BytesIO(body)) as pdf:
                    npages = len(pdf.pages)
                    pages = balance_sheet_pages(pdf)
            except Exception as exc:  # noqa: BLE001
                result.rejections.append(Rejection(
                    candidate.url, "unreadable PDF: %s" % type(exc).__name__))
                continue

            if not pages:
                result.rejections.append(
                    Rejection(candidate.url, "no balance sheet in %d pages" % npages,
                              npages))
                continue

            pdf_path.write_bytes(body)
            meta_path.write_text(json.dumps({
                "symbol": symbol,
                "url": candidate.url,
                "announced_text": candidate.announced.strftime("%d-%b-%Y %H:%M:%S")
                if candidate.announced else None,
                "announced_stamp": candidate.announced.strftime("%d%m%Y%H%M%S")
                if candidate.announced else None,
                "pages": npages,
                "balance_sheet_pages": pages,
                "bytes": len(body),
                "tried": result.tried,
                "label": candidate.label,
            }, indent=2), encoding="utf-8")

            result.attachment = pdf_path
            result.url = candidate.url
            result.announced = candidate.announced
            result.pages = npages
            result.balance_sheet_pages = pages
            result.note = candidate.label
            return result

        result.note = ("no attachment carried a balance sheet (%d tried)"
                       % result.tried)
        return result


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--cache", default=str(NSE_CACHE_DIR))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--max", type=int, default=MAX_CANDIDATES)
    parser.add_argument("--delay", type=float, default=POLITE_DELAY_SECONDS)
    args = parser.parse_args(argv)

    fetcher = NSEFilings(Path(args.cache), delay=args.delay,
                         max_candidates=args.max)
    width = max(len(s) for s in args.symbols) + 2
    failures = 0
    for symbol in args.symbols:
        got = fetcher.acquire(symbol, refresh=args.refresh)
        if got.ok:
            print("%-*s %s  %d pages, balance sheet at %s  (tried %d)"
                  % (width, symbol, got.url.rsplit("/", 1)[-1][:44], got.pages,
                     got.balance_sheet_pages, got.tried))
            print("%-*s announced %s" % (width, "", got.announced))
        else:
            failures += 1
            print("%-*s FAILED: %s" % (width, symbol, got.note))
            for rej in got.rejections[:5]:
                print("%-*s   %-48s %s"
                      % (width, "", rej.url.rsplit("/", 1)[-1][:48], rej.reason))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
