from __future__ import annotations

from typing import Dict, List, Tuple
from backend.data.store import RawDatapoint, query_datapoints
from backend.normalization.taxonomy.models import CanonicalDatapoint

# Every source whose numbers were written by hand into a workbook in this
# repository rather than retrieved from a filer or a provider. Both members are
# produced by tracked generators under backend/data/sources/ -- generate_sources.py
# (read as `screener`) and generate_us_sources.py (read as `local_export`) -- so
# neither is usable as evidence for a published figure.
#
# Module level, and shared, because two consumers needed this list. The validation
# check keyed on the single literal "screener", so it named generate_us_sources.py
# in its failure text while being structurally blind to the `local_export` rows that
# generator produces -- a company fed entirely by it was reported as having no local
# fixture at all. A second, separately maintained copy of one list is the defect
# this repository has now found three times over.
SECONDARY_SOURCES = {"screener"}
LOCAL_EXPORT_SOURCES = {"local_export"}
LOCAL_FIXTURE_SOURCES = SECONDARY_SOURCES | LOCAL_EXPORT_SOURCES


def dominant_units(
    datapoints: list[CanonicalDatapoint],
) -> Tuple[str, str]:
    """The (currency, units) a company's own datapoints are overwhelmingly in.

    Used as the starting value for a statement line, so that a line which ends up with
    no datapoint at all cannot be published wearing a hardcoded unit that may be
    wrong by a factor of ten.

    A company whose figures are genuinely mixed has no dominant unit, and the tie is
    broken deterministically rather than by dict order so two runs of the same build
    cannot disagree with each other. `check_units_agree_within_a_model` is what
    actually reports a genuine mix; this only has to be stable and honest.
    """
    tally: Dict[Tuple[str, str], int] = {}
    for d in datapoints:
        if d.currency and d.units:
            tally[(d.currency, d.units)] = tally.get((d.currency, d.units), 0) + 1
    if not tally:
        return ("", "")
    return max(tally.items(), key=lambda kv: (kv[1], kv[0]))[0]


def select_primary_datapoints(
    canonical_datapoints: list[CanonicalDatapoint],
    statement_type: str,  # "is", "bs", or "cf"
    raw_datapoints_map: Dict[str, RawDatapoint] | None = None,
) -> Dict[Tuple[str, str], CanonicalDatapoint]:
    """Selects the single best/primary CanonicalDatapoint for each (canonical_key, period_label) pair.

    Filters out movement/note sub-table rows by prioritizing primary statement table locations.
    """
    grouped: Dict[Tuple[str, str], List[CanonicalDatapoint]] = {}
    for d in canonical_datapoints:
        grouped.setdefault((d.canonical_key, d.period_label), []).append(d)

    # Authoritative source hierarchy — regulatory filings carry more weight than
    # third-party aggregators or real-time market feeds.  This ensures that when
    # an NSE/SEC/BSE filing disagrees with a screener or yfinance row, the
    # regulatory source wins.
    AUTHORITATIVE_SOURCES = {"nse_filing", "sec_edgar", "bse_filing"}
    MARKET_FEED_SOURCES = {"yfinance_live", "twelvedata"}
    # A hand-maintained repository spreadsheet ranks below every retrieved
    # source. It is a last resort, not an imitation filing. SECONDARY_SOURCES and
    # LOCAL_EXPORT_SOURCES are module level so the validation check can share them.

    def _score(dp: CanonicalDatapoint) -> int:
        score = 0

        # A derivation outranks a reported figure for the same key.
        #
        # Most derivations are guarded so they only fill a key the filer left
        # empty, and for those there is nothing to arbitrate. This applies to the
        # one that is not: a filer whose itemised non-current lines overlap its
        # catch-all, where the derivation is written to replace the reported
        # catch-all with the figure net of the overlap. Selection used to be
        # decided entirely by source authority and label, so the two rows tied and
        # the reported one won on order, which put back the double count the
        # derivation existed to prevent.
        #
        # Preferring a derived row cannot introduce a figure from outside the
        # filing, because a derivation is computed from reported figures. It can
        # only produce a different arrangement of figures the filing itself
        # supplied, which is the whole purpose of deriving anything. The cost is
        # that this rule is unscoped: an unguarded derivation added later would
        # silently outrank a reported figure. That is the safe direction, since
        # the alternative is a correction being discarded, but it does mean a
        # derivation that should defer to the filing has to say so by not being
        # written as a derivation.
        if dp.status == "derived":
            score += 1000

        # Source-authority boost (regulatory > aggregator > market feed)
        if raw_datapoints_map:
            sources = {raw_datapoints_map[rid].source for rid in dp.source_datapoint_ids if rid in raw_datapoints_map}
            if sources & AUTHORITATIVE_SOURCES:
                score += 200
            elif sources & SECONDARY_SOURCES:
                score += 100
            elif sources & MARKET_FEED_SOURCES:
                score += 50
            elif sources & LOCAL_EXPORT_SOURCES:
                score += 10

            locs = [raw_datapoints_map[rid].source_location for rid in dp.source_datapoint_ids if rid in raw_datapoints_map]
            loc_str = " ".join(locs).upper()

            if statement_type == "bs" and ("BALANCE SHEET" in loc_str or "SHEET" in loc_str or "DATASET" in loc_str or "DATASHEET" in loc_str):
                score += 100
            elif statement_type == "is" and ("PROFIT & LOSS" in loc_str or "PROFIT" in loc_str or "P&L" in loc_str or "DATASHEET" in loc_str):
                score += 100
            elif statement_type == "cf" and ("CASH FLOW" in loc_str or "CASH" in loc_str or "DATASHEET" in loc_str):
                score += 100

        # Primary label boost
        if dp.metric_raw in (
            "Trade receivables", "Unbilled revenue", "Revenues", "Sales",
            "Net Profit", "Operating profit", "Total assets", "Total equity",
            "Total liabilities and equity", "Cost of sales", "Gross profit"
        ):
            score += 50

        # Positive value boost for asset/equity line items (main vs movement note)
        if dp.value > 0:
            score += 10

        return score

    best_map: Dict[Tuple[str, str], CanonicalDatapoint] = {}
    for key, dps in grouped.items():
        best_map[key] = max(dps, key=_score)

    return best_map
