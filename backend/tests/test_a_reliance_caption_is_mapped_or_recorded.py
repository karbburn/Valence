"""A printed Reliance caption is either mapped to its key or recorded as withdrawn.

The audited consolidated balance sheet (printed page 16 of
`reliance-annual-2026-04.pdf`) prints 38 distinct captions. Twenty-six reach
existing keys with the FY25 figure the face prints under those exact words,
twelve are withdrawn with the reason on file, and two of the mapped captions --
"Lease Liabilities" and "Provisions", each printed once per block -- publish
neither printing on the real page, because the liability half-headers match no
half pattern and both rows inherit the current tag into one gate bucket.

Only the FY25 column reads cleanly (the FY26 column's header extracts as nothing
and its cells come out missing, garbled, or wrong), so every figure below is the
FY25 one and the metadata records FY25 only.

Three things the engine gets wrong on this face, each caught in the dry run and
each decided here rather than left to fuzzy luck: "Other Equity" suggested to
the equity total (dooming the true 1,009,626 beside it), "Other Financial
Liabilities" suggested to the current-liabilities key (dooming the true 90,124),
and "Deferred Tax liabilities (Net)" suggested to the deferred-tax ASSET key
(dooming the true 408). All three are withdrawn, and the true lines survive.

The face's font drops the "t" ("Olher", "lnlangible Assels") the way HCLTech's
breaks "non-current": the extracted strings are what the registry keeps, with
the artifact named in the comment, because a prettier caption would never match
what the reader receives. "Total Equi and Liabilities" is the print's own typo
for the grand total, footing the page at 1,950,121.
"""
from __future__ import annotations

from datetime import datetime

from backend.data.store import RawDatapoint
from backend.normalization.financials import mapper
from backend.normalization.taxonomy.registry import (
    RAW_METRIC_MAP,
    WITHDRAWN_LABELS,
)

# (printed caption, printed FY25 figure, canonical key)
MAPPED_FIGURES = [
    ("Property, Plant and Equipment", 683102.0, "canonical.bs.ppe"),
    ("Capital Work-in-Progress", 169710.0, "canonical.bs.cwip"),
    ("Goodwill", 24530.0, "canonical.bs.goodwill"),
    ("Olher Intangible Assets", 144639.0, "canonical.bs.intangible_assets"),
    ("Deferred Tax Assets (Net)", 408.0, "canonical.bs.deferred_tax_assets"),
    ("Olher Non-Current Assets", 58190.0, "canonical.bs.other_non_current_assets"),
    ("Total Non-Current Assets", 1450851.0, "canonical.bs.total_non_current_assets"),
    ("Inventories", 146062.0, "canonical.bs.inventory"),
    ("Trade Receivables", 42121.0, "canonical.bs.trade_receivables"),
    ("Cash and Cash Equivalents", 106502.0, "canonical.bs.cash_and_bank"),
    ("Other Current Assets", 57148.0, "canonical.bs.prepayments_other_current_assets"),
    ("Total Current Assets", 499270.0, "canonical.bs.total_current_assets"),
    ("Total Assets", 1950121.0, "canonical.bs.total_assets"),
    ("Equity Share Capital", 13532.0, "canonical.bs.equity_capital"),
    ("Non-Controlling Interest", 166426.0, "canonical.bs.minority_interest"),
    ("Total Equity", 1009626.0, "canonical.bs.total_equity"),
    ("Total Liabilities", 940495.0, "canonical.bs.total_liabilities"),
    ("Total Non-Current Liabilities", 486758.0, "canonical.bs.total_non_current_liabilities"),
    ("Borrowings", 110631.0, "canonical.bs.borrowings"),
    ("Total Current Liabilities", 453737.0, "canonical.bs.total_current_liabilities"),
    ("Total Equi and Liabilities", 1950121.0, "canonical.bs.total_liabilities_and_equity"),
    ("Other Current Liabilities", 90124.0, "canonical.bs.other_current_liabilities"),
    ("Other Non-Current Liabilities", 5641.0, "canonical.bs.other_non_current_liabilities"),
    ("Trade Payables", 186789.0, "canonical.bs.trade_payables"),
    # One of the two prints each; the face prints both under one inherited half
    # and the gate refuses both on the real document. The fixture location below
    # carries no page coordinate, so what is pinned here is the registry's
    # decision for the words, not the fate of the row.
    ("Lease Liabilities", 17142.0, "canonical.bs.lease_liabilities"),
    ("Provisions", 28304.0, "canonical.bs.provisions"),
]

# (printed caption, printed FY25 figure). Fourteen figures, twelve captions:
# "Investments" prints in both halves and "Loans" prints a 742 non-current line
# beside the 5,182 current one, and one key cannot hold either pair.
WITHDRAWN_FIGURES = [
    ("Deferred Payment liabilities", 104410.0),
    ("Deferred Tax liabilities (Net)", 83453.0),
    ("Investments", 123672.0),
    ("Investments", 118709.0),
    ("Loans", 742.0),
    ("Loans", 5182.0),
    ("Olher Financial Assets", 6088.0),
    ("Olher Financial Liabilities", 57143.0),
    ("Other Equity", 829668.0),
    ("Other Financial Assets", 23546.0),
    ("Other Financial Liabilities", 10909.0),
    ("Other lnlangible Assels Under Development", 38472.0),
    ("Spectrum", 147122.0),
    ("Spectrum Under Development", 54176.0),
]


