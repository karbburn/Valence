from __future__ import annotations

import json
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
    last_updated TEXT NOT NULL,
    slug TEXT,
    cik TEXT
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
    _migrate_columns(conn)
    return conn


# Columns added after the first release. ALTER TABLE ADD COLUMN is a no-op when
# the column is already present, so this runs on every connect and needs no
# schema-version table. Existing rows get NULL, which every read path treats as
# "not yet assigned" and backfills.
_ADDED_COLUMNS = (("slug", "TEXT"), ("cik", "TEXT"))


def _migrate_columns(conn: sqlite3.Connection) -> None:
    present = {r[1] for r in conn.execute("PRAGMA table_info(company_universe)")}
    added = False
    for name, decl in _ADDED_COLUMNS:
        if name not in present:
            conn.execute(f"ALTER TABLE company_universe ADD COLUMN {name} {decl}")
            added = True
    if added:
        conn.commit()


_UNIVERSE_COLS = (
    "company_id", "ticker", "name", "market", "exchange", "sector", "industry",
    "is_financial", "onboarding_status", "onboarding_notes", "last_updated",
    "slug", "cik",
)


def _row_to_company(row: tuple) -> UniverseCompany:
    d = dict(zip(_UNIVERSE_COLS, row))
    d["is_financial"] = bool(d["is_financial"])
    d["last_updated"] = datetime.fromisoformat(d["last_updated"])
    return UniverseCompany(
        company_id=d["company_id"],
        ticker=d["ticker"],
        name=d["name"],
        market=d["market"],
        exchange=d["exchange"],
        sector=d["sector"],
        industry=d["industry"],
        is_financial=d["is_financial"],
        onboarding_status=d["onboarding_status"],
        onboarding_notes=d["onboarding_notes"],
        last_updated=d["last_updated"],
        slug=d.get("slug"),
        cik=d.get("cik"),
    )


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
                c.slug,
                c.cik,
            )
            for c in companies
        ]
        # Named columns, not positional: the table has grown since it was first
        # written, and a positional INSERT silently truncates the moment the
        # column order and the row tuple disagree.
        placeholders = ", ".join(["?"] * len(_UNIVERSE_COLS))
        conn.executemany(
            f"INSERT OR REPLACE INTO company_universe ({', '.join(_UNIVERSE_COLS)}) "
            f"VALUES ({placeholders})",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def get_universe_company(company_id: str, db_path: str | Path = DB_PATH) -> Optional[UniverseCompany]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"SELECT {', '.join(_UNIVERSE_COLS)} FROM company_universe WHERE company_id = ?",
            (company_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return _row_to_company(row)


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
        order_params: list[Any] = []
        if query.strip():
            raw_q = query.strip()
            sql += " AND (ticker LIKE ? OR name LIKE ?)"
            q_str = f"%{raw_q}%"
            params.extend([q_str, q_str])
            order_clause = """
                ORDER BY 
                    CASE WHEN UPPER(ticker) = UPPER(?) THEN 1 
                         WHEN UPPER(ticker) LIKE UPPER(?) THEN 2 
                         WHEN UPPER(name) LIKE UPPER(?) THEN 3 
                         ELSE 4 END ASC,
                    CASE WHEN onboarding_status = 'onboarded' THEN 0 ELSE 1 END ASC,
                    LENGTH(ticker) ASC,
                    ticker ASC
            """
            order_params = [raw_q, f"{raw_q}%", f"{raw_q}%"]
        else:
            order_clause = " ORDER BY CASE WHEN onboarding_status = 'onboarded' THEN 0 ELSE 1 END ASC, ticker ASC"

        if market:
            sql += " AND market = ?"
            params.append(market)

        if status:
            sql += " AND onboarding_status = ?"
            params.append(status)

        if non_financial_only:
            sql += " AND is_financial = 0"

        sql += f"{order_clause} LIMIT ?"
        params.extend(order_params)
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    # Through the shared mapper, not a second column list. This function had its
    # own inline tuple that predated the slug and cik columns, so every search
    # result came back with slug=None even though the row had one. The dropdown
    # navigates by slug, so selecting a result fell back to the index instead of
    # opening the company, and the most-searched ticker in the product could not
    # be reached from its own search box.
    return [_row_to_company(r) for r in rows]


def get_universe_by_slug(slug: str, db_path: str | Path = DB_PATH) -> Optional[UniverseCompany]:
    """Exact, case-insensitive slug lookup. The resolver behind every /stock route.

    Only non-financial rows resolve. Financial-sector companies are excluded from
    the model engine, so returning one here would hand a page route a company_id
    the builder cannot service.
    """
    if not slug:
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"SELECT {', '.join(_UNIVERSE_COLS)} FROM company_universe "
            "WHERE UPPER(slug) = UPPER(?) AND is_financial = 0",
            (slug.strip(),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return _row_to_company(row)


def list_slugs(db_path: str | Path = DB_PATH) -> list[UniverseCompany]:
    """Every non-financial company that has a slug assigned, in slug order."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_UNIVERSE_COLS)} FROM company_universe "
            "WHERE slug IS NOT NULL AND is_financial = 0 ORDER BY UPPER(slug)"
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_company(r) for r in rows]


def assign_slugs_to_universe(db_path: str | Path = DB_PATH) -> int:
    """Recompute slugs for every non-financial company and persist them.

    Idempotent. Safe to run on every acquisition and on every deploy.
    """
    from backend.data.universe.slugs import assign_slugs

    companies = list_all_universe_companies(db_path)
    mapping = assign_slugs(companies)
    if not mapping:
        return 0
    conn = _connect(db_path)
    try:
        conn.executemany(
            "UPDATE company_universe SET slug = ? WHERE company_id = ?",
            [(slug, cid) for cid, slug in mapping.items()],
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_universe_slug ON company_universe(UPPER(slug))"
        )
        conn.commit()
    finally:
        conn.close()
    return len(mapping)


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


def backfill_universe_from_built_models(
    db_path: str | Path = DB_PATH,
    cache_dir: str | Path | None = None,
) -> list[str]:
    """Add universe rows for companies the platform can already serve.

    The hand-maintained seed list is a starting point, not the source of truth.
    A company that has a precomputed model snapshot, or an entry in the
    metadata registry, is a company the product can serve, so the universe must
    list it. Without this, rebuilding the store silently dropped every company
    that had been added through acquisition rather than seeded — the model still
    existed and still rendered, but the company vanished from search and from
    every bulk operation that enumerates the universe.

    Returns the company_ids that were added.
    """
    from datetime import datetime

    if cache_dir is None:
        cache_dir = Path(__file__).resolve().parents[2] / "data" / "cache"
    cache_path = Path(cache_dir)

    known = {c.company_id for c in list_all_universe_companies(db_path)}

    discovered: dict[str, UniverseCompany] = {}

    for snapshot in sorted(cache_path.glob("*.json")):
        if snapshot.name == "market_data_cache.json":
            continue
        cid = snapshot.stem
        if cid in known or cid in discovered:
            continue
        try:
            payload = json.loads(snapshot.read_text(encoding="utf-8"))
        except Exception:
            continue
        # A snapshot is a versioned envelope around the specification.
        model = payload.get("model") if isinstance(payload.get("model"), dict) else payload
        meta = (model or {}).get("metadata") or {}
        if not meta.get("company_id"):
            continue
        ticker = meta.get("ticker") or cid.split("_")[0].upper()
        market = meta.get("market") or ("us" if cid.endswith("_us") else "india")
        discovered[cid] = UniverseCompany(
            company_id=cid,
            ticker=ticker,
            name=meta.get("name") or ticker,
            market=market,
            exchange=meta.get("exchange") or ("NASDAQ" if market == "us" else "NSE"),
            sector=meta.get("sector") or "Unclassified",
            industry=meta.get("industry") or "Unclassified",
            is_financial=False,
            onboarding_status="onboarded",
            onboarding_notes="recovered from precomputed model snapshot",
            last_updated=datetime.now(),
        )

    if not discovered:
        return []

    save_universe_companies(list(discovered.values()), db_path=db_path)
    return sorted(discovered)


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
