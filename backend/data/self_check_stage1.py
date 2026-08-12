from __future__ import annotations

import json
from pathlib import Path

from backend.data.normalization import canonical
from backend.data.store import query_datapoints
from backend.data.pipeline import DB_PATH, LOG_PATH, run


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"self-check FAILED: {msg}")
    print(f"ok: {msg}")


def _find(rows, metric_raw, period):
    for d in rows:
        if d.metric_raw == metric_raw and d.period_label == period:
            return d
    return None


def _find_canon(rows, canon, period):
    for d in rows:
        if canonical(d.metric_raw) == canon and d.period_label == period:
            return d
    return None


def main() -> None:
    run()

    screener = query_datapoints(DB_PATH, "infy_infy", source="screener")
    filing = query_datapoints(DB_PATH, "infy_infy", source="nse_filing")

    _assert(len(screener) > 0, f"screener rows ingested ({len(screener)})")
    _assert(len(filing) > 0, f"filing rows ingested ({len(filing)})")

    # Both sources in crores; FY26 revenue must agree.
    s_rev = _find_canon(screener, "revenue", "FY26")
    f_rev = _find_canon(filing, "revenue", "FY26")
    _assert(s_rev is not None and f_rev is not None, "FY26 revenue present in both sources")
    _assert(abs(s_rev.value - f_rev.value) <= 1.0, f"FY26 revenue reconciled ({s_rev.value} vs {f_rev.value})")

    # Balance sheet must balance for the filing (both years).
    for period in ("FY26", "FY25"):
        assets = _find(filing, "Total assets", period)
        liab = _find(filing, "Total liabilities and equity", period)
        if assets is not None and liab is not None:
            _assert(abs(assets.value - liab.value) <= 1.0, f"{period} balance sheet balances ({assets.value} vs {liab.value})")

    # Reconciliation: FY25 Net Profit must cross-match (screener vs filing).
    s_np = _find_canon(screener, "net_profit", "FY25")
    f_np = _find_canon(filing, "net_profit", "FY25")
    _assert(s_np is not None and f_np is not None, "FY25 Net Profit present in both sources")
    _assert(abs(s_np.value - f_np.value) <= 150.0, f"FY25 Net Profit reconciled ({s_np.value} vs {f_np.value})")

    # Reconciliation must flag at least one genuine cross-source drift.
    disc = json.loads(LOG_PATH.read_text())
    _assert(isinstance(disc, list) and len(disc) > 0, f"discrepancy log non-empty ({len(disc)} entries)")

    print("\nALL INGESTION SELF-CHECKS PASSED")


if __name__ == "__main__":
    main()
