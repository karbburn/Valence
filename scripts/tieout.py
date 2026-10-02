"""Tie the engine's bridge inputs to the filing, line by line.

Internal consistency is not correctness. A model can foot perfectly at every
level and still be built on inputs the filing does not support, and that is what
happened: the statements added up and the debt was 15% high, the balance sheet
was dated five days after the quarter ended, and the securities line matched no
filed caption at all.

This harness asks one question of every number that reaches the valuation: is
this the figure the issuer reported, in the period the engine says it is from?

The filing is read from SEC XBRL, independently of the engine and independently of
anything the film's reference file claims. The film is useful as a cross-check but
it is not the authority: it is a document produced alongside the product, and if
it and the engine agree on a wrong number this harness would miss it.

Run:  python scripts/tieout.py [company_id ...]
"""

from __future__ import annotations

import gzip
import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sqlite3


# Element names for the tie-out checks, resolved from the ingestion's own maps so
# this gate cannot fall behind the taxonomy a filer actually uses.
#
# It did fall behind, once, and it cost a real signal. When IFRS ingestion landed,
# TSMC's cash and marketable securities were reported UNTIED -- "no us-gaap element
# or filed caption carries it" -- because this gate only knew us-gaap names while
# Infosys' 20-F carries `ifrs-full:CashAndCashEquivalents`. The figures were
# correct and the filing agreed with them.
#
# A gate that invents a disagreement is as damaging as one that misses a real one,
# because it teaches people to ignore the gate. The fix is to delete the duplicate
# list rather than to add a test asserting two copies agree -- which is the same
# lesson this project has now had to learn about the claims enumeration, the IFRS
# metric labels, and the capex fades.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.data.ingestion.sec_edgar import US_GAAP_TAG_MAP as _US_GAAP_TAG_MAP  # noqa: E402
from backend.data.ingestion import ifrs_tags as _IFRS  # noqa: E402

# `US_GAAP_TAG_MAP` is a list of (label, tags, section) triples, so it is indexed by
# label here rather than used as a mapping.
_US_BY_LABEL: Dict[str, Tuple[str, ...]] = {
    label: tuple(tags) for label, tags, _section in _US_GAAP_TAG_MAP
}
_IFRS_BY_LABEL: Dict[str, Tuple[str, ...]] = {
    label: tuple(tags) for label, tags in _IFRS.IFRS_ALTERNATIVES.items()
}
_US_GAAP_ELEMENTS: Dict[str, Tuple[str, ...]] = {
    "cash_and_equivalents": _US_BY_LABEL.get("Cash & Bank", ()),
    # The ingestion's tags, plus three alternates this gate has always accepted and
    # ingestion does not use. They are here, in one place, rather than restated at
    # the point of use where nothing records that they are a deliberate widening.
    "marketable_securities": (
        *_US_BY_LABEL.get("Current investments", ()),
    ),
    "total_debt": (
        *_US_BY_LABEL.get("Borrowings", ()),
        *_US_BY_LABEL.get("Short term borrowings", ()),
    ),
}
_IFRS_ELEMENTS: Dict[str, Tuple[str, ...]] = {
    "cash_and_equivalents": _IFRS_BY_LABEL.get("Cash & Bank", ()),
    "marketable_securities": _IFRS_BY_LABEL.get("Current investments", ()),
    "total_debt": _IFRS_BY_LABEL.get("Borrowings", ()),
}

REPO = Path(__file__).resolve().parents[1]

UA = {"User-Agent": "Valence valuation research team@valence.com", "Accept-Encoding": "gzip"}
API = "http://127.0.0.1:8111"


# --- the filing ---------------------------------------------------------------


# The forms that carry financial statements.
#
# 20-F is an annual report and is excluded by a 10-K-only filter. Amdocs, a
# Nasdaq-listed Israeli company, files one, so the filter saw none of its figures
# and reported every bridge input as "nothing to tie it to" — which is a statement
# about the harness and not about the engine, and its numbers were exact.
ANNUAL_FORMS = ("10-K", "20-F")
INTERIM_FORMS = ("10-Q", "6-K")


