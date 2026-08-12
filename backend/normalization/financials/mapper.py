from __future__ import annotations

from backend.data.store import RawDatapoint
from backend.normalization.taxonomy.models import CanonicalDatapoint, TaxonomyMapping
from backend.normalization.taxonomy.registry import get_canonical_mapping


def map_raw_datapoints(
    raw_datapoints: list[RawDatapoint],
    include_superseded: bool = False,
) -> tuple[list[CanonicalDatapoint], list[TaxonomyMapping], list[str]]:
    """Map raw datapoints to canonical datapoints and taxonomy mapping records.

    Returns:
        (canonical_datapoints, taxonomy_mappings, unmapped_raw_labels)
    """
    canonical_datapoints: list[CanonicalDatapoint] = []
    taxonomy_mappings_dict: dict[tuple[str, str], TaxonomyMapping] = {}
    unmapped_labels: set[str] = set()

    for d in raw_datapoints:
        if not include_superseded and d.superseded_by_id is not None:
            continue

        mapping = get_canonical_mapping(d.metric_raw)
        if mapping is None:
            unmapped_labels.add(d.metric_raw)
            continue

        canonical_key, statement = mapping

        # Build Canonical Datapoint
        status = "reported_adjusted" if d.status == "reported_adjusted" else "reported"
        c_dp = CanonicalDatapoint(
            company_id=d.company_id,
            canonical_key=canonical_key,
            metric_raw=d.metric_raw,
            period_label=d.period_label,
            period_end_date=d.period_end_date,
            value=d.value,
            currency=d.currency,
            units=d.units,
            status=status,
            source_datapoint_ids=[d.id],
            derivation_rule=None,
        )
        canonical_datapoints.append(c_dp)

        # Build Taxonomy Mapping Record (deduped by (company_id, metric_raw))
        map_key = (d.company_id, d.metric_raw)
        if map_key not in taxonomy_mappings_dict:
            tax_map = TaxonomyMapping(
                company_id=d.company_id,
                canonical_key=canonical_key,
                metric_raw=d.metric_raw,
                statement=statement,
                source=d.source,
                human_confirmed=True,
            )
            taxonomy_mappings_dict[map_key] = tax_map

    return canonical_datapoints, list(taxonomy_mappings_dict.values()), sorted(unmapped_labels)
