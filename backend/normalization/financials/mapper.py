from __future__ import annotations

from backend.data.store import RawDatapoint
from backend.normalization.taxonomy.models import CanonicalDatapoint, TaxonomyMapping
from backend.normalization.taxonomy.registry import get_canonical_mapping
from backend.normalization.taxonomy.mapping_engine import (
    suggest_canonical_mapping,
    route_to_review_queue,
)


def map_raw_datapoints(
    raw_datapoints: list[RawDatapoint],
    include_superseded: bool = False,
    use_confidence_engine: bool = True,
) -> tuple[list[CanonicalDatapoint], list[TaxonomyMapping], list[str]]:
    """Map raw datapoints to canonical datapoints and taxonomy mapping records.

    Exact registry matches are always applied. When ``use_confidence_engine`` is
    enabled, unmapped labels fall back to the confidence-scored mapping engine:
    high-confidence suggestions are auto-accepted, medium-confidence ones are
    accepted but flagged ``human_confirmed=False`` for review, and low-confidence
    labels are routed to the review queue and returned as unmapped.

    Returns:
        (canonical_datapoints, taxonomy_mappings, unmapped_raw_labels)
    """
    canonical_datapoints: list[CanonicalDatapoint] = []
    taxonomy_mappings_dict: dict[tuple[str, str], TaxonomyMapping] = {}
    unmapped_labels: set[str] = set()
    queued_for_review: set[tuple[str, str]] = set()

    for d in raw_datapoints:
        if not include_superseded and d.superseded_by_id is not None:
            continue

        mapping = get_canonical_mapping(d.metric_raw)
        human_confirmed = True
        if mapping is None and use_confidence_engine:
            suggestion = suggest_canonical_mapping(d.metric_raw)
            if suggestion.level in ("high", "medium") and suggestion.canonical_key is not None:
                mapping = (suggestion.canonical_key, suggestion.statement)
                human_confirmed = suggestion.level == "high"
            elif suggestion.level == "low":
                key = (d.company_id, d.metric_raw)
                if key not in queued_for_review:
                    route_to_review_queue(d.company_id, d.metric_raw, suggestion)
                    queued_for_review.add(key)
                unmapped_labels.add(d.metric_raw)

        if mapping is None:
            unmapped_labels.add(d.metric_raw)
            continue

        canonical_key, statement = mapping

        # Build Canonical Datapoint
        #
        # The raw datapoint's status is carried through unchanged. It used to be
        # collapsed to a binary here -- anything that was not "reported_adjusted"
        # became "reported" -- so a raw row an ingestion reader had deliberately
        # marked `estimated` arrived at the canonical layer claiming to have been
        # read from a filing. That is how eight companies' hand-entered fixture
        # figures reached the workbook labelled `reported`: the screener reader knew
        # what they were, and this line threw that away on the way through.
        #
        # Every consumer that wants to know whether a figure is filed must now read
        # the status rather than assume it, because this was the one place that
        # guaranteed the assumption held.
        status = d.status
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
                human_confirmed=human_confirmed,
            )
            taxonomy_mappings_dict[map_key] = tax_map

    return canonical_datapoints, list(taxonomy_mappings_dict.values()), sorted(unmapped_labels)
