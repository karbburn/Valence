from __future__ import annotations

"""
Self-check suite for Stage 15 / Phase 3.5 — Universe Expansion (Full India + US Ticker Coverage).

Acceptance criteria:
  1. Universe Storage & Master Listing:
     Seeds and populates SQLite company_universe table with master listings across India and US markets.
  2. Sector Filtering:
     Enforces strict non-financial sector filtering (excludes Banks, Insurance, REITs).
  3. Confidence-Scored Taxonomy Mapping:
     Correctly evaluates High, Medium, and Low confidence mapping suggestions and routes novel labels to review queue.
  4. Batch Ingestion & Retries:
     Batch runner processes onboarding tasks with status reporting and exponential backoff retry controls.
  5. Universe Monitoring:
     Computes universe-level quality report, QA validity rate, and failure frequencies.
  6. Staged Rollout Orchestration:
     Tier 1 rollout achieves >= 80% onboarding success rate threshold.
  7. API Ticker Search:
     GET /api/companies and GET /api/companies/search return matching onboarded company records.
  8. Cross-Market Non-Regression:
     All 7 original pilot companies (INFY, TCS, Tata Motors, Tata Steel, AAPL, MSFT, INFY ADR) remain MODEL VALID.
"""

from pathlib import Path
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.data.batch import run_batch_company_onboarding
from backend.data.monitoring import generate_universe_quality_report
from backend.data.pipeline import DB_PATH
from backend.data.universe.master_list import seed_master_universe
from backend.data.universe.rollout import execute_staged_rollout
from backend.data.universe.sector_filter import is_financial_sector
from backend.data.universe.store import get_universe_company, search_universe_companies
from backend.normalization.taxonomy.mapping_engine import suggest_canonical_mapping, route_to_review_queue, feedback_mapping_resolution


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"Stage 15 self-check FAILED: {msg}")
    print(f"ok: {msg}")


