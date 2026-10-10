"""A row read from a document outranks a row somebody modelled.

The scorer used to decide reported-vs-estimated ties by label and section
boosts, which cancel the source-authority gap exactly where it matters: every
screener location contains "DATASHEET" (+100), so regulatory +200 against
aggregator +100 ends level and the tie goes to whichever row archived first --
the estimate. TCS published screener "Net Block" 12,600 over filed 11,032,
and a primary-labelled screener caption ("Trade receivables", +50) beat the
filed variant ("Billed") by fifty outright.

The reported boost (+200) exceeds the largest accidental swing (section 100
plus primary label 50) and sits below derived (+1000), so reported-vs-reported
and estimated-vs-estimated contests are unchanged.
"""
from __future__ import annotations

from datetime import datetime

from backend.data.store import RawDatapoint
from backend.models.statements.selector import (
    _score_canonical,
    select_primary_datapoints,
)
from backend.normalization.taxonomy.models import CanonicalDatapoint


def _row(metric_raw: str, value: float, status: str, rid: str) -> CanonicalDatapoint:
    return CanonicalDatapoint(
        company_id="fixture_co",
        canonical_key="canonical.bs.ppe",
        metric_raw=metric_raw,
        period_label="FY26",
        period_end_date=datetime(2026, 3, 31).date(),
        value=value,
        currency="INR",
        units="crores",
        status=status,
        source_datapoint_ids=[rid],
        derivation_rule=None,
    )


def _raw(rid: str, source: str, location: str) -> RawDatapoint:
    return RawDatapoint(
        id=rid,
        company_id="fixture_co",
        metric_raw="m",
        period_label="FY26",
        period_end_date=datetime(2026, 3, 31).date(),
        value=0.0,
        currency="INR",
        units="crores",
        source=source,
        source_location=location,
        section="BALANCE SHEET",
        status="reported",
        update_date=datetime.now(),
    )


def _map():
    return {
        "file": _raw("file", "nse_filing", "tcs-outcome.pdf p.11 y=98.1 caption"),
        "agg": _raw("agg", "screener", "DataSheet!E35"),
    }


class TestReportedOutranksEstimated:
    def test_filed_row_beats_aggregator_row_despite_datasheet_boost(self):
        filed = _row("Property, plant and equipment", 11032.0, "reported", "file")
        est = _row("Net Block", 12600.0, "estimated", "agg")
        assert _score_canonical(filed, "bs", _map()) > _score_canonical(
            est, "bs", _map()
        ), "the estimate still wins the tie the boost exists to break"

    def test_filed_variant_beats_primary_labelled_estimate(self):
        filed = _row("Billed", 10084.0, "reported", "file")
        est = _row("Trade receivables", 9999.0, "estimated", "agg")
        assert _score_canonical(filed, "bs", _map()) > _score_canonical(
            est, "bs", _map()
        ), "a +50 label boost still overrules a read figure"

    def test_selection_publishes_the_filed_row_either_order(self):
        filed = _row("Property, plant and equipment", 11032.0, "reported", "file")
        est = _row("Net Block", 12600.0, "estimated", "agg")
        for ordered in ([filed, est], [est, filed]):
            best = select_primary_datapoints(
                ordered, "bs", raw_datapoints_map=_map()
            )
            assert best[("canonical.bs.ppe", "FY26")].value == 11032.0, (
                "page order decides the figure again"
            )


class TestUntouchedContestsStayUntouched:
    def test_reported_vs_reported_still_ties(self):
        a = _row("Property, plant and equipment", 11032.0, "reported", "file")
        b = _row("Property, plant and equipment", 11032.0, "reported", "file")
        assert _score_canonical(a, "bs", _map()) == _score_canonical(b, "bs", _map())

    def test_estimated_vs_estimated_still_ties(self):
        a = _row("Net Block", 12600.0, "estimated", "agg")
        b = _row("Net Block", 12600.0, "estimated", "agg")
        assert _score_canonical(a, "bs", _map()) == _score_canonical(b, "bs", _map())

    def test_derived_still_outranks_reported(self):
        derived = _row("m", 1.0, "derived", "file")
        filed = _row("m", 1.0, "reported", "file")
        assert _score_canonical(derived, "bs", _map()) > _score_canonical(
            filed, "bs", _map()
        ), "the boost must sit below the derivation rule"