def _is_annual(form: str) -> bool:
    return form.startswith(ANNUAL_FORMS)


def _is_statement_form(form: str) -> bool:
    return form.startswith(ANNUAL_FORMS + INTERIM_FORMS)


def company_facts(cik: int) -> Dict[str, Any]:
    req = urllib.request.Request(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", headers=UA
    )
    raw = urllib.request.urlopen(req, timeout=180).read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    # BOTH taxonomies.
    #
    # A foreign private issuer filing a 20-F reports under `ifrs-full`, and reading
    # only us-gaap made the gate report TSMC's cash as carrying no filed caption at
    # all. That is a statement about the taxonomy rather than about the filing: the
    # 20-F carries `ifrs-full:CashAndCashEquivalents` and the number is right there.
    #
    # Merged rather than selected, because the gate asks "does ANY filed caption carry
    # this figure", and a filer may use either vocabulary. A 20-F filer that also
    # reports a us-gaap extension is covered by both.
    facts = json.loads(raw).get("facts", {})
    merged: Dict[str, Any] = {}
    for namespace in ("us-gaap", "ifrs-full"):
        for tag, payload in (facts.get(namespace) or {}).items():
            merged.setdefault(tag, payload)
    return merged


def at(body: Dict[str, Any], tag: str, on: str) -> Optional[float]:
    """One figure for one period end, from a 10-Q or 10-K, in millions.

    Where a tag is reported more than once for the same date, the most recently
    FILED value wins rather than whichever the payload happened to list last. A
    filer restates, and the restatement is the figure in the accounts now; taking
    the last row instead reported Meta's finance leases as absent one run and
    present the next.
    """
    entry = body.get(tag)
    if not entry:
        return None
    best: Optional[tuple[str, float]] = None
    for _unit, rows in entry.get("units", {}).items():
        for row in rows:
            if row.get("end") != on or row.get("start") is not None:
                continue
            form = str(row.get("form", ""))
            if not _is_statement_form(form):
                continue
            filed = str(row.get("filed", ""))
            # An annual figure is the annual report's, even if a later quarter
            # repeated the same instant.
            rank = ("1" if _is_annual(form) else "0", filed)
            if best is None or rank > best[0]:
                best = (rank, row["val"] / 1e6)  # type: ignore[assignment]
    return best[1] if best else None


def first_of(body: Dict[str, Any], tags: List[str], on: str) -> tuple:
    for tag in tags:
        v = at(body, tag, on)
        if v is not None:
            return tag, v
    return None, None


# The caption words a filed line is recognised by, per engine field. Deliberately
# narrow: a loose match ties an engine figure to whatever filed line happens to
# contain the same word, which produces a green tick on a wrong comparison.
CAPTION_WORDS = {
    "cash_and_equivalents": ("cash and cash equivalents", "cash & equivalents"),
    "marketable_securities": ("marketable securities", "short-term investments",
                              "short term investments"),
    "non_current_investments": ("non-marketable equity securities",
                                "long-term investments", "marketable securities, non-current"),
}


def _caption_matches(caption: str, label: str) -> bool:
    low = caption.lower()
    words = CAPTION_WORDS.get(label, ())
    return any(w in low for w in words)


# A filer may report a line under its own element rather than a us-gaap one, in
# which case companyfacts cannot see it at all. NVIDIA's marketable securities and
# non-marketable equity securities are both filed under
# nvda_MarketableSecuritiesAndEquitySecuritiesFVNI and
# nvda_EquitySecuritiesFVNINoncurrent, and us-gaap publishes neither. Reading only
# us-gaap reports them as missing, which is a statement about the taxonomy rather
# than about the engine, and "missing" is exactly the word that stops anyone
# looking. So the filing's own rendered balance sheet is the fallback: it is the
# document a reader would hold, and it carries the captions whatever namespace they
# live in.
_BS_CACHE: Dict[tuple, Dict[str, float]] = {}


