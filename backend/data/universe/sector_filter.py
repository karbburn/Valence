from __future__ import annotations

from typing import Tuple

FINANCIAL_SIC_RANGES = [(6000, 6999)]  # SEC EDGAR Financials, Insurance, Real Estate

FINANCIAL_SECTOR_KEYWORDS = [
    "bank",
    "banking",
    "financial services",
    "nbfc",
    "insurance",
    "housing finance",
    "reit",
    "invit",
    "investment company",
    "asset management",
]


def is_financial_sector(
    sector: str,
    industry: str,
    sic_code: int | str | None = None,
) -> Tuple[bool, str]:
    """Classify if a company belongs to the financial sector based on explicit rules.

    Returns:
        (is_financial, reason_description)
    """
    if sic_code is not None:
        try:
            code_int = int(sic_code)
            for start, end in FINANCIAL_SIC_RANGES:
                if start <= code_int <= end:
                    return True, f"Excluded by SEC SIC code {code_int} (Range {start}-{end})"
        except ValueError:
            pass

    sec_lower = sector.lower().strip()
    ind_lower = industry.lower().strip()

    for kw in FINANCIAL_SECTOR_KEYWORDS:
        if kw in sec_lower or kw in ind_lower:
            return True, f"Excluded by financial keyword match '{kw}' in sector/industry ({sector} / {industry})"

    return False, "Included (Non-financial)"
