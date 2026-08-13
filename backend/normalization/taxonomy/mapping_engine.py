from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from backend.data.pipeline import DB_PATH
from backend.data.universe.models import MappingConfidenceLevel, MappingConfidenceResult
from backend.normalization.taxonomy.registry import RAW_METRIC_MAP, get_canonical_mapping


def _normalize_string(s: str) -> str:
    """Normalize label string by lowercasing, stripping whitespace and special chars."""
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s)


# Build a pre-calculated normalized map for fast lookup
_NORMALIZED_MAP: dict[str, Tuple[str, str]] = {
    _normalize_string(k): v for k, v in RAW_METRIC_MAP.items()
}


def suggest_canonical_mapping(metric_raw: str) -> MappingConfidenceResult:
    """Confidence-scored mapping suggestion engine.

    Returns:
        MappingConfidenceResult with score (0.0 to 1.0) and level ('high', 'medium', 'low').
    """
    clean_raw = metric_raw.strip()

    # 1. Exact match in RAW_METRIC_MAP
    direct = get_canonical_mapping(clean_raw)
    if direct is not None:
        key, statement = direct
        return MappingConfidenceResult(
            metric_raw=clean_raw,
            canonical_key=key,
            statement=statement,
            confidence_score=1.0,
            level="high",
            reason="Exact match in taxonomy registry",
        )

    # 2. Normalized string match
    norm_key = _normalize_string(clean_raw)
    if norm_key in _NORMALIZED_MAP:
        key, statement = _NORMALIZED_MAP[norm_key]
        return MappingConfidenceResult(
            metric_raw=clean_raw,
            canonical_key=key,
            statement=statement,
            confidence_score=0.9,
            level="high",
            reason="Normalized string match in taxonomy registry",
        )

    # 3. Token-similarity fuzzy match against known labels
    raw_tokens = set(norm_key.split())
    if raw_tokens:
        best_match: Optional[Tuple[str, str]] = None
        best_score = 0.0

        for registered_label, (c_key, stmt) in RAW_METRIC_MAP.items():
            reg_tokens = set(_normalize_string(registered_label).split())
            if not reg_tokens:
                continue
            intersection = raw_tokens.intersection(reg_tokens)
            union = raw_tokens.union(reg_tokens)
            score = len(intersection) / len(union) if union else 0.0

            # Boost score if a core metric keyword overlaps
            core_keywords = {"revenue", "sales", "profit", "cost", "expenses", "depreciation", "tax", "borrowings", "cash", "receivables", "payables", "equity"}
            if intersection.intersection(core_keywords):
                score += 0.25

            if score > best_score:
                best_score = min(score, 0.88)
                best_match = (c_key, stmt)

        if best_score >= 0.45 and best_match is not None:
            key, statement = best_match
            return MappingConfidenceResult(
                metric_raw=clean_raw,
                canonical_key=key,
                statement=statement,
                confidence_score=round(best_score, 2),
                level="medium",
                reason=f"Token similarity ({round(best_score * 100)}%) with registered label",
            )

    # 4. Low confidence / novel label -> Route to review queue
    return MappingConfidenceResult(
        metric_raw=clean_raw,
        canonical_key=None,
        statement=None,
        confidence_score=0.2,
        level="low",
        reason="Unrecognized label, requires human review",
    )


def route_to_review_queue(
    company_id: str,
    metric_raw: str,
    suggested: MappingConfidenceResult,
    db_path: str | Path = DB_PATH,
) -> None:
    """Route low-confidence mapping to human review queue SQLite table."""
    conn = sqlite3.connect(str(db_path))
    req_id = uuid.uuid4().hex
    now_iso = datetime.now().isoformat()
    conn.execute(
        """
        INSERT OR REPLACE INTO taxonomy_review_queue
        (id, company_id, metric_raw, suggested_key, confidence_score, status, resolved_by, update_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            req_id,
            company_id,
            metric_raw,
            suggested.canonical_key,
            suggested.confidence_score,
            "pending",
            None,
            now_iso,
        ),
    )
    conn.commit()
    conn.close()


def feedback_mapping_resolution(
    metric_raw: str,
    canonical_key: str,
    statement: str = "is",
    human_confirmed: bool = True,
) -> None:
    """Feedback loop: add human-confirmed mapping into runtime registry."""
    RAW_METRIC_MAP[metric_raw.strip()] = (canonical_key, statement)
    _NORMALIZED_MAP[_normalize_string(metric_raw)] = (canonical_key, statement)
