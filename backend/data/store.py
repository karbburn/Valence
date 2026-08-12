from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from backend.normalization.taxonomy.models import CanonicalDatapoint, TaxonomyMapping

Source = Literal["screener", "bse_filing", "nse_filing"]
Status = Literal["reported", "reported_adjusted", "derived"]


class RawDatapoint(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    company_id: str
    metric_raw: str
    period_label: str
    period_end_date: date
    value: float
    currency: str
    units: str
    source: Source
    source_location: str
    status: Status
    update_date: datetime = datetime.now()
    superseded_by_id: Optional[str] = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_datapoints (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    metric_raw TEXT NOT NULL,
    period_label TEXT NOT NULL,
    period_end_date TEXT NOT NULL,
    value REAL NOT NULL,
    currency TEXT NOT NULL,
    units TEXT NOT NULL,
    source TEXT NOT NULL,
    source_location TEXT NOT NULL,
    status TEXT NOT NULL,
    update_date TEXT NOT NULL,
    superseded_by_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_raw_company ON raw_datapoints(company_id);
CREATE INDEX IF NOT EXISTS idx_raw_lookup ON raw_datapoints(company_id, period_label, source);

CREATE TABLE IF NOT EXISTS canonical_datapoints (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    metric_raw TEXT NOT NULL,
    period_label TEXT NOT NULL,
    period_end_date TEXT NOT NULL,
    value REAL NOT NULL,
    currency TEXT NOT NULL,
    units TEXT NOT NULL,
    status TEXT NOT NULL,
    source_datapoint_ids TEXT NOT NULL,
    derivation_rule TEXT,
    update_date TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_canon_company ON canonical_datapoints(company_id);
CREATE INDEX IF NOT EXISTS idx_canon_lookup ON canonical_datapoints(company_id, canonical_key, period_label);

CREATE TABLE IF NOT EXISTS taxonomy_mappings (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    metric_raw TEXT NOT NULL,
    statement TEXT NOT NULL,
    source TEXT NOT NULL,
    human_confirmed INTEGER NOT NULL,
    update_date TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tax_lookup ON taxonomy_mappings(company_id, metric_raw);
"""


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    return conn


def save_datapoints(db_path: str | Path, datapoints: list[RawDatapoint]) -> None:
    conn = _connect(db_path)
    rows = [
        (
            d.id, d.company_id, d.metric_raw, d.period_label,
            d.period_end_date.isoformat(), d.value, d.currency, d.units,
            d.source, d.source_location, d.status,
            d.update_date.isoformat(), d.superseded_by_id,
        )
        for d in datapoints
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO raw_datapoints VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def query_datapoints(
    db_path: str | Path,
    company_id: str,
    period_label: str | None = None,
    source: str | None = None,
) -> list[RawDatapoint]:
    conn = _connect(db_path)
    sql = "SELECT * FROM raw_datapoints WHERE company_id = ?"
    params: list = [company_id]
    if period_label is not None:
        sql += " AND period_label = ?"
        params.append(period_label)
    if source is not None:
        sql += " AND source = ?"
        params.append(source)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    cols = ("id", "company_id", "metric_raw", "period_label", "period_end_date", "value", "currency", "units", "source", "source_location", "status", "update_date", "superseded_by_id")
    return [_row_to_datapoint(dict(zip(cols, r))) for r in rows]


def _row_to_datapoint(row: dict) -> RawDatapoint:
    row = dict(row)
    row["period_end_date"] = date.fromisoformat(row["period_end_date"])
    row["update_date"] = datetime.fromisoformat(row["update_date"])
    return RawDatapoint(**row)


def save_canonical_datapoints(db_path: str | Path, datapoints: list[CanonicalDatapoint]) -> None:
    conn = _connect(db_path)
    rows = [
        (
            d.id, d.company_id, d.canonical_key, d.metric_raw, d.period_label,
            d.period_end_date.isoformat(), d.value, d.currency, d.units,
            d.status, json.dumps(d.source_datapoint_ids), d.derivation_rule,
            d.update_date.isoformat(),
        )
        for d in datapoints
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO canonical_datapoints VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def query_canonical_datapoints(
    db_path: str | Path,
    company_id: str,
    period_label: str | None = None,
    canonical_key: str | None = None,
) -> list[CanonicalDatapoint]:
    from backend.normalization.taxonomy.models import CanonicalDatapoint
    conn = _connect(db_path)
    sql = "SELECT * FROM canonical_datapoints WHERE company_id = ?"
    params: list = [company_id]
    if period_label is not None:
        sql += " AND period_label = ?"
        params.append(period_label)
    if canonical_key is not None:
        sql += " AND canonical_key = ?"
        params.append(canonical_key)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    cols = ("id", "company_id", "canonical_key", "metric_raw", "period_label", "period_end_date", "value", "currency", "units", "status", "source_datapoint_ids", "derivation_rule", "update_date")
    result = []
    for r in rows:
        d = dict(zip(cols, r))
        d["period_end_date"] = date.fromisoformat(d["period_end_date"])
        d["update_date"] = datetime.fromisoformat(d["update_date"])
        d["source_datapoint_ids"] = json.loads(d["source_datapoint_ids"])
        result.append(CanonicalDatapoint(**d))
    return result


def save_taxonomy_mappings(db_path: str | Path, mappings: list[TaxonomyMapping]) -> None:
    conn = _connect(db_path)
    rows = [
        (
            m.id, m.company_id, m.canonical_key, m.metric_raw, m.statement,
            m.source, 1 if m.human_confirmed else 0, m.update_date.isoformat(),
        )
        for m in mappings
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO taxonomy_mappings VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def get_taxonomy_mappings(db_path: str | Path, company_id: str) -> list[TaxonomyMapping]:
    from backend.normalization.taxonomy.models import TaxonomyMapping
    conn = _connect(db_path)
    rows = conn.execute("SELECT * FROM taxonomy_mappings WHERE company_id = ?", (company_id,)).fetchall()
    conn.close()
    cols = ("id", "company_id", "canonical_key", "metric_raw", "statement", "source", "human_confirmed", "update_date")
    result = []
    for r in rows:
        d = dict(zip(cols, r))
        d["human_confirmed"] = bool(d["human_confirmed"])
        d["update_date"] = datetime.fromisoformat(d["update_date"])
        result.append(TaxonomyMapping(**d))
    return result