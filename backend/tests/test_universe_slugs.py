"""Public slug and company_id sanitization.

Two namespaces, sanitized differently. slug is the public URL segment and keeps
the real ticker so a link reads honestly. company_id is internal and must satisfy
COMPANY_ID_PATTERN, which rejects the punctuation real tickers actually contain.
"""

from __future__ import annotations

import pytest

from backend.api.routes import COMPANY_ID_PATTERN
from backend.data.universe.models import UniverseCompany
from backend.data.universe.slugs import (
    assign_slugs,
    build_company_id,
    dedupe_company_ids,
    extract_cik,
    sanitize_company_id,
    sanitize_slug,
)


def _c(company_id, ticker, exchange="NASDAQ", market="us", is_financial=False, cik=None):
    return UniverseCompany(
        company_id=company_id,
        ticker=ticker,
        name=f"{ticker} Inc.",
        market=market,
        exchange=exchange,
        sector="Technology",
        industry="Software",
        is_financial=is_financial,
        cik=cik,
    )


# --------------------------------------------------------------------------- #
# sanitize_company_id
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("NVDA", "nvda"),
        ("BRK.B", "brk_b"),
        ("BF-B", "bf_b"),
        ("BAJAJ-AUTO", "bajaj_auto"),
        ("M&M", "m_m"),
        ("L&T", "l_t"),
        ("  nvda  ", "nvda"),
        ("a__b", "a_b"),
        ("_lead", "lead"),
        ("trail_", "trail"),
    ],
)
def test_sanitize_company_id(raw, expected):
    assert sanitize_company_id(raw) == expected


@pytest.mark.parametrize("ticker", ["BRK.B", "BF-B", "BAJAJ-AUTO", "M&M", "L&T", "NVDA", "A"])
def test_sanitize_company_id_always_satisfies_the_api_pattern(ticker):
    """Every sanitized id must pass the pattern the API enforces.

    This is the whole point of sanitizing at the boundary: a ticker with
    punctuation used to produce a company_id the model endpoint rejected, so
    the company was unreachable even though the engine could value it.
    """
    result = sanitize_company_id(ticker)
    assert result, f"{ticker!r} sanitized to nothing"
    assert COMPANY_ID_PATTERN.match(result), f"{ticker!r} -> {result!r} fails COMPANY_ID_PATTERN"


def test_sanitize_company_id_truncates_without_ending_on_underscore():
    long_ticker = "A" * 80
    result = sanitize_company_id(long_ticker)
    assert len(result) <= 63
    assert COMPANY_ID_PATTERN.match(result)
    assert not result.endswith("_")


def test_build_company_id_preserves_the_existing_convention():
    """Existing ids in the database must keep working after sanitization."""
    assert build_company_id("NVDA", "us") == "nvda_us"
    assert build_company_id("LT", "india") == "lt_lt"
    assert build_company_id("INFY", "us") == "infy_us"
    assert build_company_id("TATAMOTORS", "india") == "tatamotors_tatamotors"
    assert build_company_id("BAJAJ-AUTO", "india") == "bajaj_auto_bajaj_auto"


# --------------------------------------------------------------------------- #
# sanitize_slug
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("NVDA", "NVDA"),
        ("BRK.B", "BRK.B"),
        ("BAJAJ-AUTO", "BAJAJ-AUTO"),
        ("INFY", "INFY"),
        ("nvda", "NVDA"),
        ("in fy", "IN-FY"),
        ("...", ""),
    ],
)
def test_sanitize_slug(raw, expected):
    assert sanitize_slug(raw) == expected


def test_sanitize_slug_never_exceeds_the_length_ceiling():
    assert len(sanitize_slug("A" * 100)) <= 32


# --------------------------------------------------------------------------- #
# assign_slugs
# --------------------------------------------------------------------------- #

def test_unambiguous_ticker_gets_the_bare_slug():
    mapping = assign_slugs([_c("nvda_us", "NVDA")])
    assert mapping == {"nvda_us": "NVDA"}


def test_shared_ticker_with_real_exchanges_uses_the_exchange_suffix():
    """INFY exists twice. The bare slug must go to the NSE listing, not the ADR.

    Determined by an explicit override. Inferring it from the name string is how
    an ADR silently becomes the default landing page for /INFY.
    """
    companies = [
        _c("infy_infy", "INFY", exchange="NSE", market="india"),
        _c("infy_us", "INFY", exchange="NYSE", market="us"),
    ]
    mapping = assign_slugs(companies)
    assert mapping["infy_infy"] == "INFY"
    assert mapping["infy_us"] == "INFY-NYSE"
    assert len(set(mapping.values())) == 2