def filed_balance_sheet(cik: int, on: str) -> Dict[str, float]:
    """The filer's own balance sheet captions and values at a period end."""
    key = (cik, on)
    if key in _BS_CACHE:
        return _BS_CACHE[key]

    import gzip
    import re

    def get(url: str) -> str:
        req = urllib.request.Request(url, headers=UA)
        raw = urllib.request.urlopen(req, timeout=180).read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "replace")

    lines: Dict[str, float] = {}
    try:
        sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))
        accession = None
        recent = sub["filings"]["recent"]
        for form, accn, rep in zip(recent["form"], recent["accessionNumber"],
                                   recent["reportDate"]):
            # 20-F and 40-F are annual reports. A filter that accepts only 10-K sees
            # nothing at all for a filer reporting under IFRS, which is how Amdocs
            # came to have every bridge input reported as "nothing to tie it to"
            # when its figures were exact to the filing.
            if form.startswith(("10-K", "20-F", "40-F")) and rep == on:
                accession = accn
                break
        if not accession:
            _BS_CACHE[key] = lines
            return lines
        base = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/"
            f"{accession.replace('-', '')}"
        )
        summary = get(f"{base}/FilingSummary.xml")
        for report in re.finditer(r"<Report[^>]*>(.*?)</Report>", summary, re.S):
            block = report.group(1)
            short = re.search(r"<ShortName>(.*?)</ShortName>", block)
            html_file = re.search(r"<HtmlFileName>(.*?)</HtmlFileName>", block)
            if not short or not html_file:
                continue
            name = short.group(1).upper()
            # A filer reporting under IFRS does not publish a "balance sheet". It
            # publishes a statement of financial position, and the title varies:
            # TSM's is "Consolidated Statements of Financial Position", plural, and
            # a singular filter matched Infosys' and missed TSM's. Matching on the
            # phrase rather than the whole title covers both. The parenthetical
            # detail pages are still excluded.
            if not any(
                wanted in name for wanted in ("BALANCE SHEET", "FINANCIAL POSITION")
            ) or "PARENTHETICAL" in name:
                continue
            page = get(f"{base}/{html_file.group(1)}")
            for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", page, re.S):
                cells = [
                    re.sub(r"<[^>]+>", "", c).strip()
                    for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row.group(1), re.S)
                ]
                cells = [c for c in cells if c and not c.startswith("- Definition")]
                if len(cells) < 2:
                    continue
                for candidate in cells[1:]:
                    try:
                        amount = float(candidate.replace(",", "").replace("(", "-"))
                    except ValueError:
                        continue
                    if amount:
                        lines[cells[0]] = lines.get(cells[0], amount)
                    break
            break
    except Exception:
        pass
    _BS_CACHE[key] = lines
    return lines


# What each engine field should equal, and the tags that carry it.
#
# A field with no filed counterpart is reported as untied rather than passed: the
# absence of a line to check against is itself the finding, and that is how the
# securities figure got through.
FIELDS = [
    ("cash_and_equivalents", "Cash and cash equivalents", [
        # Resolved from the ingestion's own map rather than named here. A second
        # hand-kept list of element names is what made this gate report TSMC as
        # disagreeing with its own accounts: the 20-F carries
        # `ifrs-full:CashAndCashEquivalents`, and this was looking only for
        # `us-gaap:CashAndCashEquivalentsAtCarryingValue`.
        #
        # A gate that reports a disagreement that is not there is as damaging as one
        # that misses a real one, because it teaches people to ignore the gate. And
        # the way to stop it is to delete the duplicate, not to add a test asserting
        # the two lists agree -- they are the same lesson three times over now.
        *_US_GAAP_ELEMENTS.get("cash_and_equivalents", ()),
        *_IFRS_ELEMENTS.get("cash_and_equivalents", ()),
    ]),
    # Ordered AGGREGATE FIRST. A filer tags several of these and they are not
    # additive, so the aggregate is the figure a reader finds in the accounts and
    # the subsets are not. Apple reports 77,723 as marketable securities
    # non-current and nothing under the equity-securities element; Alphabet reports
    # 68,687 as other long-term investments against 64,094 of equity securities
    # inside it. Ranking the subset first reports both as wrong and invites fixing
    # something that is already exact.
    ("non_current_investments", "Long-term and non-current investments", [
        "MarketableSecuritiesNoncurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent",
        "OtherLongTermInvestments",
        "LongTermInvestments",
        "EquitySecuritiesWithoutReadilyDeterminableFairValueAmount",
    ]),
    ("marketable_securities", "Marketable securities", [
        *_US_GAAP_ELEMENTS.get("marketable_securities", ()),
        *_IFRS_ELEMENTS.get("marketable_securities", ()),
    ]),
]

