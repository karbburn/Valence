from __future__ import annotations

"""
Tiered Batch Rollout Orchestrator for Valence.

Executes staged rollout waves across the target universe:
  - Tier 1: 7 Core Pilot Companies (Infosys, TCS, Tata Motors, Tata Steel, AAPL, MSFT, INFY ADR)
  - Tier 2: Additional Target Non-Financials (Wipro, HCLTech, L&T, Sun Pharma, NVDA, GOOGL, AMZN)
  - Tier 3: Full Universe Rolling Batches (all non-financial filers)

Enforces 80% success threshold circuit breakers and records durable onboarding status per company.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

from backend.data.batch import BatchTaskResult, run_batch_tier
from backend.data.pipeline import DB_PATH
from backend.data.universe.acquisition import acquire_full_universe
from backend.data.universe.master_list import seed_master_universe
from backend.data.universe.store import list_all_universe_companies

logger = logging.getLogger(__name__)

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
    max_batch_size: int = 50,
) -> Dict[str, Any]:
    """Execute staged rollout for given universe tier and evaluate failure threshold."""
    seed_master_universe(db_path=db_path)

    if target_tier == 1:
        target_ids = TIER_1_IDS
    elif target_tier == 2:
        target_ids = TIER_2_IDS
    else:
        # Full universe non-financial filers
        all_companies = list_all_universe_companies(db_path=db_path)
        non_fin = [c for c in all_companies if not c.is_financial]
        target_ids = [c.company_id for c in non_fin[:max_batch_size]]

    results: List[BatchTaskResult] = run_batch_tier(target_ids, db_path=db_path)

    successful = sum(1 for r in results if r.success)
    total = len(results)
    success_rate = successful / total if total > 0 else 0.0

    threshold_met = success_rate >= 0.80
    circuit_breaker_triggered = not threshold_met

    if circuit_breaker_triggered:
        logger.warning(
            "Circuit breaker TRIGGERED for Tier %d: success rate %.2f%% below 80%% threshold",
            target_tier,
            success_rate * 100.0,
        )

    return {
        "tier": target_tier,
        "total_attempted": total,
        "successful_count": successful,
        "success_rate": round(success_rate, 4),
        "threshold_met": threshold_met,
        "circuit_breaker_triggered": circuit_breaker_triggered,
        "results": [r.model_dump() for r in results],
    }
