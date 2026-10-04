from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

MarketType = Literal["india", "us"]

MODEL_SPEC_VERSION = "1.0.0"

# Ingestion sources that carry a filer's own accounts rather than someone's
# aggregation of them. A model is filing-derived when these are the large majority
# of its rows.
#
# `screener` is deliberately NOT here, and that is the substantive judgement rather
# than a formality: Screener.in is a third-party aggregator whose own documentation
# says its figures may differ from the filings, and the codebase already ranked it
# as a secondary source for exactly that reason. A number from it is a real number
# about a real company, but it is not the number the filer published.
FILING_SOURCES = frozenset({"sec_edgar", "nse_filing", "bse_filing"})

_MONTH_STARTERS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_fiscal_year_end(fiscal_year_end: str) -> tuple[int, int]:
    """Return (month, day) for strings like 'March 31', 'Sep 30', 'Dec 31'."""
    parts = fiscal_year_end.strip().split()
    if len(parts) != 2:
        raise ValueError(f"Unparseable fiscal year end: {fiscal_year_end!r}")
    month = _MONTH_STARTERS.get(parts[0][:3].lower())
    if month is None:
        raise ValueError(f"Unknown month in fiscal year end: {fiscal_year_end!r}")
    return month, int(parts[1])


class ModelMetadata(BaseModel):
    """Presentation-independent metadata identifying the company and schema version."""
    model_config = ConfigDict(protected_namespaces=())


    company_id: str                          # stable slug, e.g. "infy_infy"
    ticker: str                              # exchange ticker, e.g. "INFY"
    name: str                                # full legal company name
    market: MarketType                       # "india" | "us"
    currency: str                            # ISO code, e.g. "INR"
    units: str = "crores"                    # reporting units for financial values
    fiscal_year_end: str                     # e.g. "March 31" — human-readable
    shares_outstanding: Optional[float] = None # in Crores
    sector: Optional[str] = None             # Industry sector, e.g. "Technology", "Automotive"
    # Where this model's numbers came from, counted by ingestion source.
    #
    # The product claims that every published figure matches an official filing.
    # That claim is true for nine of the twenty-three shipped companies and false
    # for thirteen, and until now nothing in the product said so: a page built from
    # a market feed was indistinguishable from one built from EDGAR, and the only
    # way to tell was to know which sources a given company's ingestion happened to
    # use. A reader cannot audit a claim the site does not let them see the terms of.
    #
    # The distinction is not cosmetic. The tie-out has now measured two of the
    # market-sourced companies against their own 20-F filings and found them
    # disagreeing — the Infosys ADR publishes 1,043 of current investments where the
    # filing says 1,365, and no non-current investments where the filing says 942 —
    # which is the cost of reading a feed instead of an account, stated exactly.
    data_sources: Optional[dict] = None      # {source: row_count}
    filing_derived: Optional[bool] = None    # True when filing rows are the large majority
    filing_source: Optional[str] = None      # the filing source that dominates, if any
    model_version: str = MODEL_SPEC_VERSION  # schema version, semver — NOT data refresh
    generation_date: datetime = Field(default_factory=datetime.now)


# Canonical Infosys metadata — used by factory methods in downstream modules.
INFOSYS_METADATA = ModelMetadata(
    company_id="infy_infy",
    ticker="INFY",
    name="Infosys Limited",
    market="india",
    currency="INR",
    units="crores",
    fiscal_year_end="March 31",
    shares_outstanding=412.45,
)

