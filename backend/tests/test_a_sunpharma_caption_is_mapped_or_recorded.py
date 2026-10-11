"""Every caption on Sun Pharma's audited consolidated face is mapped or recorded.

The filing (`sunpharma-annual-2026-05.pdf`) prints its audited consolidated
statement of assets and liabilities at printed page 19, and the page reads 92
rows across 45 distinct captions for FY25 and FY26. Twenty-six canonical keys
publish; the rest are recorded elsewhere or refuse by design. Four facts about
this face are decided against its printed figures:

1. Triage. The balance-sheet detector finds two statements: printed 6 is the
   standalone ("Audited Standalone Statement of Assets and Liabilities",
   430,595.4 total, no non-controlling interests on the page) and printed 19
   the consolidated, which foots exactly on both periods (assets = equity +
   liabilities = 921,005.8 at FY25 and 1,087,852.2 at FY26, with the liability
   halves summing to their printed total as well). The consolidated is the
   statement of record and the standalone is not migrated.

2. Basis. The face prints "(~ in Million)" -- the parenthesised banner the
   number reader matches is the crores one, so the page declares nothing
   readable and the record in `sunpharma.json` carries the witnessed basis:
   paid-up capital of 2,399.3 million is 240 crore shares at Rs 1, the share
   count the registry already holds, and total assets 1,087,852.2 million is
   108,785 crores against the feed's 102,000 crore estimate. The model for
   `sunpharma_sunpharma` declares crores and is single-basis, so the branch
   scales the rows by the definition the way `us_live.py` stamps millions.
   PUBLISHED below is crores throughout; the printed figure is the same
   number ten times over.

3. Halves. The block headers survive extraction clean ("(1) Non-current
   assets", "(2) Current assets"), so rows carry their half and the two
   "(i) Investments" printings route to their own keys by position:
   non-current 46,977.0 / 37,890.7 and current 136,561.0 / 209,334.5 (printed,
   millions).

4. Engine inversions. The captions print in full here, so what refuses is the
   engine rather than the extraction: three tax liabilities whose only keys
   are asset keys ("(c) Deferred tax liabilities (Net)" 1,924.4 / 3,780.2,
   "(d) Current tax liabilities (Net)" 7,331.8 / 13,500.4, "(e) Non-current
   tax liabilities (Net)" 87.6 / 128.9), an intangibles pair under one key
   ("(e) Intangible assets under development" 54,096.2 / 16,710.8 against
   "(d) Other intangible assets" 36,109.2 / 118,750.8), and the parent-only
   equity (722,180.2 / 835,700.9) whose total the sheet itself prints
   (724,859.5 / 838,797.4) with the non-controlling interests of 2,679.3 /
   3,096.5 beside it. All five are withdrawn and the asset lines beside them
   take their own keys: the true deferred-tax asset (44,075.5 / 40,464.6),
   the income-tax asset (4,206.7 / 6,451.3), goodwill (89,394.2 / 98,330.8)
   and the completed intangibles.

One refusal is three distinct lines under one key: "(b) Other current
liabilities" (11,697.9 / 11,875.3), "(iii) Other financial liabilities"
(106.8 / 6,307.9) and "(iv) Other financial liabilities" (19,478.4 /
25,721.8) all reach other_current_liabilities and refuse each other as
same-page same-half twins, so none publishes. The standing withdrawals of
the earlier faces carry their cost here as recorded: borrowings, trade
receivables, the current lease and provisions lines, loans and
assets-classified-as-held-for-sale stay feed-sourced, and the held-for-sale
line (304.1 / 309.0) is the only figure between the printed current-assets
subtotal and TOTAL ASSETS.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest

from backend.data.parsers.pdf_tables import parse_predicted_statement_page
from backend.data.pipeline import _filing_datapoints_from_cached_pdf
from backend.normalization.financials import mapper
from backend.normalization.taxonomy.registry import (
    RAW_METRIC_MAP,
    WITHDRAWN_LABELS,
)

FILING = Path("backend/data/filings/nse/sunpharma-annual-2026-05.pdf")
META = Path("backend/data/filings/nse/sunpharma.json")

needs_sun = pytest.mark.skipif(
    not FILING.exists(), reason="the Sun Pharma filing is absent"
)

# The whole face resolves to exactly these homes, on the model's crores basis
# (printed millions / 10).
PUBLISHED = {
    "canonical.bs.cash_and_bank": {"FY25": 10268.77, "FY26": 9770.51},
    "canonical.bs.current_investments": {"FY25": 13656.1, "FY26": 20933.45},
    "canonical.bs.cwip": {"FY25": 1234.34, "FY26": 1380.65},
    "canonical.bs.deferred_tax_assets": {"FY25": 4407.55, "FY26": 4046.46},
    "canonical.bs.equity_capital": {"FY25": 239.93, "FY26": 239.93},
    "canonical.bs.goodwill": {"FY25": 8939.42, "FY26": 9833.08},
    "canonical.bs.income_tax_assets": {"FY25": 420.67, "FY26": 645.13},
    "canonical.bs.intangible_assets": {"FY25": 3610.92, "FY26": 11875.08},
    "canonical.bs.inventory": {"FY25": 10243.33, "FY26": 11492.93},
    "canonical.bs.lease_liabilities": {"FY25": 355.74, "FY26": 361.63},
    "canonical.bs.minority_interest": {"FY25": 267.93, "FY26": 309.65},
    "canonical.bs.non_current_investments": {"FY25": 4697.7, "FY26": 3789.07},
    "canonical.bs.other_non_current_assets": {"FY25": 540.12, "FY26": 471.0},
    "canonical.bs.other_non_current_liabilities": {"FY25": 385.24, "FY26": 356.67},
    "canonical.bs.ppe": {"FY25": 10035.94, "FY26": 11114.11},
    "canonical.bs.prepayments_other_current_assets": {
        "FY25": 2527.86, "FY26": 2864.77,
    },
    "canonical.bs.provisions": {"FY25": 465.04, "FY26": 512.18},
    "canonical.bs.trade_payables": {"FY25": 6184.34, "FY26": 7333.8},
    "canonical.bs.total_assets": {"FY25": 92100.58, "FY26": 108785.22},
    "canonical.bs.total_current_assets": {"FY25": 52594.06, "FY26": 63860.29},
    "canonical.bs.total_current_liabilities": {"FY25": 18194.21, "FY26": 22622.04},
    "canonical.bs.total_equity": {"FY25": 72485.95, "FY26": 83879.74},
    "canonical.bs.total_liabilities": {"FY25": 19614.63, "FY26": 24905.48},
    "canonical.bs.total_liabilities_and_equity": {
        "FY25": 92100.58, "FY26": 108785.22,
    },
    "canonical.bs.total_non_current_assets": {"FY25": 39476.11, "FY26": 44894.03},
    "canonical.bs.total_non_current_liabilities": {"FY25": 1420.42, "FY26": 2283.44},
}

# (printed caption, printed figure) for the five engine inversions, AS PRINTED
# in millions because the decision is about which figure sits under which key,
# not about the scale.
INVERTED_FIGURES = [
    ("(c) Deferred tax liabilities (Net)", 3780.2),
    ("(d) Current tax liabilities (Net)", 13500.4),
    ("(e) Non-current tax liabilities (Net)", 128.9),
    ("(e) Intangible assets under development", 16710.8),
    ("Equity attributable to the equity shareholders of the parent company",
     835700.9),
]

# Three distinct printed lines under one key; none may publish.
TRIO = [
    ("(b) Other current liabilities", 11697.9),
    ("(iii) Other financial liabilities", 106.8),
    ("(iv) Other financial liabilities", 19478.4),
]


@lru_cache(maxsize=1)
def _face_rows():
    """The rows the product itself builds from the installed record."""
    meta = json.loads(META.read_text(encoding="utf-8"))
    return _filing_datapoints_from_cached_pdf(FILING, meta, "sunpharma_sunpharma")


def _raw(label: str, value: float, period: str = "FY26", *,
         page: str | None = None):
    from datetime import datetime

    from backend.data.store import RawDatapoint

    # With a page coordinate the same-page twin gate reads the rows as
    # printings of one page; without it the location carries no coordinate
    # and the gate never counts them, which is what the withdrawal fixtures
    # want because a withdrawal refuses before staging.
    location = ("sun-annual.pdf %s y=42" % page) if page else "fixture p.19"
    return RawDatapoint(
        id="sunp-%s-%.1f-%s-%s" % (label[:8].replace(" ", ""), value, period,
                                   page or "n"),
        company_id="sunpharma_sunpharma",
        metric_raw=label,
        period_label=period,
        period_end_date=datetime(2026 if period == "FY26" else 2025, 3, 31).date(),
        value=value,
        currency="INR",
        units="millions",
        source="nse_filing",
        source_location=location,
        section="BALANCE SHEET",
        bs_half="current",
        status="reported",
        update_date=datetime.now(),
    )


class TestTheEngineInversionsAreRecorded:
    def test_each_is_withdrawn_and_not_mapped(self):
        for label, _value in INVERTED_FIGURES:
            assert label in WITHDRAWN_LABELS, "%r is not recorded as withdrawn" % label
            assert label not in RAW_METRIC_MAP, (
                "%r is withdrawn AND mapped; a confirmed mapping outranks the "
                "withdrawal and the refusal would be dead on arrival" % label
            )
        assert len(INVERTED_FIGURES) == 5, (
            "the inversion family changed size (%d); add or remove the caption "
            "itself, not silently the count" % len(INVERTED_FIGURES)
        )

    def test_none_reaches_a_canonical_datapoint(self, tmp_path):
        for label, value in INVERTED_FIGURES:
            canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
                [_raw(label, value)],
                db_path=tmp_path / "queue.db",
            )
            assert canonical == [], (
                "%r reached %s; a liability or a partial must not publish "
                "under an asset or total key" % (
                    label, [c.canonical_key for c in canonical],
                )
            )


class TestTheThreeLinesUnderOneKeyPublishNone:
    def test_the_twin_gate_refuses_all_three_printings(self, tmp_path):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            [_raw(label, value, page="p.19") for label, value in TRIO],
            db_path=tmp_path / "queue.db",
        )
        assert canonical == [], (
            "one key cannot hold three figures for one period; got %s" % [
                (c.canonical_key, c.value) for c in canonical
            ]
        )


@needs_sun
class TestTheDeclaredBasisIsRecordedAndThenScaled:
    """The record states what the page cannot; the branch delivers the model's basis.

    The parser reads what a page declares, and this page declares nothing any
    pattern matches: "(~ in Million)" is the crores banner's shape with a
    bare scale word. So the record supplies the basis, the parse carries it,
    and the branch scales to the model's crores. A test that saw only the
    store's rows could not tell a declared basis from an assumed one.
    """

    def test_the_parser_reads_the_recorded_basis_as_printed(self):
        rows = parse_predicted_statement_page(
            FILING, 18, "BALANCE SHEET", "nse_filing",
            annual_only=False, company_id="sunpharma_sunpharma",
            declared_units_override=("INR", "millions"),
        )
        assert {(d.currency, d.units) for d in rows} == {("INR", "millions")}, (
            "the recorded basis did not reach every row"
        )
        total = [
            d.value for d in rows
            if d.metric_raw == "TOTAL ASSETS" and d.period_label == "FY26"
        ]
        assert total == [1087852.2], (
            "the printed total must read as printed before any scaling: %s" % total
        )

    def test_the_branch_delivers_the_rows_on_the_model_basis(self):
        rows = _face_rows()
        assert len(rows) == 92, "the page reads %d rows" % len(rows)
        assert {(d.currency, d.units) for d in rows} == {("INR", "crores")}, (
            "rows must arrive on the basis the model declares; got %s"
            % {(d.currency, d.units) for d in rows}
        )
        assert {d.period_label for d in rows} == {"FY25", "FY26"}
        total = [
            d.value for d in rows
            if d.metric_raw == "TOTAL ASSETS" and d.period_label == "FY26"
        ]
        assert total == [108785.22], (
            "the total must be the printed figure scaled by the recorded "
            "factor: %s" % total
        )


@needs_sun
class TestTheWholeFaceResolvesToExactlyTheseHomes:
    def test_every_caption_reaches_its_home_with_the_expected_figure(
        self, tmp_path
    ):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=tmp_path / "queue.db"
        )
        by = {(c.canonical_key, c.period_label): c.value for c in canonical}
        expected = {
            (key, period): value
            for key, periods in PUBLISHED.items()
            for period, value in periods.items()
        }
        assert by == expected, (
            "the face must resolve to exactly twenty-six homes on the model "
            "basis; extra: %s, missing: %s" % (
                {k: by[k] for k in set(by) - set(expected)},
                {k: expected[k] for k in set(expected) - set(by)},
            )
        )

    def test_the_inverted_keys_hold_only_their_true_figures(self, tmp_path):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=tmp_path / "queue.db"
        )
        by = {(c.canonical_key, c.period_label): c.value for c in canonical}
        assert by[("canonical.bs.deferred_tax_assets", "FY26")] == 4046.46, (
            "the deferred-tax key must hold the printed ASSET (40,464.6 "
            "million), not the liability beside it (3,780.2)"
        )
        assert by[("canonical.bs.income_tax_assets", "FY26")] == 645.13, (
            "the income-tax key must hold the printed asset (6,451.3 million)"
        )
        assert by[("canonical.bs.intangible_assets", "FY26")] == 11875.08, (
            "the intangibles key must hold the completed intangibles "
            "(118,750.8 million), not the line under development"
        )
        assert "canonical.meta.share_count" not in {
            c.canonical_key for c in canonical
        }, "a balance-sheet figure reached the share-count key"
        assert "canonical.bs.other_current_liabilities" not in {
            c.canonical_key for c in canonical
        }, (
            "three printed lines compete for this key and none may publish a "
            "figure the reader would take as the whole"
        )


@needs_sun
class TestTheFootingClosesOnBothPeriods:
    """The identity the whole face turns on, on the basis the store holds.

    Both sides of the sheet report the same total on both periods, and the
    current-assets subtotal plus the held-for-sale line the withdrawals keep
    out (304.1 / 309.0 printed, the only figure between them) bridge to
    TOTAL ASSETS. If any caption routed elsewhere these pairs would disagree.
    The printed figures and the stored ones are the same arithmetic at a
    tenth the scale.
    """

    def test_both_sides_report_the_same_total(self, tmp_path):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=tmp_path / "queue.db"
        )
        by = {(c.canonical_key, c.period_label): c.value for c in canonical}
        for period, total, equity, liabilities, noncur, cur, held in (
            ("FY25", 92100.58, 72485.95, 19614.63, 39476.11, 52594.06, 30.41),
            ("FY26", 108785.22, 83879.74, 24905.48, 44894.03, 63860.29, 30.9),
        ):
            assert by[("canonical.bs.total_assets", period)] == total
            assert by[("canonical.bs.total_liabilities_and_equity", period)] == total
            assert by[("canonical.bs.total_equity", period)] == equity
            assert by[("canonical.bs.total_liabilities", period)] == liabilities
            assert abs(equity + liabilities - total) < 1e-6, (
                "%s: %s + %s does not foot to %s" % (
                    period, equity, liabilities, total,
                )
            )
            got = (by[("canonical.bs.total_non_current_assets", period)]
                   + by[("canonical.bs.total_current_assets", period)] + held)
            assert abs(got - total) < 1e-6, (
                "%s: %s + %s + the withheld held-for-sale %s does not bridge "
                "to %s" % (period, noncur, cur, held, total)
            )


@needs_sun
class TestTheRecordStatesWhatTheBannerCannot:
    """The installed record, pinned beside the page it governs.

    The face states its scale in a form no pattern reads, and the record
    carries the witnessed fact beside the printed page. The end-to-end rows
    above prove both are consulted: the basis drives the parse and the parse
    drives the scale.
    """

    def test_the_record_names_the_face_and_its_basis(self):
        meta = json.loads(META.read_text(encoding="utf-8"))
        assert meta["balance_sheet_pages"] == [19]
        assert meta["declared_units"] == {"19": ["INR", "millions"]}
        assert meta["symbol"] == "SUNPHARMA"
