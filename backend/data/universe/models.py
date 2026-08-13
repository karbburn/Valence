from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

MarketType = Literal["india", "us"]
OnboardingStatus = Literal["onboarded", "partial", "not_yet_attempted", "failed"]
MappingConfidenceLevel = Literal["high", "medium", "low"]


class UniverseCompany(BaseModel):
    """Master record for a company in the target universe across markets."""
    company_id: str
    ticker: str
    name: str
    market: MarketType
    exchange: str
    sector: str
    industry: str
    is_financial: bool = False
    onboarding_status: OnboardingStatus = "not_yet_attempted"
    onboarding_notes: Optional[str] = None
    last_updated: datetime = Field(default_factory=datetime.now)


class MappingConfidenceResult(BaseModel):
    """Result of confidence-scored taxonomy mapping suggestion."""
    metric_raw: str
    canonical_key: Optional[str] = None
    statement: Optional[str] = None
    confidence_score: float  # 0.0 to 1.0
    level: MappingConfidenceLevel
    reason: str