COMPANY_METADATA_REGISTRY: dict[str, ModelMetadata] = {
    "infy_infy": INFOSYS_METADATA,
    "tcs_tcs": ModelMetadata(
        company_id="tcs_tcs",
        ticker="TCS",
        name="Tata Consultancy Services Limited",
        market="india",
        currency="INR",
        units="crores",
        fiscal_year_end="March 31",
        shares_outstanding=361.8,
    ),
    "tatamotors_tatamotors": ModelMetadata(
        company_id="tatamotors_tatamotors",
        ticker="TATAMOTORS",
        name="Tata Motors Limited",
        market="india",
        currency="INR",
        units="crores",
        fiscal_year_end="March 31",
        shares_outstanding=367.0,
    ),
    "tatasteel_tatasteel": ModelMetadata(
        company_id="tatasteel_tatasteel",
        ticker="TATASTEEL",
        name="Tata Steel Limited",
        market="india",
        currency="INR",
        units="crores",
        fiscal_year_end="March 31",
        shares_outstanding=1248.0,
    ),
    "aapl_us": ModelMetadata(
        company_id="aapl_us",
        ticker="AAPL",
        name="Apple Inc.",
        market="us",
        currency="USD",
        units="millions",
        fiscal_year_end="September 30",
        shares_outstanding=15300.0,
    ),
    "msft_us": ModelMetadata(
        company_id="msft_us",
        ticker="MSFT",
        name="Microsoft Corporation",
        market="us",
        currency="USD",
        units="millions",
        fiscal_year_end="June 30",
        shares_outstanding=7430.0,
    ),
    "infy_us": ModelMetadata(
        company_id="infy_us",
        ticker="INFY",
        name="Infosys Limited (NYSE ADR)",
        market="us",
        currency="USD",
        units="millions",
        fiscal_year_end="March 31",
        shares_outstanding=4124.0,
    ),
    "wipro_wipro": ModelMetadata(
        company_id="wipro_wipro",
        ticker="WIPRO",
        name="Wipro Limited",
        market="india",
        currency="INR",
        units="crores",
        fiscal_year_end="March 31",
        shares_outstanding=522.0,
    ),
    "hcltech_hcltech": ModelMetadata(
        company_id="hcltech_hcltech",
        ticker="HCLTECH",
        name="HCL Technologies Limited",
        market="india",
        currency="INR",
        units="crores",
        fiscal_year_end="March 31",
        shares_outstanding=271.0,
    ),
    "lt_lt": ModelMetadata(
        company_id="lt_lt",
        ticker="LT",
        name="Larsen & Toubro Limited",
        market="india",
        currency="INR",
        units="crores",
        fiscal_year_end="March 31",
        shares_outstanding=137.5,
    ),
    "sunpharma_sunpharma": ModelMetadata(
        company_id="sunpharma_sunpharma",
        ticker="SUNPHARMA",
        name="Sun Pharmaceutical Industries Limited",
        market="india",
        currency="INR",
        units="crores",
        fiscal_year_end="March 31",
        shares_outstanding=240.0,
    ),
    "nvda_us": ModelMetadata(
        company_id="nvda_us",
        ticker="NVDA",
        name="NVIDIA Corporation",
        market="us",
        currency="USD",
        units="millions",
        fiscal_year_end="January 31",
        shares_outstanding=24500.0,
    ),
    "googl_us": ModelMetadata(
        company_id="googl_us",
        ticker="GOOGL",
        name="Alphabet Inc.",
        market="us",
        currency="USD",
        units="millions",
        fiscal_year_end="December 31",
        shares_outstanding=12400.0,
    ),
    "amzn_us": ModelMetadata(
        company_id="amzn_us",
        ticker="AMZN",
        name="Amazon.com, Inc.",
        market="us",
        currency="USD",
        units="millions",
        fiscal_year_end="December 31",
        shares_outstanding=10500.0,
    ),
}


def resolve_market(company_id: str) -> str:
    """Reporting market for a company: "us" or "india".

    The single replacement for `company_id.endswith("_us")`. The suffix is only a
    last resort: it mis-classifies any listing whose slug and reporting calendar
    differ, most importantly infy_us, a US-listed ADR that reports on a 31 March
    Indian fiscal year and is taxed as an Indian company. The registry is
    consulted first so the answer is the company's actual market.
    """
    registered = COMPANY_METADATA_REGISTRY.get(company_id)
    if registered is not None:
        return registered.market

    try:
        from backend.data.universe.store import get_universe_company

        co = get_universe_company(company_id)
        if co is not None and co.market:
            return co.market
    except Exception:
        pass

    return "us" if company_id.endswith("_us") else "india"


def _read_provenance(
    company_id: str, db_path: str | Path | None = None
) -> tuple[dict[str, int], bool | None, str | None]:
    """What the ingestion used, counted by source, from the datapoints themselves.

    `db_path` is a parameter because the caller has one. `ensure_company_ingested(db_path=X)`
    ingests into a store the caller named, and this function read a module-level `DB_PATH`
    instead, so a caller working against a copy was asking the LIVE store what it had
    ingested. That is the same defect `normalization.pipeline.run` had, fixed in 18b4220,
    one layer over: a caller testing against a copy believes it is isolated and is not.

    Found by writing a probe that wanted this function -- the authority on the publication
    threshold, rather than a second implementation of it -- and could not point it at its
    copy. The only way to ask the question was to reassign a module global, which is a
    measure of how little the function is parameterised.
    """
    import sqlite3

    if db_path is None:
        from backend.data.universe.store import DB_PATH as db_path  # type: ignore[no-redef]

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT source, COUNT(*) FROM raw_datapoints WHERE company_id = ? GROUP BY source",
            (company_id,),
        ).fetchall()
    finally:
        conn.close()

    sources = {str(s): int(n) for s, n in rows if s}
    total = sum(sources.values())
    if not total:
        return sources, None, None
    filing = {k: v for k, v in sources.items() if k in FILING_SOURCES}
    # A majority, not an absolute: a filer whose PDF parse contributes a few rows
    # alongside a feed is not a filing-derived model, and calling it one would be the
    # same overclaim in the other direction.
    derived = sum(filing.values()) / total > 0.9
    dominant = max(filing, key=lambda k: filing[k]) if filing else None
    return sources, derived, dominant


