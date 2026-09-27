"""Public URL slugs and safe internal company identifiers.

Two namespaces, sanitized differently, both derived from the raw ticker.

``slug`` is the public URL segment. It preserves the real ticker so a link reads
honestly (``/stock/BRK.B``), and is the only thing a visitor ever sees.

``company_id`` is internal and must satisfy COMPANY_ID_PATTERN exactly. Real
tickers contain characters that pattern rejects: ``BRK.B``, ``BF-B``,
``BAJAJ-AUTO``, ``M&M``. Those names were previously unreachable because the
acquisition step wrote an id the API then refused. Sanitizing at the boundary
fixes the mapping without widening the pattern, so what is allowed to reach live
ingestion stays exactly as narrow as it was.

Sanitizing is lossy, so ``BRK.B`` and ``BRK-B`` both want ``brk_b_us``. Every
collision gets a deterministic suffix from the source's own unique key rather
than silently overwriting a different company.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

# Mirrors backend.api.routes.COMPANY_ID_PATTERN. Duplicated deliberately: this
# module is imported by acquisition code that must not pull in the API layer.
COMPANY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,62}[a-z0-9]$")

SLUG_MAX = 32
COMPANY_ID_MAX = 63

_SLUG_STRIP = re.compile(r"[^A-Z0-9.\-]+")
_SLUG_RUNS = re.compile(r"[.\-]{2,}")

# Exchanges that identify a real listing venue. EDGAR is a filing system, not a
# venue, and every acquired US row carries it, so it can never separate two
# companies that share a ticker.
REAL_EXCHANGES = {"NSE", "BSE", "NYSE", "NASDAQ", "NYQ", "AMEX", "PCX", "IEX"}

# Ticker -> the company_id that owns the bare slug when a ticker is shared.
# Explicit beats inferred: parsing "Infosys Limited (NYSE ADR)" to work out that
# the parenthesised one is the depositary receipt is exactly the kind of
# cleverness that silently makes an ADR the default landing page for /INFY.
LISTING_PRIMARY: Dict[str, str] = {
    "INFY": "infy_infy",
}


def sanitize_slug(raw: str) -> str:
    """Normalize a ticker into a URL-safe uppercase slug fragment."""
    s = (raw or "").strip().upper()
    s = _SLUG_STRIP.sub("-", s)
    s = _SLUG_RUNS.sub("-", s)
    s = s.strip("-.")
    if not s:
        return ""
    if not s[0].isalnum():
        s = s.lstrip("-.")
    return s[:SLUG_MAX].strip("-.")


def sanitize_company_id(raw: str) -> str:
    """Normalize a ticker into a company_id that satisfies COMPANY_ID_RE.

    Collapses runs of underscores, strips leading and trailing ones, and
    truncates to the pattern's ceiling. The result is re-checked against the
    pattern because truncation can leave a one-character string, which the
    ``{1,62}`` middle quantifier rejects.
    """
    s = (raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_{2,}", "_", s).strip("_")
    if not s:
        return ""
    s = s[:COMPANY_ID_MAX].strip("_")
    # Guarantee the middle run stays at least two characters.
    while len(s) < 3:
        s = f"{s}x"
    if not COMPANY_ID_RE.match(s):
        return ""
    return s


def build_company_id(ticker: str, market: str) -> str:
    """Build the conventional ``{ticker}_{market}`` id, sanitized.

    Preserves the existing convention (``nvda_us``, ``lt_lt``, ``infy_infy``)
    so every id already in the database keeps working.
    """
    market_suffix = "us" if market == "us" else (ticker or "").strip().lower()[:12]
    return sanitize_company_id(f"{ticker}_{market_suffix}")


def _suffix_for(company, taken: set[str], base: str) -> str:
    """Find a unique suffix for a non-primary member of a shared-ticker group."""
    exchange = (getattr(company, "exchange", "") or "").upper()
    ticker = (getattr(company, "ticker", "") or "").upper()

    if exchange in REAL_EXCHANGES:
        candidate = f"{ticker}-{exchange}"
        if candidate not in taken:
            return candidate

    cik = getattr(company, "cik", None)
    if cik:
        digits = re.sub(r"\D", "", str(cik))
        if digits:
            candidate = f"{ticker}-{digits[-7:]}"
            if candidate not in taken:
                return candidate

    n = 2
    while f"{ticker}-{n}" in taken:
        n += 1
    return f"{ticker}-{n}"


def resolve_unique_slug(
    ticker: str, exchange: str, cik: Optional[str], taken: set
) -> str:
    """The slug one listing of `ticker` should get, given what is already taken.

    Shared by ``assign_slugs`` and the search preview. They have to agree: the
    preview is the URL a user clicks, and a preview that disagrees with the
    register sends them to a company that is not the one they picked.

    Preference order is the same as the existing sibling rule: the bare ticker
    when it is free, then ``TICKER-EXCHANGE`` for a real exchange, then
    ``TICKER-CIK7`` for two EDGAR filers that cannot be told apart by exchange,
    then a numeric suffix as the last resort.
    """
    base = sanitize_slug(ticker)
    if not base:
        return ""
    if base.upper() not in taken:
        return base

    ex = (exchange or "").upper()
    if ex in REAL_EXCHANGES:
        candidate = f"{base}-{ex}"
        if candidate.upper() not in taken:
            return candidate

    if cik:
        digits = re.sub(r"\D", "", str(cik))
        if digits:
            candidate = f"{base}-{digits[-7:]}"
            if candidate.upper() not in taken:
                return candidate

    n = 2
    while f"{base}-{n}".upper() in taken:
        n += 1
    return f"{base}-{n}"


def assign_slugs(companies: Iterable) -> Dict[str, str]:
    """Map company_id -> slug for a set of universe companies.

    Three rules, applied in order:

    1. Ticker unique across the group: the bare uppercase ticker.
    2. Ticker shared, members carry distinct real exchanges: the bare ticker
       goes to the primary, siblings get ``TICKER-EXCHANGE``.
    3. Ticker shared, members are EDGAR rows: the bare ticker goes to the
       primary, siblings get ``TICKER-CIK7``, because every acquired US row
       carries ``exchange="SEC_EDGAR"`` and exchange cannot separate them.

    The primary is ``LISTING_PRIMARY`` when listed, otherwise the lowest
    company_id. Lowest-ascending is a total order, so the outcome is
    deterministic even when the override is missing.
    """
    by_ticker: Dict[str, List] = {}
    for c in companies:
        if getattr(c, "is_financial", False):
            continue
        ticker = (getattr(c, "ticker", "") or "").upper()
        if not ticker:
            continue
        by_ticker.setdefault(ticker, []).append(c)

    result: Dict[str, str] = {}
    for ticker, group in by_ticker.items():
        group.sort(key=lambda c: getattr(c, "company_id", ""))
        if len(group) == 1:
            slug = sanitize_slug(ticker)
            if slug:
                result[group[0].company_id] = slug
            continue

        override = LISTING_PRIMARY.get(ticker)
        primary = next((c for c in group if c.company_id == override), group[0])
        base = sanitize_slug(ticker)
        if not base:
            continue
        taken = {base}
        result[primary.company_id] = base
        for c in group:
            if c.company_id == primary.company_id:
                continue
            slug = _suffix_for(c, taken, base)
            taken.add(slug)
            result[c.company_id] = slug

    return result


def dedupe_company_ids(companies: List) -> Tuple[List, int]:
    """Drop companies whose sanitized company_id collides with an earlier one.

    The loser is given a deterministic suffix rather than being discarded.
    Acquisition previously deduplicated by keeping the first row, which meant a
    sanitization collision would silently delete a real company from the
    universe. Returns the surviving list and the number that had to be renamed.
    """
    seen: Dict[str, object] = {}
    out: List = []
    renamed = 0
    for c in companies:
        cid = getattr(c, "company_id", "")
        if cid not in seen:
            seen[cid] = c
            out.append(c)
            continue
        ticker = (getattr(c, "ticker", "") or "").upper()
        cik = getattr(c, "cik", None)
        digits = re.sub(r"\D", "", str(cik)) if cik else ""
        base = f"{cid}_{digits[-4:]}" if digits else f"{cid}_dup"
        candidate = sanitize_company_id(base) or f"{cid}_dup"
        n = 2
        while candidate in seen:
            candidate = sanitize_company_id(f"{cid}_{digits[-4:]}_{n}" if digits else f"{cid}_dup{n}")
            n += 1
        try:
            c.company_id = candidate
        except Exception:
            continue
        seen[candidate] = c
        out.append(c)
        renamed += 1
    return out, renamed


def extract_cik(notes: Optional[str]) -> Optional[str]:
    """Pull the CIK back out of a legacy onboarding_notes string."""
    if not notes:
        return None
    m = re.search(r"CIK:\s*(\d+)", notes, re.IGNORECASE)
    return m.group(1) if m else None
