from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from backend.data.batch import BatchTaskResult, run_batch_tier
from backend.data.pipeline import DB_PATH
from backend.data.universe.master_list import seed_master_universe
from backend.data.universe.store import list_all_universe_companies

TIER_1_IDS = [
    "infy_infy",
    "tcs_tcs",
    "tatamotors_tatamotors",
    "tatasteel_tatasteel",
    "aapl_us",
    "msft_us",
    "infy_us",
]

TIER_2_IDS = [
    "wipro_wipro",
    "hcltech_hcltech",
    "lt_lt",
    "sunpharma_sunpharma",
    "nvda_us",
    "googl_us",
    "amzn_us",
]


def execute_staged_rollout(
    target_tier: int = 1,
    db_path: str | Path = DB_PATH,
) -> Dict[str, Any]:
    """Execute staged rollout for given universe tier and evaluate failure threshold."""
    # Ensure master universe list is populated
    seed_master_universe(db_path=db_path)

    target_ids = TIER_1_IDS if target_tier == 1 else TIER_2_IDS
    results: List[BatchTaskResult] = run_batch_tier(target_ids, db_path=db_path)

    successful = sum(1 for r in results if r.success)
    total = len(results)
    success_rate = successful / total if total > 0 else 0.0

    threshold_met = success_rate >= 0.80

    return {
        "tier": target_tier,
        "total_attempted": total,
        "successful_count": successful,
        "success_rate": round(success_rate, 4),
        "threshold_met": threshold_met,
        "results": [r.model_dump() for r in results],
    }
