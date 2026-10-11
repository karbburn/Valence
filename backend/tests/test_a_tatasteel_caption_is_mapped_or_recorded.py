"""Every caption on Tata Steel's audited consolidated face is mapped or recorded.

The filing (`tatasteel-annual-2026-05.pdf`) prints its consolidated balance sheet at
printed page 20, and the page reads 46 rows across 26 distinct captions in INR/crores
for FY25 and FY26. Four captions reach a canonical key and 22 are recorded as
withdrawn. The split is not a preference: the face letter-spaces its headings, and
the extraction keeps only part of several of them.

What the page prints foots exactly, on both periods:

    FY25  non-current assets 211,003.26 + current assets 68,391.54 = 279,394.80
          non-current liab. 101,948.47 + current liab. 86,093.55 + equity
          91,352.78        = 279,394.80
    FY26  228,733.94 + 72,265.11 + held-for-sale 255.06 = 301,254.11
          100,556.02 + 96,917.64 + equity 103,780.45     = 301,254.11

so "TOTAL-ASSETS" and "TOTAL - EQUITY AND LIABILITIES" are the same figure printed
twice, and each reaches its own key with it. The subtotal fragments that carry the
rest of that arithmetic lost the words that say which subtotal they are: bare
"Sub-total" alone holds four of the six (the current-assets and total-equity
subtotals extract to the same two words), so the identity is checkable from the
fixture but not publishable from the caption.

The sharpest refusal is the equity line. The engine proposes `share_count` for
"Equity attributable to shareholders of the company" at MEDIUM confidence, and a
MEDIUM suggestion is accepted by the mapper -- so without the withdrawal this page
would publish 102,167.65 crores as a count of shares. The standing withdrawal
covers the capitalised spelling; this filer's extraction prints "company" lowercase
and both gates match the printed string exactly, so the printed spelling is pinned
here beside it.
"""
from __future__ import annotations

from datetime import datetime

from backend.data.store import RawDatapoint
from backend.normalization.financials import mapper
from backend.normalization.taxonomy.registry import (
    RAW_METRIC_MAP,
    WITHDRAWN_LABELS,
)

# (printed caption, printed figure, canonical key, half as the filing prints it,
# period the filing prints it in)
#
# The half is carried where it decides something: "(d) Current tax assets" reaches
# a current-asset key, which the half guard refuses unless the row carries the
# current half -- the printed half, so the guard is exercised rather than
# sidestepped. The totals and the equity line are not current-asset keys and the
# guard makes no claim about them.
MAPPED_FIGURES = [
    ("TOTAL-ASSETS", 301254.11, "canonical.bs.total_assets", None, "FY26"),
    ("TOTAL - EQUITY AND LIABILITIES", 301254.11,
     "canonical.bs.total_liabilities_and_equity", None, "FY26"),
    ("(d) Current tax assets", 76.28, "canonical.bs.current_income_tax_assets",
     "current", "FY26"),
    ("Non-controlling interest", 183.15, "canonical.bs.minority_interest",
     None, "FY25"),
]

# (printed caption, printed figure, period the filing prints it in)
#
# The figure is the one the filing prints under these exact words, so a caption
# whose reason is a number (the 102,167.65 equity line, the four-figure
# "Sub-total") is decided against that number rather than against its own label.
WITHDRAWN_FIGURES = [
    ("( Retirement benefit assets", 86.38, "FY26"),
    ("()", 442.65, "FY25"),
    ("(3) Assets held for sale", 255.06, "FY26"),
    ("(c)", 297.76, "FY26"),
    ("(c) Retirement benefit assets", 2.33, "FY25"),
    ("(c) Retirement benefit obligations", 148.63, "FY26"),
    ("(d) Deferred income", 764.91, "FY25"),
    ("(iii)", 703.85, "FY26"),
    ("(iii) Derivative liabilities", 206.38, "FY25"),
    ("(iv) Derivative liabilities", 260.7, "FY26"),
    ("(v) Loans", 3.35, "FY26"),
    ("(vi) assets", 961.47, "FY26"),
    ("Acceptances", 338.52, "FY25"),
    ("Equity attributable to shareholders of the company", 102167.65, "FY26"),
    ("Intangible assets under development", 986.42, "FY26"),
    ("Loans", 126.2, "FY26"),
    ("Other financial assets", 828.59, "FY26"),
    ("Sub-total", 103780.45, "FY26"),
    ("Sub-total -", 197473.66, "FY26"),
    ("Sub-total - Current", 96917.64, "FY26"),
    ("Sub-total - Non-current", 228733.94, "FY26"),
    ("«d) Deferred income", 88.09, "FY26"),
]

_PERIOD_END = {"FY25": datetime(2025, 3, 31), "FY26": datetime(2026, 3, 31)}