def test_shared_ticker_across_edgar_rows_disambiguates_on_cik():
    """Every acquired EDGAR row carries exchange="SEC_EDGAR".

    Exchange therefore cannot separate two filers sharing a ticker, and a
    TICKER-EXCHANGE rule would emit the same slug twice. CIK is the unique key.
    """
    companies = [
        _c("aaa_us", "ABCD", exchange="SEC_EDGAR", cik="1234567"),
        _c("bbb_us", "ABCD", exchange="SEC_EDGAR", cik="7654321"),
    ]
    mapping = assign_slugs(companies)
    assert mapping == {"aaa_us": "ABCD", "bbb_us": "ABCD-7654321"}
    assert len(set(mapping.values())) == 2, f"slugs collided: {mapping}"


def test_edgar_collision_picks_primary_by_company_id_order():
    """The primary is the lowest company_id when no override is listed."""
    companies = [
        _c("zzz_us", "WXYZ", exchange="SEC_EDGAR", cik="1111111"),
        _c("aaa_us", "WXYZ", exchange="SEC_EDGAR", cik="2222222"),
    ]
    mapping = assign_slugs(companies)
    assert mapping["aaa_us"] == "WXYZ"
    assert mapping["zzz_us"] == "WXYZ-1111111"


def test_edgar_collision_falls_back_when_cik_is_missing():
    companies = [
        _c("abcd_us", "ABCD", exchange="SEC_EDGAR"),
        _c("abcd2_us", "ABCD", exchange="SEC_EDGAR"),
    ]
    mapping = assign_slugs(companies)
    assert len(set(mapping.values())) == 2, f"slugs collided: {mapping}"


def test_financial_sector_companies_never_receive_a_slug():
    companies = [
        _c("jpm_us", "JPM", is_financial=True),
        _c("aapl_us", "AAPL"),
    ]
    mapping = assign_slugs(companies)
    assert "jpm_us" not in mapping
    assert mapping == {"aapl_us": "AAPL"}


def test_every_slug_is_unique_across_a_mixed_universe():
    companies = [
        _c("infy_infy", "INFY", exchange="NSE", market="india"),
        _c("infy_us", "INFY", exchange="NYSE", market="us"),
        _c("nvda_us", "NVDA"),
        _c("aapl_us", "AAPL"),
        _c("lt_lt", "LT", exchange="NSE", market="india"),
        _c("googl_us", "GOOGL"),
        _c("jpm_us", "JPM", is_financial=True),
    ]
    mapping = assign_slugs(companies)
    values = list(mapping.values())
    assert len(values) == len(set(values)), f"duplicate slugs: {mapping}"


def test_slug_assignment_is_deterministic_regardless_of_input_order():
    companies = [
        _c("infy_us", "INFY", exchange="NYSE", market="us"),
        _c("infy_infy", "INFY", exchange="NSE", market="india"),
    ]
    assert assign_slugs(companies) == assign_slugs(list(reversed(companies)))


# --------------------------------------------------------------------------- #
# dedupe_company_ids
# --------------------------------------------------------------------------- #

def test_sanitization_collision_renames_rather_than_discarding():
    """BRK.B and BRK-B both sanitize to brk_b.

    Acquisition previously deduplicated by keeping the first row, which silently
    deleted a real company from the universe. The loser must survive under a
    distinct id.
    """
    companies = [
        _c("brk_b_us", "BRK.B", cik="1111"),
        _c("brk_b_us", "BRK-B", cik="2222"),
    ]
    result, renamed = dedupe_company_ids(companies)
    assert len(result) == 2, "a company was discarded"
    assert renamed == 1
    ids = [c.company_id for c in result]
    assert len(set(ids)) == 2, f"ids still collide: {ids}"
    for cid in ids:
        assert COMPANY_ID_PATTERN.match(cid), f"{cid!r} fails COMPANY_ID_PATTERN"


def test_dedupe_is_a_no_op_when_ids_are_already_distinct():
    companies = [_c("nvda_us", "NVDA"), _c("aapl_us", "AAPL")]
    result, renamed = dedupe_company_ids(companies)
    assert renamed == 0
    assert [c.company_id for c in result] == ["nvda_us", "aapl_us"]


# --------------------------------------------------------------------------- #
# extract_cik
# --------------------------------------------------------------------------- #

def test_extract_cik_reads_the_legacy_notes_format():
    assert extract_cik("Acquired via SEC EDGAR (CIK: 1046179) - Non-Financial Filer") == "1046179"
    assert extract_cik("no cik here") is None
    assert extract_cik(None) is None
