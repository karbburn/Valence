from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

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