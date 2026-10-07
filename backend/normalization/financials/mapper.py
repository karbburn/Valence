from __future__ import annotations

from pathlib import Path

from backend.data.pipeline import DB_PATH
from backend.data.store import RawDatapoint
from backend.normalization.taxonomy.models import CanonicalDatapoint, TaxonomyMapping
from backend.normalization.taxonomy.registry import (
    WITHDRAWN_LABELS,
    get_canonical_mapping,
)
from backend.validation.accounting_checks import CURRENT_ASSET_LINES

# The balance-sheet keys `current_assets_reconcile` treats as current. Imported
# rather than restated, so the two lists cannot drift apart -- the reconciliation
# summing a different set from the mapper's notion of current is the same defect
# wearing a different name.
_CURRENT_ASSET_KEYS = frozenset(
    "canonical.bs." + line.replace("canonical.bs.", "")
    for line in CURRENT_ASSET_LINES
)
from backend.normalization.taxonomy.mapping_engine import (
    suggest_canonical_mapping,
    route_to_review_queue,
)


def _half_agrees(bs_half: str | None, canonical_key: str | None) -> bool:
    """True when a caption's printed half of the balance sheet fits its canonical key.

    A filer may print one caption on both sides:

        Current assets      Unbilled revenue 15,483    Income tax assets 1,835
        Non-current assets  Unbilled revenue  1,738    Income tax assets   666

    Each pair reaches ONE canonical key, so the later row overwrites the earlier and
    the reader is shown the non-current figure as though it were the current one.

    Only the CURRENT-asset keys are claimed here. A non-current caption reaching a
    non-current key is not this defect and is left alone; the mapping registry is
    where that distinction belongs, and guessing at it would refuse filers whose
    statements group things differently.
    """
    if not bs_half or not canonical_key or not canonical_key.startswith("canonical.bs."):
        return True
    if canonical_key not in _CURRENT_ASSET_KEYS:
        # Not a line the reconciliation calls current -- a subtotal, a liability, an
        # equity line. Whether a caption belongs in it is the registry's business,
        # and this check makes no claim about it.
        return True
    return bs_half == "current"


def _key_for_half(canonical_key: str, bs_half: str | None) -> str:
    """Move a caption printed in one half of the balance sheet to that half's key.

    "Income tax assets" appears on both sides of Infosys' balance sheet -- 1,835
    current and 666 non-current -- and the registry gives both the same key,
    `income_tax_assets`, which is not one of the lines the reconciliation sums. So
    the current caption was published under a key that no current-asset total
    contains, which is an under-count that reconciles against nothing.

    The reader knows which half it parsed, so the current half is routed to the
    current key. The non-current half keeps the existing key, which is where it
    already went and where `total_non_current_assets` can find it.

    Narrow on purpose: only this pair, because only this pair is observed to be
    printed on both sides. Generalising it would invent a naming convention.
    """
    if bs_half == "current" and canonical_key == "canonical.bs.income_tax_assets":
        return "canonical.bs.current_income_tax_assets"
    return canonical_key


def _statement_agrees(section: str | None, statement: str | None) -> bool:
    """True when a caption's printed statement is the one it is being mapped into.

    `None` on either side means no claim is being made -- a reader with no notion of
    statements, or a mapping with no statement -- and absence of evidence is not
    evidence of disagreement, so those pass. Only an explicit, positive mismatch is
    refused.

    The readers spell statements long ("CASH FLOW", "CASH FLOW:") and the registry
    spells them short ("cf"), so both are normalised to a single code before being
    compared. Substring matching is deliberately NOT used: "is" is a substring of
    "BALANCE SHEET"-adjacent text and "cf" of nothing useful, so a reader that
    "matched" would happily accept a profit-and-loss caption as a balance-sheet one.
    """
    if not section or not statement:
        return True

    LONG_TO_CODE = {
        "BALANCE SHEET": "bs",
        "CASH FLOW": "cf",
        "PROFIT & LOSS": "is",
        "PROFIT AND LOSS": "is",
        "INCOME STATEMENT": "is",
    }
    left = section.upper().split(":")[0].strip()
    # The registry stores short codes in lower case, so `right` must be lowered too.
    # Upper-casing it here made "bs" into "BS" and every positive case failed --
    # which would have refused EVERY cross-statement mapping in the wrong direction,
    # silently emptying balance sheets rather than protecting them.
    right = str(statement).strip().lower()
    return LONG_TO_CODE.get(left, left) == right


