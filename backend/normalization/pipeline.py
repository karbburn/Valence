from __future__ import annotations

import logging
from pathlib import Path

from backend.data.store import (
    connect,
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

logger = logging.getLogger(__name__)


def run(company_id: str = "infy_infy", db_path=None) -> dict:
    """Run Taxonomy Normalization pipeline for a target company.

    `db_path` defaults to the module-level store. It is a parameter because the caller
    already has one: `ensure_company_ingested(db_path=...)` passes a store down to the
    ingestion step, and before this existed that argument was silently ignored here --
    raw rows went to the store the caller named and canonical rows went to the global one.
    A caller testing against a copy therefore mutated the LIVE database while believing it
    was working on the copy, which is how a test of the failure path nearly destroyed the
    data it was supposed to be protecting.
    """
    target = Path(db_path) if db_path is not None else DB_PATH
    if not target.exists():
        raise FileNotFoundError(
            f"Database not found at {target}. Run data ingestion pipeline first.")

    # Fetch all non-superseded winning raw datapoints
    raw_dps = query_datapoints(target, company_id)
    winning_raw_dps = [d for d in raw_dps if d.superseded_by_id is None]

    # Map raw labels to canonical taxonomy
    canonical_dps, taxonomy_mappings, unmapped_labels = map_raw_datapoints(winning_raw_dps)

    # An unmapped caption is a COVERAGE GAP, and it is recorded rather than fatal.
    #
    # This raised, and the raise was a forcing function for taxonomy work. It became a
    # shipping defect the moment the NSE fetcher's located pages actually reached this
    # stage: TCS's audited balance sheet contributes 174 rows carrying 9 captions the
    # taxonomy has no entry for, and the whole ingest failed. Two companies that ingested
    # cleanly from the market feed a moment earlier could not be ingested at all, so a
    # breadth improvement would have shipped as a regression.
    #
    # Nothing is lost by continuing. Every unmapped label is already written to the review
    # queue inside `map_raw_datapoints` before it is reported here, so the gap is durable
    # and queryable rather than something a stack trace carried away.
    #
    # And the guard that actually protects the numbers is downstream and is not this one.
    # A balance sheet missing lines of itself does not foot, so `current_assets_reconcile`
    # compares the sum of what was kept against the filer's own printed subtotal and FAILS,
    # naming the gap. That is the check written for exactly this, and it fails the model
    # rather than the build. Verified rather than assumed: the two companies named below
    # were ingested after this change and their reconcile outcome was read directly.
    if unmapped_labels:
        logger.warning(
            "%s: %d caption(s) have no canonical mapping and were left out of the "
            "canonical layer. They are in the review queue. The statements they came from "
            "will not foot, and the reconciliation check will say so: %s",
            company_id, len(unmapped_labels), unmapped_labels,
        )

    # Apply derivation rules (e.g. EBITDA)
    derived_dps = derive_canonical_metrics(canonical_dps)
    all_canonical_dps = canonical_dps + derived_dps

    # Validate currencies and units based on company metadata
    from backend.models.spec.metadata import get_metadata_for_company
    meta = get_metadata_for_company(company_id)
    currency_val = validate_currencies_and_units(
        all_canonical_dps,
        expected_currency=meta.currency,
        expected_units=meta.units,
    )
    if not currency_val["is_valid"]:
        raise ValueError(f"Currency/Units validation failed for {company_id}: {currency_val['inconsistent_datapoints']}")

    # Validate fiscal period alignment
    period_val = align_fiscal_periods(all_canonical_dps)
    if not period_val["is_aligned"]:
        raise ValueError(f"Fiscal period alignment failed: {period_val['misaligned_datapoints']}")

    # Save canonical datapoints and taxonomy mappings atomically: a failure in either
    # write rolls back both so the DB never ends up with canonical data without its
    # mappings (or vice-versa).
    conn = connect(target)
    try:
        save_canonical_datapoints(target, all_canonical_dps, conn=conn)
        save_taxonomy_mappings(target, taxonomy_mappings, conn=conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    summary = {
        "raw_winning_count": len(winning_raw_dps),
        "canonical_reported_count": len(canonical_dps),
        "canonical_derived_count": len(derived_dps),
        "total_canonical_count": len(all_canonical_dps),
        "taxonomy_mappings_count": len(taxonomy_mappings),
        "unmapped_labels_count": len(unmapped_labels),
        # The captions themselves, not only how many. A count tells a reader that
        # something is missing; the names tell whoever fixes it what to open.
        "unmapped_labels": list(unmapped_labels),
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