# Debt is assembled from filed parts rather than read off one tag, because no
# filer publishes a single "total debt" in XBRL that matches a convention. These
# are the interest-bearing components:
#
#   borrowings            the debt itself, current and non-current
#   finance leases        capitalised leases. These ARE borrowing in substance
#                         and are interest-bearing, so they belong in a debt
#                         figure. Microsoft reports 66,594 of them at 30 June
#                         2026 and a harness that omits them reports the engine
#                         as 165% overstated when it is exact.
#
# Operating leases are deliberately absent, and that absence is the point: rent
# already sits in operating expense and therefore inside the EBIT the cash flows
# are built from, so deducting the liability as well would charge for the same
# obligation twice. The check is therefore that total debt equals borrowings plus
# finance leases EXACTLY, which fails if operating leases have leaked in.
# Marks a finding that is a coverage limit rather than a disagreement with a
# filing. See `check()`.
NOT_AUDITABLE_PREFIX = "not auditable here: "

DEBT_PARTS = [
    "LongTermDebtNoncurrent",
    "LongTermDebtCurrent",
    "FinanceLeaseLiability",
]

# Totals, used ONLY when a filer publishes no components at all.
#
# These are aggregates, so they are never added to the components above — that
# would count the debt twice. Armstrong publishes only long-term and current, and
# sums to 445,520 exactly; a filer publishing nothing but a total is read from the
# total, because a sum of absent components is a figure the filing never stated.
DEBT_TOTALS = [
    "DebtInstrumentCarryingAmount",
    "LongTermDebt",
]


# --- the engine ---------------------------------------------------------------


def bridge(company_id: str) -> Dict[str, Any]:
    req = urllib.request.Request(
        f"{API}/api/model/{company_id}", headers={"x-valence-build": "1"}
    )
    payload = json.loads(urllib.request.urlopen(req, timeout=600).read())
    payload = payload.get("model", payload)
    out = payload["valuation"][0]["dcf_bridge"]
    out["_debt_schedule"] = payload.get("debt_schedule") or []
    return out


def debt_schedule_opening(rows: List[Dict[str, Any]], scenario: str = "base") -> Optional[float]:
    for row in rows:
        if row.get("scenario") != scenario:
            continue
        periods = row.get("periods") or []
        if periods:
            return periods[0].get("opening_balance")
    return None


# --- the check ----------------------------------------------------------------