def map_raw_datapoints(
    raw_datapoints: list[RawDatapoint],
    include_superseded: bool = False,
    use_confidence_engine: bool = True,
    db_path: str | Path = DB_PATH,
) -> tuple[list[CanonicalDatapoint], list[TaxonomyMapping], list[str]]:
    """Map raw datapoints to canonical datapoints and taxonomy mapping records.

    Exact registry matches are always applied. When ``use_confidence_engine`` is
    enabled, unmapped labels fall back to the confidence-scored mapping engine:
    high-confidence suggestions are auto-accepted, medium-confidence ones are
    accepted but flagged ``human_confirmed=False`` for review, and low-confidence
    labels are routed to the review queue and returned as unmapped.

    ``db_path`` is the store the review queue is written to; it defaults to the
    shared one so tests can point the queue at a database of their own instead
    of writing fixture rows into the live store.

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

        # A withdrawal outranks a suggestion.
        #
        # Removing a label from RAW_METRIC_MAP is not a withdrawal on its own: the
        # confidence engine below proposes these labels at MEDIUM confidence, and a
        # medium suggestion is accepted. So "Investments" and "Other Assets" were
        # still being mapped after being deliberately unmapped -- the aggregate
        # merely moved keys (21,880 published as NON-current investments against a
        # filed 8,930) and the double count outlived the fix meant to end it.
        #
        # These labels are routed to review and counted as neither mapped nor
        # unmapped: the decision is recorded, so failing the build over it would
        # report a known-and-accepted gap as a fresh one, while leaving the value in
        # the model would state something the engine does not know.
        if mapping is None and d.metric_raw in WITHDRAWN_LABELS:
            key = (d.company_id, d.metric_raw)
            if key not in queued_for_review:
                route_to_review_queue(
                    d.company_id,
                    d.metric_raw,
                    suggest_canonical_mapping(d.metric_raw),
                    db_path=db_path,
                )
                queued_for_review.add(key)
            continue

        if mapping is None and use_confidence_engine:
            suggestion = suggest_canonical_mapping(d.metric_raw)
            if suggestion.level in ("high", "medium") and suggestion.canonical_key is not None:
                mapping = (suggestion.canonical_key, suggestion.statement)
                human_confirmed = suggestion.level == "high"
            elif suggestion.level == "low":
                key = (d.company_id, d.metric_raw)
                if key not in queued_for_review:
                    route_to_review_queue(
                        d.company_id, d.metric_raw, suggestion, db_path=db_path
                    )
                    queued_for_review.add(key)
                unmapped_labels.add(d.metric_raw)

        if mapping is None:
            unmapped_labels.add(d.metric_raw)
            continue

        canonical_key, statement = mapping
        canonical_key = _key_for_half(canonical_key, d.bs_half)

        # A caption may not become a line of a statement it was not printed in, or of
        # a half of the balance sheet it was not printed under.
        #
        # Infosys prints "Prepayments and other assets" in its CASH FLOW statement as
        # a working-capital movement, and "Prepayments and other current assets" on
        # its balance sheet as a stock. The two share a stem and the cash-flow page is
        # parsed second, so the movement overwrote the stock and the model published
        # -2,312 as a balance-sheet asset where the filing says +15,703.
        #
        # Refusing the mapping is the fix; ordering alone would only hide which of the
        # two happened to win.
        #
        # A REFUSAL IS NOT AN UNMAPPED LABEL, and conflating the two fails builds for
        # the wrong reason. The cash-flow page also carries the note breaking down
        # "Fair value changes on investments, net" -- "- Quoted debt securities",
        # "- Mutual fund units", "- Certificates of deposit" and five more. Every one
        # of those is correctly refused, and a filing containing notes is normal
        # rather than an error, so counting them as unmapped made Infosys answer 422
        # for having notes. They are declined and queued; only a caption the engine
        # has no mapping for at all is reported unmapped.
        if not _statement_agrees(d.section, statement) or not _half_agrees(
            d.bs_half, canonical_key
        ):
            if use_confidence_engine:
                key = (d.company_id, d.metric_raw)
                if key not in queued_for_review:
                    route_to_review_queue(
                        d.company_id,
                        d.metric_raw,
                        suggest_canonical_mapping(d.metric_raw),
                        db_path=db_path,
                    )
                    queued_for_review.add(key)
            continue

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
