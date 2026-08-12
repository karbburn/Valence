from __future__ import annotations

from datetime import date, datetime
from typing import Literal

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
)