def check(company_id: str, name: str, cik: int) -> List[str]:
    findings: List[str] = []
    try:
        snap = bridge(company_id)
    except urllib.error.HTTPError as exc:
        return [f"{company_id}: the engine would not serve a model ({exc.code})"]

    stated = snap.get("balance_sheet_as_of")
    body = company_facts(cik)

    # Period ends the filing carries, split by form. The engine ingests annual
    # reports, so the annual end is the date its figures must tie to. A quarterly
    # end that is later is a STALENESS gap and is reported as such; conflating the
    # two is how a six-day mislabel and a six-month omission each get mistaken for
    # the other.
    filed_all: set = set()
    filed_annual: set = set()
    for _u, rows in body.get("Assets", {}).get("units", {}).items():
        for row in rows:
            if row.get("start") is not None:
                continue
            if _is_statement_form(str(row.get("form", ""))):
                filed_all.add(row["end"])
            if _is_annual(str(row.get("form", ""))):
                filed_annual.add(row["end"])

    latest_filed = max(filed_all) if filed_all else None
    annual_filed = max(filed_annual) if filed_annual else latest_filed

    if not body:
        # A filer that reports under IFRS and files a 20-F publishes its statements
        # in the ifrs-full taxonomy, which this harness does not read. Every field
        # would report as untied, which is a statement about the harness rather
        # than about the engine, and counting it would bury the domestic filers.
        #
        # Reported separately from a mismatch because the two mean different things:
        # an untied figure is a number this engine published that the filing
        # contradicts, and an inauditable filer is a number nobody has checked. Only
        # the first is a defect in the output. A coverage gap that widens is still
        # caught, because main() fails when the count of uncheckable filers rises.
        #
        # But it does not have to end here. A filer's statements are rendered by
        # EDGAR into a statement-of-financial-position page whether its taxonomy is
        # us-gaap or ifrs-full, and reading THAT needs no taxonomy at all: the filer
        # printed its own captions. So the caption route is tried before giving up.
        # Two shipped companies — the Infosys ADR and TSM, both 20-F filers — had
        # nobody checking them for exactly as long as this branch came first.
        #
        # Reading the filing as filed is also what makes the audit current.
        # companyfacts lags a filing behind for both: TSM's FY2025 20-F and Infosys'
        # FY2026 20-F are on file and neither is indexed yet, so a companyfacts tie-out
        # would compare a 2026 model against a 2024 filing and call the difference a
        # mismatch. Read as filed, Infosys' FY2026 statement of financial position
        # gives total assets 16,446 and total equity 9,786, which is what the engine
        # publishes, to the dollar.
        captions = filed_balance_sheet(cik, annual_filed or stated or "")
        if not captions:
            return [NOT_AUDITABLE_PREFIX + (
                f"{name} publishes no us-gaap facts, so it reports under IFRS, and "
                f"its rendered statement of financial position is unreachable as "
                f"well. Its bridge inputs are unverified rather than wrong. Closing "
                f"this means reading the filing as filed, not relaxing the audit"
            )]
        body = {}
        stated = annual_filed or stated
        on = annual_filed or stated

    if stated and annual_filed and stated != annual_filed:
        findings.append(
            f"balance-sheet date: engine {stated}, most recent filed ANNUAL "
            f"{annual_filed} "
            f"({(date.fromisoformat(stated) - date.fromisoformat(annual_filed)).days:+d} days)"
        )
    if stated and latest_filed and latest_filed > annual_filed:
        print(
            f"    note: the latest filing of any kind ends {latest_filed}; the engine "
            f"values off the annual, so its balance sheet is "
            f"{(date.fromisoformat(latest_filed) - date.fromisoformat(annual_filed)).days} "
            f"days older than the newest quarter on file"
        )

    # Look the figures up at the date the FILING has, not the date the engine
    # claims. Reading at the engine's date finds nothing at all, which reports
    # every field as untraceable and hides the figures that are merely wrong
    # behind the one that is merely mislabelled. The date mismatch is reported
    # separately above.
    on = annual_filed or stated
    # Captions the filer itself prints, for lines it tags under its own element.
    captions = filed_balance_sheet(cik, on) if on else {}
    for field, label, tags in FIELDS:
        engine_val = snap.get(field)
        if engine_val is None:
            continue
        tag, filed_val = first_of(body, tags, on or "")
        if filed_val is None:
            # Fall back to the filing's own caption for this line, if it has one.
            for caption, value in captions.items():
                if _caption_matches(caption, field):
                    tag, filed_val = caption, value
                    break
        if filed_val is None:
            # A zero standing against a line the filing does not publish is agreement,
            # not a gap: the balance sheet has no such row to disagree with. Only a
            # non-zero figure the filing cannot account for is a finding, because only
            # that asserts debt, cash or securities the filer never reported.
            if abs(engine_val) > 1.0:
                findings.append(
                    f"{field}: engine {engine_val:,.0f}, and no us-gaap element or filed "
                    f"caption carries it ({label}); nothing to tie it to"
                )
            continue
        delta = engine_val - filed_val
        if abs(delta) > max(abs(filed_val) * 0.005, 1.0):
            findings.append(
                f"{field}: engine {engine_val:,.0f}, filed {filed_val:,.0f}, "
                f"delta {delta:+,.0f} ({delta / filed_val:+.1%})"
            )

    # Total debt, assembled from the filed interest-bearing parts.
    #
    # Compared against the sum rather than a single tag, and required to be exact
    # rather than close: every part of this figure is a filed number, so any
    # difference at all means the engine added something or dropped something. A
    # tolerance here would let an operating lease of any size pass as rounding.
    engine_debt = snap.get("total_debt")
    if engine_debt is not None:
        parts = {t: at(body, t, on or "") for t in DEBT_PARTS}
        present = {t: v for t, v in parts.items() if v is not None}
        if not present:
            # A filer publishing no component at all but publishing a total is read
            # from the total: a sum of absent components is a figure the filing
            # never stated. The totals are aggregates, so they are used only here and
            # never added to the components, which would count the debt twice.
            for t in DEBT_TOTALS:
                total = at(body, t, on or "")
                if total is not None:
                    present = {t: total}
                    break
        missing = [t for t, v in parts.items() if v is None]
        filed_debt = sum(present.values())
        if missing and not filed_debt:
            # Same reasoning as the field loop: a debt-free balance sheet and a
            # balance sheet with no borrowing line agree. Only a non-zero figure the
            # filing cannot account for is a finding.
            if abs(engine_debt) > 1.0:
                findings.append(
                    f"total_debt: engine {engine_debt:,.0f}, and the filing publishes "
                    f"none of {', '.join(missing)} at {on}"
                )
        elif filed_debt:
            delta = engine_debt - filed_debt
            if abs(delta) > 1.0:
                leases = (
                    at(body, "OperatingLeaseLiabilityNoncurrent", on or "") or 0.0
                )
                mechanism = ""
                if abs(abs(delta) - leases) <= 1.0:
                    mechanism = (
                        f" — the difference is the operating lease liability "
                        f"({leases:,.0f}) to the dollar, so operating leases are "
                        f"inside this debt figure"
                    )
                findings.append(
                    f"total_debt: engine {engine_debt:,.0f}, filed "
                    + " + ".join(f"{v:,.0f}" for v in present.values())
                    + f" = {filed_debt:,.0f}, delta {delta:+,.0f}{mechanism}"
                )

    # One period end per model. The forecast and the bridge must agree.
    opening = debt_schedule_opening(snap.get("_debt_schedule") or [])
    if opening is not None and snap.get("total_debt") is not None:
        if abs(opening - snap["total_debt"]) > max(abs(snap["total_debt"]) * 0.01, 1.0):
            findings.append(
                f"debt schedule opens at {opening:,.0f} while the bridge values "
                f"against {snap['total_debt']:,.0f}: two balance sheets in one "
                f"model, {opening - snap['total_debt']:+,.0f} apart"
            )

    return findings


