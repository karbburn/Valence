from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from backend.normalization.taxonomy.models import CanonicalDatapoint, TaxonomyMapping

# `local_export` is a hand-maintained spreadsheet held in the repository, NOT a
# filing and NOT a live API response. It must never be labelled with the source
# it imitates: doing so is how a model served invented figures comes to present
# them to a reader as audited SEC data, with a `source_location` pointing at a
# cell in a document nobody published.
Source = Literal[
    "screener", "bse_filing", "nse_filing", "sec_edgar", "yfinance_live",
    "twelvedata", "local_export",
]
# `estimated` means a projection or a hand-entered figure, never a filed number.
Status = Literal["reported", "reported_adjusted", "derived", "estimated"]


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
    # Which statement the caption was printed in: "BALANCE SHEET",
    # "PROFIT & LOSS", "CASH FLOW:", or None where the reader has no such notion.
    #
    # This is not metadata. Two statements print the same words for opposite things:
    #
    #     p.104  Consolidated Statement of Cash Flows
    #            "Prepayments and other assets        (2,312)"   a MOVEMENT
    #     p.100  Consolidated Balance Sheet
    #            "Prepayments and other current assets 15,703"   a STOCK
    #
    # Without the statement, both arrive as the bare label "Prepayments and other
    # assets", the mapper cannot tell them apart, and the cash-flow figure
    # overwrites the balance-sheet one. That is how Infosys published -2,312 as a
    # balance-sheet stock where its own filing says +15,703: a movement published
    # as a balance, and negative where an asset cannot be.
    #
    # Every reader already KNOWS this -- each passes `section` into its datapoint
    # id hash. It was hashed and then discarded, so the knowledge existed and was
    # thrown away at the boundary.
    section: Optional[str] = None
    # Which half of a BALANCE SHEET the caption was printed in: "current",
    # "noncurrent", or None where the reader has no such notion or the page is not
    # a balance sheet.
    #
    # A filer may print the same caption on both sides:
    #
    #     Current assets      Unbilled revenue 15,483   Income tax assets 1,835
    #     Non-current assets  Unbilled revenue  1,738   Income tax assets   666
    #
    # Both members of each pair reach ONE canonical key, so without this the later
    # row overwrites the earlier and the reader is shown the non-current figure as
    # though it were the current one -- which is exactly what
    # `current_assets_reconcile` then cannot explain.
    #
    # Taken from the filer's own printed headers rather than inferred from position,
    # so it is the statement answering the question.
    bs_half: Optional[str] = None
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
    superseded_by_id TEXT,
    section TEXT,
    bs_half TEXT
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


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that `CREATE TABLE IF NOT EXISTS` cannot add.

    That statement is a no-op when the table already exists, so a column added to
    `_SCHEMA` is silently absent from every database created before it. The symptom
    is an INSERT whose placeholder count no longer matches the table, which surfaces
    as a failure in an unrelated test rather than as a schema error.

    Observed on 2026-10-02 with `section`: `raw_datapoints` in the local store kept
    its 13 columns, the 14-value INSERT failed, and five tests failed in a full
    suite while passing in isolation. Additive only -- SQLite has no
    `ADD COLUMN IF NOT EXISTS`, so existing columns are checked first and the
    migration is a no-op on a database that is already current.
    """
    additions = {"raw_datapoints": [("section", "TEXT"), ("bs_half", "TEXT")]}
    for table, columns in additions.items():
        present = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if not present:
            continue  # table not created yet; _SCHEMA will make it correctly
        for name, decl in columns:
            if name not in present:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, decl))
    conn.commit()


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection for callers that need to batch multiple writes atomically.

    The caller owns commit()/rollback()/close().
    """
    return _connect(db_path)


def delete_company_datapoints(db_path: str | Path, company_id: str) -> None:
    """Drop every raw and canonical row belonging to ONE company.

    Scoped deliberately. The previous way to force a re-ingest of a single
    company unlinked the whole database file, which destroyed every other
    company and the universe table as a side effect of refreshing one name.
    """
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM raw_datapoints WHERE company_id = ?", (company_id,))
        conn.execute("DELETE FROM canonical_datapoints WHERE company_id = ?", (company_id,))
        conn.commit()
    finally:
        conn.close()


def save_datapoints(db_path: str | Path, datapoints: list[RawDatapoint], clear_existing: bool = True) -> None:
    conn = _connect(db_path)
    if clear_existing:
        company_ids = set(d.company_id for d in datapoints)
        for cid in company_ids:
            conn.execute("DELETE FROM raw_datapoints WHERE company_id = ?", (cid,))
    rows = [
        (
            d.id, d.company_id, d.metric_raw, d.period_label,
            d.period_end_date.isoformat(), d.value, d.currency, d.units,
            d.source, d.source_location, d.status,
            d.update_date.isoformat(), d.superseded_by_id, d.section, d.bs_half,
        )
        for d in datapoints
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO raw_datapoints VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
    params: list[Any] = [company_id]
    if period_label:
        sql += " AND period_label = ?"
        params.append(period_label)
    if source:
        sql += " AND source = ?"
        params.append(source)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    cols = (
        "id", "company_id", "metric_raw", "period_label",
        "period_end_date", "value", "currency", "units",
        "source", "source_location", "status",
        "update_date", "superseded_by_id",
    )
    result = []
    for r in rows:
        d = dict(zip(cols, r))
        d["period_end_date"] = date.fromisoformat(d["period_end_date"])
        d["update_date"] = datetime.fromisoformat(d["update_date"])
        result.append(RawDatapoint(**d))
    return result


def save_canonical_datapoints(
    db_path: str | Path,
    datapoints: list[CanonicalDatapoint],
    clear_existing: bool = True,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Persist canonical datapoints.

    Pass `conn` (from ``backend.data.store.connect``) to participate in a caller-managed
    transaction; otherwise a dedicated connection is opened, committed and closed.
    """
    own = conn is None
    if own:
        conn = _connect(db_path)
    try:
        if clear_existing:
            company_ids = set(d.company_id for d in datapoints)
            for cid in company_ids:
                conn.execute("DELETE FROM canonical_datapoints WHERE company_id = ?", (cid,))
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
        if own:
            conn.commit()
    finally:
        if own:
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


def save_taxonomy_mappings(
    db_path: str | Path,
    mappings: list[TaxonomyMapping],
    conn: sqlite3.Connection | None = None,
) -> None:
    """Persist taxonomy mappings.

    Pass `conn` (from ``backend.data.store.connect``) to participate in a caller-managed
    transaction; otherwise a dedicated connection is opened, committed and closed.
    """
    own = conn is None
    if own:
        conn = _connect(db_path)
    try:
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
        if own:
            conn.commit()
    finally:
        if own:
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