from __future__ import annotations

"""
Reconciliation Engine for Valence.

Reconciles primary Screener.in export data against secondary regulated BSE/NSE PDF filings
per company, resolving conflicts per data_architecture hierarchy (filing wins on conflict).
Mark superseded rows and emit per-company discrepancy logs.
"""

import json
from pathlib import Path

from backend.data.normalization import canonical
from backend.data.store import RawDatapoint, query_datapoints, save_datapoints

DEFAULT_COMPANY_ID = "infy_infy"
TOLERANCE_FRAC = 0.005
TOLERANCE_ABS = 1.0  # crores


def _within_tolerance(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOLERANCE_FRAC * abs(b), TOLERANCE_ABS)


def reconcile(
    db_path: str | Path,
    log_path: str | Path,
    company_id: str = DEFAULT_COMPANY_ID,
) -> list[dict]:
    """Mark every Screener datapoint that a filing contradicts as superseded for company_id.

    Precedence per data_architecture: the regulated filing wins. Comparison keys
    on a canonical metric vocabulary so vendor wording differences reconcile.
    Returns the discrepancy records and writes them to log_path as JSON.
    """
    screener = query_datapoints(db_path, company_id=company_id, source="screener")
    filing = query_datapoints(db_path, company_id=company_id, source="nse_filing")

    fmap: dict[tuple[str, str], list[RawDatapoint]] = {}
    for d in filing:
        fmap.setdefault((canonical(d.metric_raw), d.period_label), []).append(d)

    discrepancies: list[dict] = []
    superseded: list[RawDatapoint] = []
    for s in screener:
        key = (canonical(s.metric_raw), s.period_label)
        matches = fmap.get(key)
        if not matches:
            continue
        f = matches[0]
        if _within_tolerance(s.value, f.value):
            continue
        discrepancies.append({
            "company_id": company_id,
            "metric_raw": s.metric_raw,
            "canonical_metric": key[0],
            "period_label": s.period_label,
            "screener_value": s.value,
            "filing_value": f.value,
            "abs_diff": abs(s.value - f.value),
            "rel_diff": abs(s.value - f.value) / abs(f.value) if f.value else None,
            "winner": "nse_filing",
            "screener_id": s.id,
            "filing_id": f.id,
        })
        s.superseded_by_id = f.id
        superseded.append(s)

    if superseded:
        save_datapoints(db_path, superseded, clear_existing=False)

    # Preserve multi-company logs if log_path exists
    log_file = Path(log_path)
    existing_logs: list[dict] = []
    if log_file.exists():
        try:
            existing_logs = json.loads(log_file.read_text(encoding="utf-8"))
            if not isinstance(existing_logs, list):
                existing_logs = []
        except Exception:
            existing_logs = []

    # Filter out previous entries for this company_id and update
    updated_logs = [entry for entry in existing_logs if entry.get("company_id") != company_id] + discrepancies
    log_file.write_text(json.dumps(updated_logs, indent=2, default=str), encoding="utf-8")

    return discrepancies