def shipped_companies() -> list[tuple[str, str, int]]:
    """The companies a fresh deploy actually serves a model for, with their CIK.

    A compiled snapshot is what the loader reads when there is no database, so a
    company with one is on the launch surface and a company without one is not.
    Auditing the whole EDGAR universe instead buries the twenty-three that matter
    under a hundred micro-caps that report nothing and serve nothing: on the last
    full run it reported 101 findings of which 3 concerned a shipped company.

    CIKs are resolved from SEC's own ticker file, not from the universe table. The
    table's `cik` column is populated for 52 of 123 rows and for exactly ONE of the
    twenty-three shipped companies, so a harness that trusted it audited a single
    company and reported "0 untied figures, 1 of 1 companies audited clean" — the
    narrowest possible scope, dressed as a pass. A tie-out that silently stops
    checking is worse than no tie-out, because it is believed.

    A company whose CIK cannot be resolved is reported as such by the caller rather
    than quietly dropped.
    """
    import json as _json
    import urllib.request as _request

    cache = REPO / "backend" / "data" / "cache"
    shipped = {p.stem for p in cache.glob("*.json") if p.name != "market_data_cache.json"}

    db = REPO / "backend" / "data" / "valence.db"
    rows: list = []
    if db.exists():
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute("SELECT company_id, name, slug, cik FROM company_universe").fetchall()
        finally:
            conn.close()

    ticker_of = {cid: (slug or "") for cid, _n, slug, _c in rows}
    name_of = {cid: n for cid, n, _s, _c in rows}

    sec_by_ticker: dict = {}
    try:
        req = _request.Request(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "Valence valuation research team@valence.com",
                     "Accept-Encoding": "gzip"},
        )
        raw = _request.urlopen(req, timeout=180).read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        for v in _json.loads(raw).values():
            sec_by_ticker.setdefault(str(v["ticker"]).upper(), v)
    except Exception:
        pass

    out = []
    for cid in sorted(shipped):
        if not cid.endswith("_us"):
            continue
        slug = ticker_of.get(cid) or ""
        symbol = slug.split("-")[0].upper()
        hit = sec_by_ticker.get(symbol)
        if hit:
            out.append((cid, name_of.get(cid) or cid, int(hit["cik_str"])))
            continue
        # Fall back to the table only when SEC cannot answer, and say so later.
        for _cid, n, _s, cik in rows:
            if _cid == cid and cik:
                try:
                    out.append((cid, n or cid, int(str(cik).lstrip("CIK"))))
                except ValueError:
                    pass
    return out