def _raw(label: str, value: float, half: str | None = None,
         location: str = "fixture p.16") -> RawDatapoint:
    # The default location carries no " y=" on purpose: the same-page twin gate
    # reads a page coordinate as a second printing, and what the mapped and
    # withdrawn classes pin is the registry's decision for the caption rather
    # than the row's fate on the real page. The gate class below passes real
    # coordinates.
    return RawDatapoint(
        id="rel-%s-%.0f" % (label[:8].replace(" ", ""), value),
        company_id="fixture_co",
        metric_raw=label,
        period_label="FY25",
        period_end_date=datetime(2025, 3, 31).date(),
        value=value,
        currency="INR",
        units="crores",
        source="nse_filing",
        source_location=location,
        section="BALANCE SHEET",
        bs_half=half,
        status="reported",
        update_date=datetime.now(),
    )


class TestTheRelianceCaptionsWithHomesReachThem:
    def test_each_reaches_its_key_with_the_printed_figure(self, tmp_path):
        for label, value, key in MAPPED_FIGURES:
            canonical, _mappings, unmapped = mapper.map_raw_datapoints(
                [_raw(label, value)], db_path=tmp_path / "queue.db"
            )
            keys = [c.canonical_key for c in canonical]
            assert keys == [key], (
                "%r reached %s; it belongs on %s, and the figure the filing "
                "prints under these exact words is %.0f" % (label, keys, key, value)
            )
            assert canonical[0].value == value
            assert label not in unmapped
        assert len(MAPPED_FIGURES) == 26, (
            "the mapped family changed size (%d); add or remove the caption itself, "
            "not silently the count" % len(MAPPED_FIGURES)
        )

    def test_each_is_registered_and_not_withdrawn(self):
        for label, _value, _key in MAPPED_FIGURES:
            assert label in RAW_METRIC_MAP, "%r has no registry entry" % label
            assert label not in WITHDRAWN_LABELS


class TestTheRelianceCaptionsWithoutAHomeAreRecorded:
    def test_every_one_of_them_is_a_withdrawn_label(self):
        missing = [
            label
            for label, _value in WITHDRAWN_FIGURES
            if label not in WITHDRAWN_LABELS
        ]
        assert not missing, "%r is not recorded as withdrawn" % missing
        assert len({label for label, _v in WITHDRAWN_FIGURES}) == 12, (
            "the withdrawn family changed size (%d captions); add or remove the "
            "caption itself, not silently the count"
            % len({label for label, _v in WITHDRAWN_FIGURES})
        )
        assert len(WITHDRAWN_FIGURES) == 14, (
            "two captions print two figures under one withdrawn caption; the figure "
            "count changed (%d)" % len(WITHDRAWN_FIGURES)
        )

    def test_none_reaches_a_canonical_datapoint(self, tmp_path):
        for label, value in WITHDRAWN_FIGURES:
            canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
                [_raw(label, value)], db_path=tmp_path / "queue.db"
            )
            assert canonical == [], (
                "%r reached %s; it is recorded as withdrawn because no key "
                "holds what it says" % (label, [c.canonical_key for c in canonical])
            )

    def test_none_is_registered_as_a_mapping(self):
        for label, _value in WITHDRAWN_FIGURES:
            assert label not in RAW_METRIC_MAP, (
                "%r is withdrawn AND mapped; a confirmed mapping outranks the "
                "withdrawal and the refusal would be dead on arrival" % label
            )


class TestTheLiabilityTwinsShareOneBucket:
    """The face's liability half-headers match no half pattern, so both blocks'
    rows inherit the current tag and each twice-printed caption lands in one
    gate bucket with two values. Neither printing publishes; both queue."""

    def test_neither_lease_printing_publishes(self, tmp_path):
        dps = [
            _raw("Lease Liabilities", 17142.0, half="current",
                 location="reliance-annual-2026-04.pdf p.16 y=506.3 Lease Liabilities"),
            _raw("Lease Liabilities", 4903.0, half="current",
                 location="reliance-annual-2026-04.pdf p.16 y=612.5 Lease Liabilities"),
        ]
        canonical, _mappings, unmapped = mapper.map_raw_datapoints(
            dps, db_path=tmp_path / "queue.db"
        )
        assert [c.canonical_key for c in canonical] == [], (
            "the non-current 17,142 and the current 4,903 share one key and one "
            "bucket; publishing either states the other half's figure as this line"
        )
        assert unmapped == []

    def test_neither_provisions_printing_publishes(self, tmp_path):
        dps = [
            _raw("Provisions", 28304.0, half="current",
                 location="reliance-annual-2026-04.pdf p.16 y=538.0 Provisions"),
            _raw("Provisions", 4147.0, half="current",
                 location="reliance-annual-2026-04.pdf p.16 y=655.7 Provisions"),
        ]
        canonical, _mappings, unmapped = mapper.map_raw_datapoints(
            dps, db_path=tmp_path / "queue.db"
        )
        assert [c.canonical_key for c in canonical] == []
        assert unmapped == []

    def test_a_withdrawn_mate_frees_the_true_line(self, tmp_path):
        """The other half of the gate's work: "Other Equity" is withdrawn, so the
        true 1,009,626 survives where the dry run doomed it beside the 829,668."""
        dps = [
            _raw("Total Equity", 1009626.0, half="current",
                 location="reliance-annual-2026-04.pdf p.16 y=442.8 Total Equity"),
        ]
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            dps, db_path=tmp_path / "queue.db"
        )
        assert [(c.canonical_key, c.value) for c in canonical] == [
            ("canonical.bs.total_equity", 1009626.0)
        ]
