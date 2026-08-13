from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

MarketType = Literal["india", "us"]

MODEL_SPEC_VERSION = "1.0.0"


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
    shares_outstanding=405.76,
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
}


def get_metadata_for_company(company_id: str) -> ModelMetadata:
    """Return ModelMetadata for company_id.

    Registered companies return their canonical metadata. Unregistered companies
    are derived from the company_id slug: the first token becomes the ticker and
    a ``_us`` suffix selects USD/millions US-market defaults (India otherwise).
    """
    if company_id in COMPANY_METADATA_REGISTRY:
        return COMPANY_METADATA_REGISTRY[company_id]
    parts = company_id.split("_")
    ticker = parts[0].upper()
    if parts[-1] == "us":
        return ModelMetadata(
            company_id=company_id,
            ticker=ticker,
            name=f"{ticker} Inc.",
            market="us",
            currency="USD",
            units="millions",
            fiscal_year_end="December 31",
        )
    return ModelMetadata(
        company_id=company_id,
        ticker=ticker,
        name=f"{ticker} Limited",
        market="india",
        currency="INR",
        units="crores",
        fiscal_year_end="March 31",
    )
