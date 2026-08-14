from __future__ import annotations

"""
Universe Acquisition Module for Valence.

Acquires listing data across Indian exchanges (NSE/BSE) and US SEC EDGAR (company_tickers.json),
applies non-financial sector filtering, and enforces canonical company_id uniqueness.
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

from backend.data.pipeline import DB_PATH
from backend.data.universe.models import UniverseCompany
from backend.data.universe.sector_filter import is_financial_sector
from backend.data.universe.store import save_universe_companies

logger = logging.getLogger(__name__)

SEC_HEADERS = {
    "User-Agent": "ValencePlatform team@valence.com",
    "Accept-Encoding": "gzip, deflate",
}

# Standard India Universe Seed Listing
INDIA_LISTINGS: List[Dict[str, str]] = [
    {"symbol": "INFY", "name": "Infosys Limited", "sector": "Information Technology", "industry": "IT Services & Consulting"},
    {"symbol": "TCS", "name": "Tata Consultancy Services Limited", "sector": "Information Technology", "industry": "IT Services & Consulting"},
    {"symbol": "TATAMOTORS", "name": "Tata Motors Limited", "sector": "Automotive", "industry": "Automobiles"},
    {"symbol": "TATASTEEL", "name": "Tata Steel Limited", "sector": "Metals & Mining", "industry": "Steel & Iron Products"},
    {"symbol": "WIPRO", "name": "Wipro Limited", "sector": "Information Technology", "industry": "IT Services"},
    {"symbol": "HCLTECH", "name": "HCL Technologies Limited", "sector": "Information Technology", "industry": "IT Services"},
    {"symbol": "LT", "name": "Larsen & Toubro Limited", "sector": "Capital Goods", "industry": "Engineering & Construction"},
    {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Limited", "sector": "Healthcare", "industry": "Pharmaceuticals"},
    {"symbol": "RELIANCE", "name": "Reliance Industries Limited", "sector": "Energy", "industry": "Oil & Gas / Conglomerate"},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Limited", "sector": "Telecommunication", "industry": "Telecom Services"},
    {"symbol": "ITC", "name": "ITC Limited", "sector": "Consumer Goods", "industry": "FMCG"},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Limited", "sector": "Financial Services", "industry": "Private Sector Bank"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Limited", "sector": "Financial Services", "industry": "Private Sector Bank"},
]


def acquire_india_universe() -> List[UniverseCompany]:
    """Acquire and normalize Indian listed companies into UniverseCompany records."""
    companies: List[UniverseCompany] = []
    now = datetime.now()

    for item in INDIA_LISTINGS:
        sym = item["symbol"].strip().upper()
        cid = f"{sym.lower()}_{sym.lower()}"
        is_fin, reason = is_financial_sector(item["sector"], item["industry"])

        c = UniverseCompany(
            company_id=cid,
            ticker=sym,
            name=item["name"],
            market="india",
            exchange="NSE",
            sector=item["sector"],
            industry=item["industry"],
            is_financial=is_fin,
            onboarding_status="onboarded" if cid in ("infy_infy", "tcs_tcs", "tatamotors_tatamotors", "tatasteel_tatasteel") else "not_yet_attempted",
            onboarding_notes=f"Acquired via India Universe Listing ({reason})",
            last_updated=now,
        )
        companies.append(c)

    return companies


def acquire_us_universe() -> List[UniverseCompany]:
    """Acquire full US SEC EDGAR filers via company_tickers.json."""
    companies: List[UniverseCompany] = []
    now = datetime.now()

    url = "https://www.sec.gov/files/company_tickers.json"
    time.sleep(0.1)

    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            for entry in data.values():
                ticker = entry.get("ticker", "").strip().upper()
                name = entry.get("title", "").strip()
                if not ticker or not name:
                    continue

                cid = f"{ticker.lower()}_us"
                # Determine financial filter from title keywords
                is_fin, reason = is_financial_sector("Technology", name)

                c = UniverseCompany(
                    company_id=cid,
                    ticker=ticker,
                    name=name,
                    market="us",
                    exchange="SEC_EDGAR",
                    sector="General",
                    industry="General",
                    is_financial=is_fin,
                    onboarding_status="onboarded" if cid in ("aapl_us", "msft_us", "infy_us") else "not_yet_attempted",
                    onboarding_notes=f"Acquired via SEC company_tickers.json (CIK: {entry.get('cik_str')})",
                    last_updated=now,
                )
                companies.append(c)
    except Exception as e:
        logger.warning("Failed SEC company_tickers fetch: %s", e)

    # Fallback default US seed companies if offline
    if not companies:
        us_defaults = [
            ("AAPL", "Apple Inc.", "Technology", "Consumer Electronics", "aapl_us"),
            ("MSFT", "Microsoft Corporation", "Technology", "Software - Infrastructure", "msft_us"),
            ("INFY", "Infosys Limited (NYSE ADR)", "Technology", "IT Services", "infy_us"),
            ("NVDA", "NVIDIA Corporation", "Technology", "Semiconductors", "nvda_us"),
            ("GOOGL", "Alphabet Inc.", "Communication Services", "Internet Content & Information", "googl_us"),
            ("AMZN", "Amazon.com, Inc.", "Consumer Cyclical", "Internet Retail", "amzn_us"),
            ("JPM", "JPMorgan Chase & Co.", "Financial Services", "Banks - Diversified", "jpm_us"),
        ]
        for ticker, name, sec, ind, cid in us_defaults:
            is_fin, reason = is_financial_sector(sec, ind)
            companies.append(
                UniverseCompany(
                    company_id=cid,
                    ticker=ticker,
                    name=name,
                    market="us",
                    exchange="NASDAQ" if ticker != "JPM" else "NYSE",
                    sector=sec,
                    industry=ind,
                    is_financial=is_fin,
                    onboarding_status="onboarded" if cid in ("aapl_us", "msft_us", "infy_us") else "not_yet_attempted",
                    onboarding_notes="Acquired via US default seed",
                    last_updated=now,
                )
            )

    return companies


def acquire_full_universe(db_path: str | Path = DB_PATH) -> List[UniverseCompany]:
    """Acquire full universe (India + US), enforce company_id uniqueness, and persist to store."""
    from backend.data.universe.store import clean_corrupted_legacy_universe_ids, save_universe_companies

    clean_corrupted_legacy_universe_ids(db_path=db_path)
    india_c = acquire_india_universe()
    us_c = acquire_us_universe()

    all_companies = india_c + us_c

    # Deduplicate by company_id (keep first)
    seen: Dict[str, UniverseCompany] = {}
    for c in all_companies:
        if c.company_id not in seen:
            seen[c.company_id] = c

    unique_companies = list(seen.values())
    save_universe_companies(unique_companies, db_path=db_path)
    return unique_companies