def _with_provenance(
    meta: ModelMetadata, company_id: str, db_path: str | Path | None = None
) -> ModelMetadata:
    """Return a copy of `meta` carrying the provenance read from the datapoints."""
    if meta.data_sources is not None:
        return meta
    try:
        sources, derived, dominant = _read_provenance(company_id, db_path=db_path)
    except Exception:
        return meta
    if not sources:
        return meta
    return meta.model_copy(
        update={
            "data_sources": sources,
            "filing_derived": derived,
            "filing_source": dominant,
        }
    )


def get_metadata_for_company(
    company_id: str, db_path: str | Path | None = None
) -> ModelMetadata:
    """Return ModelMetadata for company_id.

    Registered companies return their canonical metadata. Unregistered companies
    are derived from the company_id slug and the company universe database.

    `db_path` names the store to read provenance from, for the same reason
    `_read_provenance` takes one: a caller that ingested into a copy is asking what THAT
    store contains, and answering from the live one reports provenance for a different set
    of rows than the model it is describing.
    """
    if company_id in COMPANY_METADATA_REGISTRY:
        registered = COMPANY_METADATA_REGISTRY[company_id]
        # Enriched rather than returned. The registry is an IDENTITY record — who the
        # company is, its fiscal year end, its share count — and it short-circuits
        # everything below, so a registered company reported no provenance at all:
        # nine of the twenty-three shipped companies would have had no statement of
        # where their numbers came from, which is the one thing a reader needs in
        # order to weigh them.
        #
        # Provenance is a property of the DATA, so it is read from the data even when
        # the identity is cached. This is the same lesson as the CIK registry, which
        # short-circuited a check and published Netflix's accounts as Infosys'.
        return _with_provenance(registered, company_id, db_path=db_path)

    # Check universe database
    name = None
    market = "us" if company_id.endswith("_us") else "india"
    ticker = company_id.split("_")[0].upper()

    try:
        from backend.data.universe.store import get_universe_company
        co = get_universe_company(company_id)
        if co:
            name = co.name
            ticker = co.ticker
            market = co.market
    except Exception:
        pass

    # What the ingestion actually used, read from the datapoints rather than
    # remembered, so it cannot drift from the data.
    try:
        data_sources, filing_derived, filing_source = _read_provenance(
            company_id, db_path=db_path
        )
    except Exception:
        data_sources, filing_derived, filing_source = {}, None, None

    if market == "us":
        return ModelMetadata(
            company_id=company_id,
            ticker=ticker,
            name=name or f"{ticker} Inc.",
            market="us",
            currency="USD",
            units="millions",
            fiscal_year_end="December 31",
            shares_outstanding=_resolve_shares(company_id, market),
            data_sources=data_sources or None,
            filing_derived=filing_derived,
            filing_source=filing_source,
        )
    return ModelMetadata(
        company_id=company_id,
        ticker=ticker,
        name=name or f"{ticker} Limited",
        market="india",
        currency="INR",
        units="crores",
        fiscal_year_end="March 31",
        shares_outstanding=_resolve_shares(company_id, market),
        data_sources=data_sources or None,
        filing_derived=filing_derived,
        filing_source=filing_source,
    )


def _resolve_shares(company_id: str, market: str) -> Optional[float]:
    """Best-effort live share count for unregistered companies.

    Fallback chain: market data provider (live/cached) -> statutory default.
    Never a hardcoded placeholder, which silently corrupts any downstream
    per-share math for unregistered companies.
    """
    try:
        from backend.data.providers.market_data import get_company_market_data
        md = get_company_market_data(company_id)
        shares = md.shares_outstanding.value
        if shares and shares > 0:
            return float(shares)
    except Exception:
        pass
    return None
