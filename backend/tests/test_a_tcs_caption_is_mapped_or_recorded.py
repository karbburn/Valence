"""A printed TCS caption is either mapped to its key or recorded as withdrawn.

The consolidated balance sheet (printed page 11; page 20 is the standalone
face and is not read) prints 37 captions. Seventeen reach existing keys, six
are withdrawn with the reason on file, and the rest were already reachable.
An unmapped caption reads as an accident; a caption publishing under a name
that states something false about it is worse, which is most of what the
withdrawn six would do: five print in both halves with no half-specific key
(one key would hold whichever half parsed last), and the sixth parks a tax
liability in an asset key that does not exist.
"""
from __future__ import annotations

from datetime import datetime

from backend.data.store import RawDatapoint
from backend.normalization.financials import mapper
from backend.normalization.taxonomy.registry import (
    RAW_METRIC_MAP,
    WITHDRAWN_LABELS,
)

# (printed caption, statement section, printed FY26 figure, canonical key)
MAPPED_FIGURES = [
    ("Property, plant and equipment", "BALANCE SHEET", 11032.0,
     "canonical.bs.ppe"),
    ("Other intangible assets", "BALANCE SHEET", 176.0,
     "canonical.bs.intangible_assets"),
    ("Unbilled", "BALANCE SHEET", 10084.0, "canonical.bs.unbilled_revenue"),
    ("Deferred tax assets (net)", "BALANCE SHEET", 4465.0,
     "canonical.bs.deferred_tax_assets"),
    ("Income tax assets (net)", "BALANCE SHEET", 1439.0,
     "canonical.bs.income_tax_assets"),
    ("Share capital", "BALANCE SHEET", 362.0, "canonical.bs.equity_capital"),
    ("TOTAL ASSETS", "BALANCE SHEET", 182372.0, "canonical.bs.total_assets"),
    ("TOTAL EQUITY AND LIABILITIES", "BALANCE SHEET", 182372.0,
     "canonical.bs.total_liabilities_and_equity"),
    ("Other liabilities", "BALANCE SHEET", 6866.0,
     "canonical.bs.other_current_liabilities"),
]

# (printed caption, statement section, printed FY26 figure)
WITHDRAWN_FIGURES = [
    ("Loans", "BALANCE SHEET", 1659.0),
    ("Other assets", "BALANCE SHEET", 16533.0),
    ("Other financial assets", "BALANCE SHEET", 2944.0),
    ("Other financial liabilities", "BALANCE SHEET", 11194.0),
    ("Income tax liabilities (net)", "BALANCE SHEET", 14751.0),
    ("Unearned and deferred revenue", "BALANCE SHEET", 4487.0),
]


def _raw(label: str, section: str, value: float) -> RawDatapoint:
    return RawDatapoint(
        id="tcs-%s" % label[:6].replace(" ", ""),
        company_id="fixture_co",
        metric_raw=label,
        period_label="FY26",
        period_end_date=datetime(2026, 3, 31).date(),
        value=value,
        currency="INR",
        units="crores",
        source="nse_filing",
        source_location="fixture p.11",
        section=section,
        status="reported",
        update_date=datetime.now(),
    )


class TestTheTcsCaptionsWithHomesReachThem:
    def test_each_reaches_its_key_with_the_printed_figure(self, tmp_path):
        for label, section, value, key in MAPPED_FIGURES:
            canonical, _mappings, unmapped = mapper.map_raw_datapoints(
                [_raw(label, section, value)], db_path=tmp_path / "queue.db"
            )
            keys = [c.canonical_key for c in canonical]
            assert keys == [key], (
                "%r reached %s; it belongs on %s, and the figure the filing "
                "prints under these exact words is %.0f" % (label, keys, key, value)
            )
            assert canonical[0].value == value
            assert label not in unmapped

    def test_each_is_registered_and_not_withdrawn(self):
        for label, _section, _value, _key in MAPPED_FIGURES:
            assert label in RAW_METRIC_MAP
            assert label not in WITHDRAWN_LABELS


class TestTheTcsCaptionsWithoutAHomeAreRecorded:
    def test_every_one_of_them_is_a_withdrawn_label(self):
        missing = [
            label
            for label, _section, _value in WITHDRAWN_FIGURES
            if label not in WITHDRAWN_LABELS
        ]
        assert not missing, "%r is not recorded as withdrawn" % missing
        assert len(WITHDRAWN_FIGURES) == 6, (
            "the family changed size (%d); add or remove the caption itself, not "
            "silently the count" % len(WITHDRAWN_FIGURES)
        )

    def test_none_reaches_a_canonical_datapoint(self, tmp_path):
        for label, section, value in WITHDRAWN_FIGURES:
            canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
                [_raw(label, section, value)], db_path=tmp_path / "queue.db"
            )
            assert canonical == [], (
                "%r reached %s; it is recorded as withdrawn because no key "
                "holds what it says" % (label, [c.canonical_key for c in canonical])
            )
