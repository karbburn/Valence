from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from backend.data.pipeline import DB_PATH
from backend.data.universe.models import UniverseCompany, OnboardingStatus, MarketType

_UNIVERSE_SCHEMA = """
CREATE TABLE IF NOT EXISTS company_universe (
    company_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    exchange TEXT NOT NULL,
    sector TEXT NOT NULL,
    industry TEXT NOT NULL,
    is_financial INTEGER NOT NULL,
    onboarding_status TEXT NOT NULL,
    onboarding_notes TEXT,
    last_updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_universe_market ON company_universe(market);
CREATE INDEX IF NOT EXISTS idx_universe_status ON company_universe(onboarding_status);
CREATE INDEX IF NOT EXISTS idx_universe_search ON company_universe(ticker, name);

CREATE TABLE IF NOT EXISTS taxonomy_review_queue (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    metric_raw TEXT NOT NULL,
    suggested_key TEXT,
    confidence_score REAL NOT NULL,
    status TEXT NOT NULL,
    resolved_by TEXT,
    update_date TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_status ON taxonomy_review_queue(status);

CREATE TABLE IF NOT EXISTS taxonomy_learned_mappings (
    metric_raw TEXT PRIMARY KEY,
    canonical_key TEXT NOT NULL,
    statement TEXT NOT NULL,
    update_date TEXT NOT NULL
);
"""


def _connect(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_UNIVERSE_SCHEMA)
    return conn


def save_universe_companies(companies: list[UniverseCompany], db_path: str | Path = DB_PATH) -> None:
    conn = _connect(db_path)
    try:
        rows = [
            (
                c.company_id,
                c.ticker,
                c.name,
                c.market,
                c.exchange,
                c.sector,
                c.industry,
                1 if c.is_financial else 0,
                c.onboarding_status,
                c.onboarding_notes,
                c.last_updated.isoformat(),
            )
            for c in companies
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO company_universe VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def get_universe_company(company_id: str, db_path: str | Path = DB_PATH) -> Optional[UniverseCompany]:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM company_universe WHERE company_id = ?", (company_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    cols = (
        "company_id", "ticker", "name", "market", "exchange",
        "sector", "industry", "is_financial", "onboarding_status",
        "onboarding_notes", "last_updated"
    )
    d = dict(zip(cols, row))
    d["is_financial"] = bool(d["is_financial"])
    d["last_updated"] = datetime.fromisoformat(d["last_updated"])
    return UniverseCompany(**d)


def search_universe_companies(
    query: str,
    market: Optional[MarketType] = None,
    status: Optional[OnboardingStatus] = None,
    non_financial_only: bool = True,
    limit: int = 50,
    db_path: str | Path = DB_PATH,
) -> list[UniverseCompany]:
    conn = _connect(db_path)
    try:
        sql = "SELECT * FROM company_universe WHERE 1=1"
        params: list[Any] = []

        if query.strip():
            sql += " AND (ticker LIKE ? OR name LIKE ?)"
            q_str = f"%{query.strip()}%"
            params.extend([q_str, q_str])

        if market:
            sql += " AND market = ?"
            params.append(market)

        if status:
            sql += " AND onboarding_status = ?"
            params.append(status)

        if non_financial_only:
            sql += " AND is_financial = 0"

        sql += " ORDER BY ticker ASC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    cols = (
        "company_id", "ticker", "name", "market", "exchange",
        "sector", "industry", "is_financial", "onboarding_status",
        "onboarding_notes", "last_updated"
    )
    result = []
    for r in rows:
        d = dict(zip(cols, r))
        d["is_financial"] = bool(d["is_financial"])
        d["last_updated"] = datetime.fromisoformat(d["last_updated"])
        result.append(UniverseCompany(**d))
    return result


def update_onboarding_status(
    company_id: str,
    status: OnboardingStatus,
    notes: Optional[str] = None,
    db_path: str | Path = DB_PATH,
) -> None:
    conn = _connect(db_path)
    try:
        now_iso = datetime.now().isoformat()
        conn.execute(
            "UPDATE company_universe SET onboarding_status = ?, onboarding_notes = ?, last_updated = ? WHERE company_id = ?",
            (status, notes, now_iso, company_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_all_universe_companies(db_path: str | Path = DB_PATH) -> list[UniverseCompany]:
    return search_universe_companies(query="", limit=10000, db_path=db_path)


def clean_corrupted_legacy_universe_ids(db_path: str | Path = DB_PATH) -> int:
    """Delete legacy corrupted company_id rows (e.g. hcltech_infy, wipro_infy) where ticker != INFY."""
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM company_universe WHERE company_id LIKE '%_infy' AND UPPER(ticker) != 'INFY'")
        deleted_count = cur.rowcount
        conn.commit()
        return deleted_count
    finally:
        conn.close()


def verify_canonical_id_integrity(db_path: str | Path = DB_PATH) -> bool:
    """Verify canonical company_id uniqueness and structure invariant.

    Rules:
      1. Every company_id in company_universe MUST be unique.
      2. No non-Infosys company should end with `_infy` (legacy corruption check).
    """
    clean_corrupted_legacy_universe_ids(db_path=db_path)
    companies = list_all_universe_companies(db_path=db_path)
    cids = [c.company_id for c in companies]
    if len(cids) != len(set(cids)):
        raise AssertionError("Duplicate company_ids detected in universe database!")

    for c in companies:
        if c.company_id.endswith("_infy") and c.ticker.upper() != "INFY":
            raise AssertionError(f"Corrupted company_id detected for {c.ticker}: {c.company_id}")

    return True
