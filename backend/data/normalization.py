from __future__ import annotations

# Canonical metric vocabulary so the two sources (Screener vs regulated filing)
# reconcile on meaning, not on vendor-specific wording.

_CANON = {
    "sales": "revenue",
    "revenues": "revenue",
    "profit before tax": "pbt",
    "profit before income taxes": "pbt",
    "tax": "tax",
    "income tax expense": "tax",
    "net profit": "net_profit",
    "interest": "finance_cost",
    "finance cost": "finance_cost",
    "other income": "other_income",
    "other income, net": "other_income",
    "receivables": "trade_receivables",
    "trade receivables": "trade_receivables",
    "cash & bank": "cash_and_bank",
    "cash and cash equivalents": "cash_and_bank",
}


def canonical(metric_raw: str) -> str:
    return _CANON.get(metric_raw.strip().lower(), metric_raw.strip().lower())
