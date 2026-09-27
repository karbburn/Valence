"""The full listed universe, not just the companies someone remembered to add.

The engine was never the limitation. ``resolve_cik`` in the SEC ingestion module
already fetches ``company_tickers.json`` to map an arbitrary ticker to a CIK, so
the pipeline can already service a company that is not in the local store. What
was missing was a way to *find* those companies, and a way to register one once
found, because ``/companies/resolve`` is the security boundary for the public
page routes and reads the universe store.

So this module is a lookup table, not a data source of truth:

* **US** from ``sec.gov/files/company_tickers.json``. Complete, free, no key,
  about 10,400 rows, and authoritative in the same sense the current hand-built
  list is: every entry is a filer that SEC itself publishes.
* **India** from the NSE listed-equity file. About 2,600 rows.

Both are cached on disk with a TTL, because a search runs on every keystroke and
a 780 KB download per keystroke is not a design. The first search of the day pays
for the fetch; the rest read the cache.

Exact match only. There is deliberately no fuzzy fallback: a near-miss that
resolved to a *different* company would start ingesting that company's filings
and then show a page whose URL does not match its contents. Returning nothing is
the safe failure, and the caller can say so.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# SEC publishes this list and requires a declared User-Agent. Kept identical to
# the headers the existing EDGAR ingestion already uses, because those are known
# to be accepted; see the note on SEC_CONTACT_EMAIL in routes.py.
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
NSE_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
SEC_HEADERS = {
    "User-Agent": "ValencePlatform team@valence.com",
    "Accept-Encoding": "gzip, deflate",
}

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "ticker_index"
CACHE_TTL_SECONDS = 24 * 60 * 60
FETCH_TIMEOUT = 30

# Only these two markets are supported end to end. An index row outside them is
# dropped rather than shown as a company the ingestion pipeline cannot service.
SUPPORTED = {"us", "india"}

# Legal-name fragments that mark a company the unlevered-FCFF engine cannot
# model. Kept separate from sector_filter.FINANCIAL_SECTOR_KEYWORDS because that
# list matches against a sector and industry field, which the exchange index does
# not carry; this one matches against the only field the index does carry. The
# overlap is deliberate rather than deduplicated, because the two classifiers are
# answering different questions from different inputs and one silently inheriting
# the other's list would break the moment either changed.
_FINANCIAL_NAME_HINTS = (
    "bank",
    "financial",
    "finance",
    "insurance",
    "assuran",
    "reit",
    "trust",
    "capital markets",
    "securities",
    "brokerage",
    "asset management",
    "investment",
    "finance and",
    "money changer",
    "nbfc",
    "microfinance",
    "leasing",
)

# The keyword list cannot catch a bank that is named after a person or a place.
# "JPMORGAN CHASE & CO" contains no industry word at all, which is exactly the
# case that matters most, and it is the one the resolver's own security test
# names. The global institutions are effectively a closed set, so they are listed
# rather than guessed at, and this list is the thing to edit when a new one floats.
#
# Every stem below is at least five characters, because these are matched as bare
# substrings. A shorter one is a loaded gun: "ing" is the Dutch bank ING and also
# the last three letters of "boeing", and an earlier version of this list blocked
# Boeing because of it. Short names go in _INSTITUTION_ABBREVIATIONS below, which
# are matched on word boundaries instead. The assertion after the tuple enforces
# the rule so the mistake cannot come back.
_INSTITUTION_STEMS = (
    # United States
    "jpmorgan", "goldman", "morgan stanley", "citigroup", "citibank", "bank of america",
    "wells fargo", "state street", "northern trust", "charles schwab", "raymond james",
    "stifel", "evercore", "blackrock", "franklin templeton", "invesco", "janus",
    "apollo", "carlyle", "blue owl", "brookfield", "equitable", "prudential",
    "metlife", "allstate", "chubb", "travelers", "aflac", "berkshire",
    # Europe and Japan
    "barclays", "credit suisse", "santander", "deutsche", "standard chartered",
    "natwest", "abn amro", "danske", "swiss re", "allianz", "munich re",
    "mitsubishi ufj", "sumitomo mitsui", "mizuho", "dai-ichi", "resona",
    # Canada and Australia
    "royal bank of canada", "scotiabank", "westpac", "national australia",
    "macquarie", "suncorp",
    # India
    "icici", "indusind", "kotak", "au small finance", "equitas", "bandhan",
    "federal bank", "karur vysya", "south indian bank", "punjab national",
    "bank of baroda", "bank of india", "canara bank", "union bank", "indian bank",
    "central bank", "uco bank",
)

# Institutions whose legal names are short enough that a bare substring match would
# collide with ordinary companies. Matched on word boundaries only, so "sbi" cannot
# match inside a longer word and "ing" cannot match "boeing".
_INSTITUTION_ABBREVIATIONS = (
    "ubs", "ing", "axa", "hsbc", "hdfc", "idfc", "kkr", "ares", "bmo", "cibc", "anz", "tmb",
    "sbi", "boi", "pnb", "iob", "uco", "aig",
)

# Guard the split between the two lists. A stem shorter than five characters is
# substring-matched and will block ordinary companies; failing at import is the
# right place to discover that, because a silently over-broad list otherwise hides
# inside the word "blocked" in somebody else's bug report.
assert all(len(s) >= 5 for s in _INSTITUTION_STEMS), (
    "institution stems are substring-matched, so any shorter than 5 characters "
    "will block ordinary companies; move it to _INSTITUTION_ABBREVIATIONS"
)

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, "ListedCompany"]]] = {}


@dataclass(frozen=True)
class ListedCompany:
    """One company as an exchange lists it, before it enters the universe."""

    ticker: str
    name: str
    market: str
    exchange: str
    cik: Optional[str] = None
    isin: Optional[str] = None

    @property
    def company_id(self) -> str:
        """The id the ingestion pipeline and model cache are keyed on.

        Delegated to ``build_company_id`` rather than reimplemented here, because
        getting it subtly wrong is invisible until a request 404s. It used to
        build ``{ticker}_{market}`` inline, which is right for the US
        (``nvda_us``) and wrong for India: the stored convention there repeats
        the ticker (``infy_infy``), so a discovered HDFCBANK would have been
        advertised as ``hdfcbank_india`` and then registered as
        ``hdfcbank_hdfcbank``, and the page route would ask for a model under an
        id that does not exist.

        A ticker listed on two exchanges is distinguished by market, which is why
        the collision handling in slugs.py needs the CIK at all.
        """
        from backend.data.universe.slugs import build_company_id

        return build_company_id(self.ticker, self.market)


def _normalise(ticker: str) -> str:
    return re.sub(r"[^A-Z0-9.\-]", "", ticker.strip().upper())


def _words(name: str) -> list[str]:
    """The uppercase alphanumeric words of a company name, in order.

    Matching a company name on a single squashed string is what made "LSB
    INDUSTRIES, INC." the top result for the query "SBIN": stripping the spaces
    produced LSBINDUSTRIESINC, and SBIN sits inside it, straddling a word
    boundary. It is not a company anyone looking for State Bank of India wants,
    and it was the first thing in the list.
    """
    return [w for w in re.split(r"[^A-Z0-9]+", (name or "").upper()) if w]


def _read_cache(market: str) -> Optional[dict[str, ListedCompany]]:
    path = CACHE_DIR / f"{market}.json"
    if not path.exists():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        if age > CACHE_TTL_SECONDS:
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("ticker index cache unreadable for %s: %s", market, exc)
        return None
    return {
        k: ListedCompany(**v) for k, v in raw.get("entries", {}).items()
    }


def _write_cache(market: str, entries: dict[str, ListedCompany]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": time.time(),
            "count": len(entries),
            "entries": {k: vars(v) for k, v in entries.items()},
        }
        (CACHE_DIR / f"{market}.json").write_text(
            json.dumps(payload, separators=(",", ":")), encoding="utf-8"
        )
    except OSError as exc:
        # A cache we cannot write is a performance problem, not a correctness
        # one. The lookup still works, it just refetches.
        logger.warning("ticker index cache not writable for %s: %s", market, exc)


def _fetch_us() -> dict[str, ListedCompany]:
    resp = requests.get(SEC_TICKER_URL, headers=SEC_HEADERS, timeout=FETCH_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    out: dict[str, ListedCompany] = {}
    for entry in data.values():
        ticker = _normalise(str(entry.get("ticker", "")))
        if not ticker:
            continue
        cik = entry.get("cik_str")
        out[ticker] = ListedCompany(
            ticker=ticker,
            name=str(entry.get("title", "")).strip() or ticker,
            market="us",
            # SEC is the source, but the filing carries no exchange, so this is
            # deliberately not invented from the ticker. An unknown exchange is
            # shown as SEC rather than guessed at NASDAQ.
            exchange="SEC",
            cik=str(cik).zfill(10) if cik is not None else None,
        )
    return out


def _fetch_india() -> dict[str, ListedCompany]:
    resp = requests.get(
        NSE_EQUITY_URL,
        headers={"User-Agent": SEC_HEADERS["User-Agent"]},
        timeout=FETCH_TIMEOUT,
    )
    resp.raise_for_status()
    text = resp.content.decode("utf-8", errors="replace")
    # The NSE file pads its column names with leading spaces.
    rows = csv.DictReader(io.StringIO(text))
    out: dict[str, ListedCompany] = {}
    for row in rows:
        clean = {(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}
        ticker = _normalise(clean.get("SYMBOL", ""))
        if not ticker:
            continue
        out[ticker] = ListedCompany(
            ticker=ticker,
            name=clean.get("NAME OF COMPANY") or ticker,
            market="india",
            exchange="NSE",
            isin=clean.get("ISIN NUMBER") or None,
        )
    return out


_FETCHERS = {"us": _fetch_us, "india": _fetch_india}


def index_for(market: str) -> dict[str, ListedCompany]:
    """The whole listed set for one market, from cache when it is fresh."""
    if market not in SUPPORTED:
        return {}
    with _lock:
        hit = _cache.get(market)
        if hit and (time.time() - hit[0]) < CACHE_TTL_SECONDS:
            return hit[1]
        cached = _read_cache(market)
        if cached is not None:
            _cache[market] = (time.time(), cached)
            return cached
        try:
            fetched = _FETCHERS[market]()
        except Exception as exc:
            # Never take the search down because an upstream list is
            # unreachable. The curated companies still resolve; the wider
            # universe is simply unavailable for now.
            logger.warning("ticker index fetch failed for %s: %s", market, exc)
            return {}
        _write_cache(market, fetched)
        _cache[market] = (time.time(), fetched)
        return fetched


def lookup(ticker: str) -> Optional[ListedCompany]:
    """Exact ticker lookup across the supported markets.

    India is checked first: an Indian listing is the one a user means when they
    type a bare NSE symbol, and a US ticker that collides with it is rarer than
    the reverse.
    """
    key = _normalise(ticker)
    if not key or len(key) > 12:
        return None
    for market in ("india", "us"):
        found = index_for(market).get(key)
        if found is not None:
            return found
    return None


def search(query: str, limit: int = 8) -> list["ListedCompany"]:
    """Ticker and company-name search over the listed universe.

    Four tiers, strictest first: the exact ticker, a ticker prefix, a company
    name whose word starts with the query, and finally a match inside a single
    word of the name. Used only to surface candidates the local store does not
    have.

    The name tiers are matched against the name's *words*, never against a
    squashed alphanumeric string. Stripping the spaces is what put LSB Industries
    above State Bank of India for the query "SBIN": squashed to
    LSBINDUSTRIESINC, the letters SBIN sit inside it straddling a word boundary,
    and a user typing a bank symbol got an unrelated chemicals company as the
    first row. A match that only exists because the spaces were removed is not a
    match.

    Ordering within a tier matters more than it looks. Choosing a row here starts
    a real download from a third party, so the row a user reaches for first
    should be the one they meant. For "TITAN" that gives the Indian ticker, then
    Titan Mining, then TITAN INTERNATIONAL, and Black Titan last, because the
    leading word is the one people type.
    """
    key = _normalise(query)
    if not key:
        return []
    exact: list[ListedCompany] = []
    ticker_prefix: list[tuple[tuple, ListedCompany]] = []
    name_word: list[tuple[tuple, ListedCompany]] = []
    name_contains: list[tuple[tuple, ListedCompany]] = []
    seen: set[tuple[str, str]] = set()

    for market in ("us", "india"):
        for ticker, company in index_for(market).items():
            marker = (ticker, market)
            if marker in seen:
                continue
            if ticker == key:
                seen.add(marker)
                exact.append(company)
                continue
            if ticker.startswith(key):
                seen.add(marker)
                # Shortest ticker first, so "TCS" beats "TCSINF" for "TCS".
                ticker_prefix.append(((len(ticker), ticker), company))
                continue
            words = _words(company.name)
            if not words:
                continue
            if words[0].startswith(key):
                # The name opens with the query, which is what "I remember the
                # company starting with Titan" means.
                seen.add(marker)
                name_word.append(((0, len(company.name), ticker), company))
            elif any(w.startswith(key) for w in words):
                seen.add(marker)
                name_word.append(((1, len(company.name), ticker), company))
            elif key in "".join(words):
                # Last resort, and only ever inside one word. Reachable, ranked
                # below everything that matched on a boundary.
                seen.add(marker)
                name_contains.append(((0, len(company.name), ticker), company))

    def rank(items: list[tuple[tuple, ListedCompany]]) -> list[ListedCompany]:
        return [c for _, c in sorted(items, key=lambda p: p[0])]

    return (exact + rank(ticker_prefix) + rank(name_word) + rank(name_contains))[:limit]


def is_probable_financial(name: str) -> bool:
    """Whether a company name alone suggests a bank, insurer or asset manager.

    **This is a heuristic, and it is known to have misses.** Read this before
    relying on it as a security property.

    The exchange index publishes a name and nothing else: no sector, no SIC code,
    nothing authoritative to classify on. Nothing in this repository classifies
    sector at run time either. ``sector_filter.is_financial_sector`` exists and
    is correct, but it takes a sector, an industry and a SIC code, and the only
    caller is a self-check, so no live company has ever been classified by it.
    The curated universe contains no financial rows at all: they were excluded by
    never being added, not by being recognised and rejected.

    Where a company *is* already in the store, ``is_financial`` on its record is
    authoritative and is honoured instead of this function. This is the fallback
    for the thousands of companies that exist only in the index.

    That leaves the name. Exchanges list companies under their legal names, so the
    legal name carries the business, and the industry words catch most of them. It
    does not catch the ones named after a person or a place, which is why
    ``_INSTITUTION_STEMS`` exists and why JPMorgan Chase is in it.

    The residual risk, stated plainly: a financial whose legal name contains
    neither an industry word nor a listed brand will be registered, will get a
    public URL, and will receive a valuation built from an unlevered free cash flow
    definition that does not apply to it. The audit will very likely pass it,
    because the audit checks that the arithmetic ties and not that the inputs
    describe the kind of business the model assumes.

    The fix for that is one field. EDGAR's submissions document carries ``sic`` and
    ``sicDescription`` for every filer, which is the authoritative answer, and the
    existing ``is_financial_sector`` already knows how to consume it. Reading it
    during ingestion would make this function unnecessary. Until then, treat a
    False here as "probably fine", never as "verified".

    The failure modes are deliberately asymmetric. A false positive means a bank
    is not discoverable, which costs a person one email. A false negative means
    the search offers a bank and the engine returns a confident number for it.
    The first is a much smaller mistake than the second.
    """
    lowered = f" {(name or '').lower().strip()} "
    if any(kw in lowered for kw in _FINANCIAL_NAME_HINTS):
        return True
    if any(stem in lowered for stem in _INSTITUTION_STEMS):
        return True
    # Whole words only, so "sbi" cannot match inside an unrelated word.
    return any(f" {abbr} " in lowered for abbr in _INSTITUTION_ABBREVIATIONS)


def discover(query: str, limit: int = 8) -> list["ListedCompany"]:
    """Listed companies matching a query that the local store does not hold.

    The local store is the source of truth for what Valence already models, so it
    is asked first and anything it returns is excluded here. That exclusion is
    what stops the two searches fighting: without it a company in both sets
    appears twice in the dropdown, once with a compiled model and once without,
    and the duplicate is indistinguishable to a user.

    Probable financials are dropped. This engine cannot model a bank, an insurer
    or a REIT, and offering one produces a number rather than an honest absence.
    """
    from backend.data.universe.store import search_universe_companies

    try:
        known = {
            c.ticker.upper()
            for c in search_universe_companies(query=query, limit=100)
        }
    except Exception as exc:  # a local store problem must not hide the universe
        logger.warning("discover: local store lookup failed: %s", exc)
        known = set()

    out: list[ListedCompany] = []
    for company in search(query, limit=limit * 3):
        if company.ticker.upper() in known:
            continue
        if is_probable_financial(company.name):
            continue
        out.append(company)
        if len(out) >= limit:
            break
    return out


def resolve_or_register(ticker: str):
    """The local company for a ticker, registering it from the index if new.

    Order matters. The store is asked first so an existing company keeps the
    identity it already has, including a curated sector and industry and a slug
    that other pages may already link to. Only a genuine miss falls through to
    the index, and the index can only ever return a company the exchange itself
    publishes, which is the property that makes ``/companies/resolve`` safe to
    widen: the allowlist is not a list someone typed, it is the exchange's own.

    Returns ``(company, created)`` where ``created`` says whether this call is
    what put the company in the store, so a caller can log a genuine first
    discovery separately from the millions of cache hits.
    """
    from backend.data.universe.models import UniverseCompany
    from backend.data.universe.slugs import build_company_id
    from backend.data.universe.store import get_universe_company, register_universe_company

    key = _normalise(ticker)
    if not key:
        return None, False

    listed = lookup(key)
    if listed is None:
        return None, False

    company_id = build_company_id(listed.ticker, listed.market)
    existing = get_universe_company(company_id)
    if existing is not None:
        if existing.is_financial:
            # The curated store already classified this one, and classified it as
            # a financial, which is why it carries no slug: it was admitted to the
            # universe and held back from the model engine on purpose. That flag
            # is authoritative, so it outranks the name heuristic entirely and
            # the request is refused here rather than being handed a company the
            # builder cannot service.
            #
            # This branch is the reason the earlier version of this function was
            # wrong. It returned any existing record unconditionally, on the
            # reasoning that a curated company should keep working. But the
            # curated financial *is* the case that must not work, and it is
            # reached here because a slugless financial row exists in the store
            # and therefore misses the by-slug lookup that normally filters
            # financial rows out upstream.
            return None, False
        return existing, False

    if is_probable_financial(listed.name):
        # Refused rather than registered. The store's own resolver refuses
        # financial rows for the same reason, so registering one would create a
        # company that exists in the database and is unreachable through the
        # public route, which is a worse state than never having found it.
        logger.info(
            "refused %s: %r reads as a financial, which this engine does not model",
            listed.ticker, listed.name,
        )
        return None, False

    record = UniverseCompany(
        company_id=company_id,
        ticker=listed.ticker,
        name=listed.name,
        market=listed.market,
        exchange=listed.exchange,
        # Left blank rather than guessed. The index knows a company exists and
        # what it trades as; it does not know what it does, and a plausible
        # sector string is worse than an empty one because nothing downstream
        # can tell it was invented.
        sector="",
        industry="",
        is_financial=False,
        # A record, not an ingestion. Nothing has been fetched for this company
        # yet, and the status is what tells the UI that.
        onboarding_status="not_yet_attempted",
        onboarding_notes=f"Discovered in the {listed.exchange} listed universe.",
        cik=listed.cik,
    )
    created = register_universe_company(record)
    if created is None:
        return None, False
    logger.info("registered %s from the listed universe", created.company_id)
    return created, True
