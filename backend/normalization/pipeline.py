from __future__ import annotations

from pathlib import Path

from backend.data.store import (
    query_datapoints,
    save_canonical_datapoints,
    save_taxonomy_mappings,
)
from backend.normalization.currencies.validator import validate_currencies_and_units
from backend.normalization.financials.derivation import derive_canonical_metrics
from backend.normalization.financials.mapper import map_raw_datapoints
from backend.normalization.fiscal_periods.aligner import align_fiscal_periods

HERE = Path(__file__).resolve().parent
WORKSPACE_ROOT = HERE.parent.parent
DB_PATH = WORKSPACE_ROOT / "backend" / "data" / "valence.db"
COMPANY_ID = "infy_infy"


def run(company_id: str = "infy_infy") -> dict:
    """Run Taxonomy Normalization pipeline for a target company."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}. Run data ingestion pipeline first.")

    # Fetch all non-superseded winning raw datapoints
    raw_dps = query_datapoints(DB_PATH, company_id)
    winning_raw_dps = [d for d in raw_dps if d.superseded_by_id is None]

    # Map raw labels to canonical taxonomy
    canonical_dps, taxonomy_mappings, unmapped_labels = map_raw_datapoints(winning_raw_dps)

    if unmapped_labels:
        raise ValueError(f"Normalization failed: {len(unmapped_labels)} unmapped labels found: {unmapped_labels}")

    # Apply derivation rules (e.g. EBITDA)
    derived_dps = derive_canonical_metrics(canonical_dps)
    all_canonical_dps = canonical_dps + derived_dps

    # Validate currencies and units
    currency_val = validate_currencies_and_units(all_canonical_dps)
    if not currency_val["is_valid"]:
        raise ValueError(f"Currency/Units validation failed: {currency_val['inconsistent_datapoints']}")

    # Validate fiscal period alignment
    period_val = align_fiscal_periods(all_canonical_dps)
    if not period_val["is_aligned"]:
        raise ValueError(f"Fiscal period alignment failed: {period_val['misaligned_datapoints']}")

    # Save canonical datapoints and taxonomy mappings to valence.db
    save_canonical_datapoints(DB_PATH, all_canonical_dps)
    save_taxonomy_mappings(DB_PATH, taxonomy_mappings)

    summary = {
        "raw_winning_count": len(winning_raw_dps),
        "canonical_reported_count": len(canonical_dps),
        "canonical_derived_count": len(derived_dps),
        "total_canonical_count": len(all_canonical_dps),
        "taxonomy_mappings_count": len(taxonomy_mappings),
        "unmapped_labels_count": len(unmapped_labels),
    }

    print(
        f"Taxonomy Normalization Complete:\n"
        f"  - Winning Raw Datapoints : {summary['raw_winning_count']}\n"
        f"  - Canonical Reported     : {summary['canonical_reported_count']}\n"
        f"  - Canonical Derived      : {summary['canonical_derived_count']}\n"
        f"  - Total Canonical        : {summary['total_canonical_count']}\n"
        f"  - Taxonomy Mappings      : {summary['taxonomy_mappings_count']}\n"
        f"  - Unmapped Labels        : {summary['unmapped_labels_count']}"
    )

    return summary



if __name__ == "__main__":
    run()
