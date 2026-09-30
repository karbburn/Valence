from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# "estimated" is a raw datapoint status, and the raw layer already had it: a reader
    # that knows a figure is not filed needs somewhere to say so. It was missing here,
    # which is why the mapper collapsed every non-"reported_adjusted" status into
    # "reported" -- the type did not permit carrying the truth through.
    #
    # The collapse was not a style choice, it was the only thing the type allowed. That
    # is worth remembering the next time a status looks redundant: it is the schema
    # deciding which distinctions are representable.
CanonicalStatus = Literal[
    "reported", "reported_adjusted", "derived", "analyst_adjusted", "estimated",
]
StatementType = Literal["is", "bs", "cf", "meta"]


class CanonicalDatapoint(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    company_id: str
    canonical_key: str
    metric_raw: str
    period_label: str
    period_end_date: date
    value: float
    currency: str
    units: str
    status: CanonicalStatus
    source_datapoint_ids: list[str] = Field(default_factory=list)
    derivation_rule: Optional[str] = None
    update_date: datetime = Field(default_factory=datetime.now)


class TaxonomyMapping(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    company_id: str
    canonical_key: str
    metric_raw: str
    statement: StatementType
    source: str
    human_confirmed: bool = True
    update_date: datetime = Field(default_factory=datetime.now)