def main() -> None:
    print("Running Stage 15 / Phase 3.5 Universe Expansion validation self-check...")

    # 1. Universe Storage & Master Listing Seeding
    print("\n1. Seeding Master Company Universe Database...")
    seed_master_universe()
    c_infy = get_universe_company("infy_infy")
    _assert(c_infy is not None, "Infosys India present in universe database")
    _assert(c_infy.onboarding_status == "onboarded", "Infosys India onboarding status is 'onboarded'")

    c_aapl = get_universe_company("aapl_us")
    _assert(c_aapl is not None, "Apple US present in universe database")
    _assert(c_aapl.onboarding_status == "onboarded", "Apple US onboarding status is 'onboarded'")

    # 2. Sector Filtering
    print("\n2. Sector Filtering (Non-Financial Isolation)...")
    is_fin_tech, _ = is_financial_sector("Information Technology", "IT Services")
    _assert(not is_fin_tech, "IT sector correctly identified as non-financial")

    is_fin_auto, _ = is_financial_sector("Automotive", "Automobiles")
    _assert(not is_fin_auto, "Automotive sector correctly identified as non-financial")

    is_fin_bank, reason_bank = is_financial_sector("Financial Services", "Private Sector Bank")
    _assert(is_fin_bank, f"Bank correctly identified as financial ({reason_bank})")

    is_fin_sic, reason_sic = is_financial_sector("Finance", "Commercial Banks", sic_code=6021)
    _assert(is_fin_sic, f"SIC code 6021 correctly identified as financial ({reason_sic})")

    # 3. Confidence-Scored Taxonomy Mapping Engine
    print("\n3. Automated Taxonomy Mapping Engine & Review Queue...")
    res_exact = suggest_canonical_mapping("Revenues")
    _assert(res_exact.level == "high" and res_exact.confidence_score == 1.0, "Exact label mapped with 1.0 score (high)")

    res_norm = suggest_canonical_mapping("  cost of sales  ")
    _assert(res_norm.level == "high" and res_norm.confidence_score >= 0.9, "Normalized label mapped with >=0.9 score (high)")

    res_fuzzy = suggest_canonical_mapping("Total operating revenue")
    _assert(res_fuzzy.level in ("high", "medium"), "Fuzzy label mapped with high/medium confidence score")

    res_low = suggest_canonical_mapping("Unusual Speculative Special Reserve Item X")
    _assert(res_low.level == "low", "Novel label categorized as low confidence")

    # Route low confidence label to review queue and verify feedback resolution
    route_to_review_queue("infy_infy", "Unusual Speculative Special Reserve Item X", res_low)
    feedback_mapping_resolution("Unusual Speculative Special Reserve Item X", "canonical.bs.other_reserves", "bs")
    res_learned = suggest_canonical_mapping("Unusual Speculative Special Reserve Item X")
    _assert(res_learned.level == "high" and res_learned.confidence_score == 1.0, "Learned label mapped with 1.0 score after feedback")

    # 4. Batch Ingestion Productionization & Task Runner
    print("\n4. Batch Productionization Runner Test...")
    batch_res = run_batch_company_onboarding("tcs_tcs")
    _assert(batch_res.success, "Batch onboarding succeeded for TCS")
    _assert(batch_res.status_category == "success", "Batch status category is 'success'")

    # 5. Staged Rollout Execution
    print("\n5. Staged Rollout Execution (Tier 1)...")
    rollout_res = execute_staged_rollout(target_tier=1)
    _assert(rollout_res["threshold_met"], f"Tier 1 rollout met threshold (Success rate: {rollout_res['success_rate']*100}%)")

    # 6. Universe Quality Monitoring Report
    print("\n6. Universe Data Quality Monitoring Report...")
    report = generate_universe_quality_report()
    _assert(report.total_companies > 0, f"Total companies tracked: {report.total_companies}")
    _assert(report.onboarded_count >= 7, f"Onboarded count >= 7 (got {report.onboarded_count})")
    _assert(report.qa_model_valid_rate == 1.0, f"QA Model Valid Rate: {report.qa_model_valid_rate * 100}%")

    # 7. FastAPI Universe Search & Ticker Autocomplete
    print("\n7. Web API Ticker Search Endpoints...")
    client = TestClient(app)
    res_companies = client.get("/api/companies")
    _assert(res_companies.status_code == 200, "GET /api/companies returned 200")
    c_list = res_companies.json()
    _assert(len(c_list) >= 7, f"GET /api/companies returned at least 7 onboarded companies (got {len(c_list)})")

    res_search_infy = client.get("/api/companies/search?q=INFY")
    _assert(res_search_infy.status_code == 200, "GET /api/companies/search?q=INFY returned 200")
    s_list = res_search_infy.json()
    _assert(any(c["ticker"] == "INFY" for c in s_list), "Search results contain INFY ticker")

    res_search_aapl = client.get("/api/companies/search?q=AAPL")
    _assert(res_search_aapl.status_code == 200, "GET /api/companies/search?q=AAPL returned 200")
    s_aapl = res_search_aapl.json()
    _assert(any(c["ticker"] == "AAPL" for c in s_aapl), "Search results contain AAPL ticker")

    print("\n" + "=" * 65)
    print("  Stage 15 / Phase 3.5 Universe Expansion Summary:")
    print(f"    Master Universe Seeded : {report.total_companies} Tickers (India + US)")
    print(f"    Onboarded Companies    : {report.onboarded_count} Companies")
    print(f"    Non-Financial Filter   : ENFORCED (Banks/Insurers Excluded)")
    print(f"    Taxonomy Engine        : CONFIDENCE SCORED + REVIEW QUEUE")
    print(f"    QA Validity Rollup     : {report.qa_model_valid_rate * 100}% MODEL VALID")
    print(f"    API Ticker Search      : ACTIVE (/api/companies/search)")
    print("=" * 65)
    print("\nALL STAGE 15 SELF-CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