def _raw(label: str, value: float, half: str | None = None,
         period: str = "FY26", location: str = "fixture p.20") -> RawDatapoint:
    # The default location carries no " y=" on purpose: the same-page twin gate reads a
    # page coordinate as a second printing, and what the mapped and withdrawn classes
    # pin is the registry's decision for the caption rather than the row's fate on the
    # real page.
    return RawDatapoint(
        id="tata-%s-%.0f-%s" % (
            label[:8].replace(" ", "").replace("(", "").replace(")", ""),
            value, period,
        ),
        company_id="fixture_co",
        metric_raw=label,
        period_label=period,
        period_end_date=_PERIOD_END[period].date(),
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


class TestTheTataSteelCaptionsWithHomesReachThem:
    def test_each_reaches_its_key_with_the_printed_figure(self, tmp_path):
        for label, value, key, half, period in MAPPED_FIGURES:
            canonical, _mappings, unmapped = mapper.map_raw_datapoints(
                [_raw(label, value, half=half, period=period)],
                db_path=tmp_path / "queue.db",
            )
            keys = [c.canonical_key for c in canonical]
            assert keys == [key], (
                "%r reached %s; it belongs on %s, and the figure the filing "
                "prints under these exact words is %.2f" % (label, keys, key, value)
            )
            assert canonical[0].value == value
            assert label not in unmapped
        assert len(MAPPED_FIGURES) == 4, (
            "the mapped family changed size (%d); add or remove the caption itself, "
            "not silently the count" % len(MAPPED_FIGURES)
        )

    def test_each_is_registered_and_not_withdrawn(self):
        for label, _value, _key, _half, _period in MAPPED_FIGURES:
            assert label in RAW_METRIC_MAP, "%r has no registry entry" % label
            assert label not in WITHDRAWN_LABELS


class TestTheTataSteelCaptionsWithoutAHomeAreRecorded:
    def test_every_one_of_them_is_a_withdrawn_label(self):
        missing = [
            label
            for label, _value, _period in WITHDRAWN_FIGURES
            if label not in WITHDRAWN_LABELS
        ]
        assert not missing, "%r is not recorded as withdrawn" % missing
        assert len(WITHDRAWN_FIGURES) == 22, (
            "the withdrawn family changed size (%d); add or remove the caption "
            "itself, not silently the count" % len(WITHDRAWN_FIGURES)
        )

    def test_none_reaches_a_canonical_datapoint(self, tmp_path):
        for label, value, period in WITHDRAWN_FIGURES:
            canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
                [_raw(label, value, period=period)],
                db_path=tmp_path / "queue.db",
            )
            assert canonical == [], (
                "%r reached %s; it is recorded as withdrawn because no key "
                "holds what it says" % (label, [c.canonical_key for c in canonical])
            )

    def test_none_is_registered_as_a_mapping(self):
        for label, _value, _period in WITHDRAWN_FIGURES:
            assert label not in RAW_METRIC_MAP, (
                "%r is withdrawn AND mapped; a confirmed mapping outranks the "
                "withdrawal and the refusal would be dead on arrival" % label
            )

    def test_the_family_covers_every_caption_not_in_a_home(self):
        mapped = {label for label, _v, _k, _h, _p in MAPPED_FIGURES}
        withdrawn = {label for label, _v, _p in WITHDRAWN_FIGURES}
        assert len(mapped | withdrawn) == 26, (
            "the face reads 26 distinct captions and the two families cover "
            "%d; a caption was dropped from both" % len(mapped | withdrawn)
        )
        assert not (mapped & withdrawn), (
            "captions in both families: %s" % sorted(mapped & withdrawn)
        )


class TestTheEquityLineDoesNotBecomeAShareCount:
    """The engine proposes `share_count` for this caption at MEDIUM, and MEDIUM publishes.

    A medium suggestion is accepted by the mapper, so the withdrawal is the only
    thing between 102,167.65 crores and a share-count field. The capitalised
    spelling carries its own standing withdrawal; this page prints "company"
    lowercase and both gates match the printed string, so both spellings are
    pinned against the consequence.
    """

    def test_the_printed_lowercase_spelling_is_refused(self, tmp_path):
        canonical, _m, _u = mapper.map_raw_datapoints(
            [_raw("Equity attributable to shareholders of the company", 102167.65)],
            db_path=tmp_path / "queue.db",
        )
        assert canonical == [], (
            "an equity figure published as a share count would state 102,167.65 "
            "crores as a number of shares"
        )

    def test_the_capitalised_spelling_is_refused(self, tmp_path):
        canonical, _m, _u = mapper.map_raw_datapoints(
            [_raw("Equity attributable to shareholders of the Company", 102167.65)],
            db_path=tmp_path / "queue.db",
        )
        assert canonical == []

    def test_nothing_printed_on_this_face_reaches_the_share_count_key(self, tmp_path):
        rows = [
            _raw(label, value, period=period)
            for label, value, period in WITHDRAWN_FIGURES
        ] + [
            _raw(label, value, half=half, period=period)
            for label, value, _key, half, period in MAPPED_FIGURES
        ]
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            rows, db_path=tmp_path / "queue.db"
        )
        keys = {c.canonical_key for c in canonical}
        assert "canonical.meta.share_count" not in keys, (
            "a caption from this face reached the share-count key: %s" % keys
        )
        assert keys == {
            "canonical.bs.total_assets",
            "canonical.bs.total_liabilities_and_equity",
            "canonical.bs.current_income_tax_assets",
            "canonical.bs.minority_interest",
        }, "the whole face must resolve to exactly the four homes: %s" % sorted(keys)


class TestTheFootingClosesOnBothPeriods:
    """The identity that makes "TOTAL-ASSETS" readable at all.

    The engine reads the hyphenated extraction at low confidence, so the static
    entry carries it; what justifies the entry is that the two footing captions
    report the same total on both periods the page prints. If either caption ever
    routed elsewhere, these pairs would disagree and this test would say so.
    """

    def test_both_sides_report_the_same_total(self, tmp_path):
        rows = [
            _raw("TOTAL-ASSETS", 279394.8, period="FY25"),
            _raw("TOTAL - EQUITY AND LIABILITIES", 279394.8, period="FY25"),
            _raw("TOTAL-ASSETS", 301254.11, period="FY26"),
            _raw("TOTAL - EQUITY AND LIABILITIES", 301254.11, period="FY26"),
        ]
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            rows, db_path=tmp_path / "queue.db"
        )
        by = {(c.canonical_key, c.period_label): c.value for c in canonical}
        for period, total in (("FY25", 279394.8), ("FY26", 301254.11)):
            assert by.get(("canonical.bs.total_assets", period)) == total
            assert by.get(("canonical.bs.total_liabilities_and_equity", period)) == total
