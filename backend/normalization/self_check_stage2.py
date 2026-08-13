from __future__ import annotations

from backend.data.store import (
    get_taxonomy_mappings,
    query_canonical_datapoints,
)
from backend.normalization.pipeline import DB_PATH, run

COMPANY_ID = "infy_infy"


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"Normalization self-check FAILED: {msg}")
    print(f"ok: {msg}")


def _find_canon(rows, canonical_key, period):
    for d in rows:
        if d.canonical_key == canonical_key and d.period_label == period:
            return d
    return None


def main() -> None:
    print("Running Normalization Pipeline...")
    summary = run(COMPANY_ID)

    _assert(summary["unmapped_labels_count"] == 0, "Zero unmapped raw labels")
    _assert(summary["total_canonical_count"] > 0, f"Canonical datapoints generated ({summary['total_canonical_count']})")
    _assert(summary["taxonomy_mappings_count"] > 0, f"Taxonomy mappings stored ({summary['taxonomy_mappings_count']})")

    # Fetch stored records from valence.db
    canonical_dps = query_canonical_datapoints(DB_PATH, COMPANY_ID)
    mappings = get_taxonomy_mappings(DB_PATH, COMPANY_ID)

    # 1. Mappings human-confirmed assertion
    all_human_confirmed = all(m.human_confirmed for m in mappings)
    _assert(all_human_confirmed, "All taxonomy mappings are human_confirmed = True")

    # 2. Lineage assertion
    all_have_lineage = all(len(d.source_datapoint_ids) > 0 for d in canonical_dps)
    _assert(all_have_lineage, "All canonical datapoints have source lineage IDs")

    # 3. Revenue check across FY26, FY25, FY24
    for period in ("FY26", "FY25", "FY24"):
        rev = _find_canon(canonical_dps, "canonical.is.revenue", period)
        _assert(rev is not None, f"Revenue present for {period} ({rev.value if rev else 'N/A'} Cr)")

    # 4. Derived EBITDA check across FY26, FY25, FY24
    for period in ("FY26", "FY25", "FY24"):
        ebitda = _find_canon(canonical_dps, "canonical.is.ebitda", period)
        _assert(ebitda is not None, f"EBITDA derived for {period} ({ebitda.value if ebitda else 'N/A'} Cr)")
        _assert(ebitda.status == "derived", f"{period} EBITDA status is 'derived'")
        _assert(ebitda.derivation_rule is not None, f"{period} EBITDA derivation rule attached ({ebitda.derivation_rule})")

    # 5. Balance Sheet equality check for canonical keys
    for period in ("FY26", "FY25"):
        assets = _find_canon(canonical_dps, "canonical.bs.total_assets", period)
        liab_eq = _find_canon(canonical_dps, "canonical.bs.total_liabilities_and_equity", period)
        if assets and liab_eq:
            _assert(abs(assets.value - liab_eq.value) <= 1.0, f"Canonical Balance Sheet balances for {period} ({assets.value} vs {liab_eq.value})")

    print("\nALL NORMALIZATION SELF-CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()

