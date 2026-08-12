from __future__ import annotations

import json
from pathlib import Path

from backend.data.normalization import canonical
from backend.data.store import RawDatapoint, query_datapoints, save_datapoints

COMPANY_ID = "infy_infy"
TOLERANCE_FRAC = 0.005
TOLERANCE_ABS = 1.0  # crores


def _within_tolerance(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOLERANCE_FRAC * abs(b), TOLERANCE_ABS)


def reconcile(db_path: str | Path, log_path: str | Path) -> list[dict]:
    """Mark every Screener datapoint that a filing contradicts as superseded.

    Precedence per data_architecture: the regulated filing wins. Comparison keys
    on a canonical metric vocabulary so vendor wording differences reconcile.
    Returns the discrepancy records and writes them to log_path as JSON.
    """
    screener = query_datapoints(db_path, COMPANY_ID, source="screener")
    filing = query_datapoints(db_path, COMPANY_ID, source="nse_filing")

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
            "company_id": COMPANY_ID,
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
        save_datapoints(db_path, superseded)

    Path(log_path).write_text(json.dumps(discrepancies, indent=2, default=str))
    return discrepancies