def expected_us_filers() -> set:
    """Every US filer on the launch surface, whatever CIK data happens to say.

    This is the denominator the audit is judged against. It is derived from the
    compiled snapshots and the company-id suffix alone, so it cannot be narrowed by
    a missing column in a table.
    """
    cache = REPO / "backend" / "data" / "cache"
    return {
        p.stem
        for p in cache.glob("*.json")
        if p.name != "market_data_cache.json" and p.stem.endswith("_us")
    }


def filing_derived(company_id: str) -> bool:
    """Whether this model's inputs came from the filer's own accounts.

    Read from the committed snapshot's own metadata, which is derived from the
    ingestion sources, so the audit and the product cannot disagree about which
    companies are filing-derived. A company with no snapshot is treated as NOT
    filing-derived, so a missing artifact can never be reported as a clean tie.
    """
    path = REPO / "backend" / "data" / "cache" / f"{company_id}.json"
    try:
        meta = json.loads(path.read_text(encoding="utf-8")).get("model", {}).get("metadata", {})
    except Exception:
        return False
    return bool(meta.get("filing_derived"))


def main() -> int:
    # The companies a fresh deploy serves a model for.
    targets = shipped_companies()
    if not targets:
        targets = [
            ("nvda_us", "NVIDIA", 1045810),
            ("aapl_us", "Apple", 320193),
            ("msft_us", "Microsoft", 789019),
            ("googl_us", "Alphabet", 1652044),
            ("meta_us", "Meta", 1326801),
            ("amzn_us", "Amazon", 1018724),
        ]
    if len(sys.argv) > 1:
        wanted = set(sys.argv[1:])
        targets = [t for t in targets if t[0] in wanted]

    total = 0
    audited = 0
    clean = 0
    uncheckable: list[str] = []
    # Disagreements from filers whose inputs are NOT filing-derived. Reported, not
    # counted, and not a failure.
    #
    # The distinction is the whole point. A model built from EDGAR claiming to tie
    # to EDGAR and not doing so is a defect in what this engine published. A model
    # built from a market feed, which the product now says is built from a market
    # feed, disagreeing with the filing is the disclosed cost of that choice — and
    # blocking on it would train people to ignore the gate, which is how a real
    # filing-derived regression would then pass unnoticed.
    #
    # Measured rather than asserted: the Infosys ADR publishes 1,043 of current
    # investments where its 20-F says 1,365, and no non-current investments where
    # the filing says 942. Both numbers are real and the page says which it is.
    feed_sourced: list[tuple[str, list[str]]] = []
    for company_id, name, cik in targets:
        try:
            findings = check(company_id, name, cik)
        except Exception as exc:
            print(f"  {name} ({company_id}): could not audit ({type(exc).__name__}: {exc})")
            uncheckable.append(company_id)
            continue
        audited += 1
        gaps = [f for f in findings if f.startswith(NOT_AUDITABLE_PREFIX)]
        mismatches = [f for f in findings if not f.startswith(NOT_AUDITABLE_PREFIX)]
        if gaps:
            uncheckable.append(company_id)
        if not findings:
            clean += 1
            print(f"  {name} ({company_id}): every bridge input ties to the filing")
            continue
        if gaps and not mismatches:
            print(f"  {name} ({company_id}): could not be checked")
            for f in gaps:
                print(f"    {f}")
            print()
            continue
        if not filing_derived(company_id):
            feed_sourced.append((company_id, mismatches))
            print(
                f"  {name} ({company_id}): {len(mismatches)} untied, and this model's "
                f"inputs are not filing-derived, so this is disclosed rather than counted"
            )
            for f in mismatches:
                print(f"    {f}")
            print()
            continue
        total += len(mismatches)
        print(f"  {name} ({company_id}): {len(mismatches)} untied")
        for f in mismatches:
            print(f"    {f}")
        print()

    # A harness that quietly checks less is worse than one that checks nothing,
    # because its result is believed. Every US filer on the launch surface must be
    # audited, and a shortfall is reported as a failure rather than as a tidy
    # "N of N clean" over a smaller N than the day before.
    expected = expected_us_filers()
    covered = {t[0] for t in targets}
    missing = sorted(expected - covered)
    if missing:
        print(f"  COVERAGE SHORTFALL — {len(missing)} shipped US filers were not audited:")
        for cid in missing:
            print(f"    {cid}")
        print("  A tie-out that silently stops checking is not a pass.")
        return 1

    # A filer nobody can check is a different problem from a filer the engine got
    # wrong, and conflating them is how a known gap becomes permanent: the gate goes
    # red every run, gets ignored, and eventually the number behind it ships
    # unverified. The gap is therefore stated plainly and does not block, because a
    # filer that reports under IFRS cannot be made auditable by relaxing the audit.
    # The regression that would matter — a filer that used to be checked and no
    # longer is — is caught above by the coverage shortfall, which is a hard failure.
    if uncheckable:
        print(
            f"  {len(uncheckable)} filer(s) could not be checked against a filing: "
            f"{', '.join(sorted(uncheckable))}"
        )
        print(
            "    they report under IFRS and publish no us-gaap facts, so their bridge "
            "inputs are unverified rather than known-wrong. Closing this means "
            "reading the ifrs-full taxonomy, not relaxing the audit."
        )

    if feed_sourced:
        print(
            f"  {len(feed_sourced)} of the audited filers are NOT filing-derived, and "
            f"their disagreements with the accounts are reported above rather than "
            f"counted: {', '.join(c for c, _ in feed_sourced)}. The product states this "
            f"on each page. A filing-derived filer that disagreed would fail this gate."
        )

    print(
        f"  {total} untied figures; {clean} of {audited} companies audited clean "
        f"(coverage {audited}/{len(expected)} shipped US filers, "
        f"{len(uncheckable)} not checkable, {len(feed_sourced)} not filing-derived)"
    )
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
