from __future__ import annotations

from typing import Dict, List, Tuple
from backend.data.store import RawDatapoint, query_datapoints
from backend.normalization.taxonomy.models import CanonicalDatapoint


def select_primary_datapoints(
    canonical_datapoints: list[CanonicalDatapoint],
    statement_type: str,  # "is", "bs", or "cf"
    raw_datapoints_map: Dict[str, RawDatapoint] | None = None,
) -> Dict[Tuple[str, str], CanonicalDatapoint]:
    """Selects the single best/primary CanonicalDatapoint for each (canonical_key, period_label) pair.

    Filters out movement/note sub-table rows by prioritizing primary statement table locations.
    """
    grouped: Dict[Tuple[str, str], List[CanonicalDatapoint]] = {}
    for d in canonical_datapoints:
        grouped.setdefault((d.canonical_key, d.period_label), []).append(d)

    def _score(dp: CanonicalDatapoint) -> int:
        score = 0
        if dp.status == "derived":
            score += 200

        if raw_datapoints_map:
            locs = [raw_datapoints_map[rid].source_location for rid in dp.source_datapoint_ids if rid in raw_datapoints_map]
            loc_str = " ".join(locs).upper()

            if statement_type == "bs" and ("BALANCE SHEET" in loc_str or "SHEET" in loc_str or "DATASET" in loc_str or "DATASHEET" in loc_str):
                score += 100
            elif statement_type == "is" and ("PROFIT & LOSS" in loc_str or "PROFIT" in loc_str or "P&L" in loc_str or "DATASHEET" in loc_str):
                score += 100
            elif statement_type == "cf" and ("CASH FLOW" in loc_str or "CASH" in loc_str or "DATASHEET" in loc_str):
                score += 100

        # Primary label boost
        if dp.metric_raw in (
            "Trade receivables", "Unbilled revenue", "Revenues", "Sales",
            "Net Profit", "Operating profit", "Total assets", "Total equity",
            "Total liabilities and equity", "Cost of sales", "Gross profit"
        ):
            score += 50

        # Positive value boost for asset/equity line items (main vs movement note)
        if dp.value > 0:
            score += 10

        return score

    best_map: Dict[Tuple[str, str], CanonicalDatapoint] = {}
    for key, dps in grouped.items():
        best_map[key] = max(dps, key=_score)

    return best_map
