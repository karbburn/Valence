from __future__ import annotations

from datetime import datetime
from pathlib import Path

from backend.data.pipeline import DB_PATH
from backend.data.universe.models import UniverseCompany
from backend.data.universe.sector_filter import is_financial_sector
from backend.data.universe.store import save_universe_companies, get_universe_company

SEED_COMPANIES: list[dict] = [
    # --- Onboarded India Companies ---
    {
        "company_id": "infy_infy",
        "ticker": "INFY",
        "name": "Infosys Limited",
        "market": "india",
        "exchange": "NSE",
        "sector": "Information Technology",
        "industry": "IT Services & Consulting",
        "onboarding_status": "onboarded",
        "onboarding_notes": "Phase 1 Pilot company - Fully validated",
    },
    {
        "company_id": "tcs_tcs",
        "ticker": "TCS",
        "name": "Tata Consultancy Services Limited",
        "market": "india",
        "exchange": "NSE",
        "sector": "Information Technology",
        "industry": "IT Services & Consulting",
        "onboarding_status": "onboarded",
        "onboarding_notes": "Phase 2 Generalization - Fully validated",
    },
    {
        "company_id": "tatamotors_tatamotors",
        "ticker": "TATAMOTORS",
        "name": "Tata Motors Limited",
        "market": "india",
        "exchange": "NSE",
        "sector": "Automotive",
        "industry": "Automobiles",
        "onboarding_status": "onboarded",
        "onboarding_notes": "Phase 2 Generalization - Fully validated",
    },
    {
        "company_id": "tatasteel_tatasteel",
        "ticker": "TATASTEEL",
        "name": "Tata Steel Limited",
        "market": "india",
        "exchange": "NSE",
        "sector": "Metals & Mining",
        "industry": "Steel & Iron Products",
        "onboarding_status": "onboarded",
        "onboarding_notes": "Phase 2 Generalization - Fully validated",
    },
    # --- Additional Target India Non-Financials ---
    {
        "company_id": "wipro_infy",
        "ticker": "WIPRO",
        "name": "Wipro Limited",
        "market": "india",
        "exchange": "NSE",
        "sector": "Information Technology",
        "industry": "IT Services",
        "onboarding_status": "not_yet_attempted",
    },
    {
        "company_id": "hcltech_infy",
        "ticker": "HCLTECH",
        "name": "HCL Technologies Limited",
        "market": "india",
        "exchange": "NSE",
        "sector": "Information Technology",
        "industry": "IT Services",
        "onboarding_status": "not_yet_attempted",
    },
    {
        "company_id": "lt_infy",
        "ticker": "LT",
        "name": "Larsen & Toubro Limited",
        "market": "india",
        "exchange": "NSE",
        "sector": "Capital Goods",
        "industry": "Engineering & Construction",
        "onboarding_status": "not_yet_attempted",
    },
    {
        "company_id": "sunpharma_infy",
        "ticker": "SUNPHARMA",
        "name": "Sun Pharmaceutical Industries Limited",
        "market": "india",
        "exchange": "NSE",
        "sector": "Healthcare",
        "industry": "Pharmaceuticals",
        "onboarding_status": "not_yet_attempted",
    },
    # --- Financial Excluded India Samples (to verify filter) ---
    {
        "company_id": "hdfcbank_infy",
        "ticker": "HDFCBANK",
        "name": "HDFC Bank Limited",
        "market": "india",
        "exchange": "NSE",
        "sector": "Financial Services",
        "industry": "Private Sector Bank",
        "onboarding_status": "not_yet_attempted",
    },
    {
        "company_id": "icicibank_infy",
        "ticker": "ICICIBANK",
        "name": "ICICI Bank Limited",
        "market": "india",
        "exchange": "NSE",
        "sector": "Financial Services",
        "industry": "Private Sector Bank",
        "onboarding_status": "not_yet_attempted",
    },
    # --- Onboarded US Companies ---
    {
        "company_id": "aapl_us",
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "market": "us",
        "exchange": "NASDAQ",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "onboarding_status": "onboarded",
        "onboarding_notes": "Phase 3 US Expansion - Fully validated",
    },
    {
        "company_id": "msft_us",
        "ticker": "MSFT",
        "name": "Microsoft Corporation",
        "market": "us",
        "exchange": "NASDAQ",
        "sector": "Technology",
        "industry": "Software - Infrastructure",
        "onboarding_status": "onboarded",
        "onboarding_notes": "Phase 3 US Expansion - Fully validated",
    },
    {
        "company_id": "infy_us",
        "ticker": "INFY",
        "name": "Infosys Limited (NYSE ADR)",
        "market": "us",
        "exchange": "NYSE",
        "sector": "Technology",
        "industry": "IT Services",
        "onboarding_status": "onboarded",
        "onboarding_notes": "Phase 3 US Expansion - Fully validated",
    },
    # --- Additional Target US Non-Financials ---
    {
        "company_id": "nvda_us",
        "ticker": "NVDA",
        "name": "NVIDIA Corporation",
        "market": "us",
        "exchange": "NASDAQ",
        "sector": "Technology",
        "industry": "Semiconductors",
        "onboarding_status": "not_yet_attempted",
    },
    {
        "company_id": "googl_us",
        "ticker": "GOOGL",
        "name": "Alphabet Inc.",
        "market": "us",
        "exchange": "NASDAQ",
        "sector": "Communication Services",
        "industry": "Internet Content & Information",
        "onboarding_status": "not_yet_attempted",
    },
    {
        "company_id": "amzn_us",
        "ticker": "AMZN",
        "name": "Amazon.com, Inc.",
        "market": "us",
        "exchange": "NASDAQ",
        "sector": "Consumer Cyclical",
        "industry": "Internet Retail",
        "onboarding_status": "not_yet_attempted",
    },
    # --- Financial Excluded US Samples (to verify filter) ---
    {
        "company_id": "jpm_us",
        "ticker": "JPM",
        "name": "JPMorgan Chase & Co.",
        "market": "us",
        "exchange": "NYSE",
        "sector": "Financial Services",
        "industry": "Banks - Diversified",
        "onboarding_status": "not_yet_attempted",
    },
]


def seed_master_universe(db_path: str | Path = DB_PATH) -> list[UniverseCompany]:
    """Seed SQLite company universe table and perform sanity check validation."""
    companies: list[UniverseCompany] = []

    for item in SEED_COMPANIES:
        is_fin, _ = is_financial_sector(item["sector"], item["industry"])
        c = UniverseCompany(
            company_id=item["company_id"],
            ticker=item["ticker"],
            name=item["name"],
            market=item["market"],
            exchange=item["exchange"],
            sector=item["sector"],
            industry=item["industry"],
            is_financial=is_fin,
            onboarding_status=item["onboarding_status"],
            onboarding_notes=item.get("onboarding_notes"),
            last_updated=datetime.now(),
        )
        companies.append(c)

    save_universe_companies(companies, db_path=db_path)

    # Sanity checks
    for cid in ["infy_infy", "tcs_tcs", "tatamotors_tatamotors", "tatasteel_tatasteel", "aapl_us", "msft_us", "infy_us"]:
        fetched = get_universe_company(cid, db_path=db_path)
        assert fetched is not None, f"Sanity check failed: {cid} not found in universe db"
        assert fetched.onboarding_status == "onboarded", f"Sanity check failed: {cid} not onboarded"

    return companies
