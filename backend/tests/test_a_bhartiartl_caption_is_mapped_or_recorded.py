"""Every caption on Bharti Airtel's audited consolidated face is mapped or recorded.

The filing (`bhartiartl-annual-2026-05.pdf`) prints its audited consolidated statement
at printed page 3 of an 89-page results booklet, and the page reads 85 rows across 41
distinct captions for FY25 and FY26. Nineteen canonical keys publish on the model's
crores basis; the rest are recorded elsewhere or refuse by design. Four facts about
this face are decided against its printed figures:

1. Basis. The record beside the page carries the witnessed basis -- INR millions --
   because the page declares nothing a pattern can match, and the model for
   `bhartiartl_bhartiartl` declares crores, so the branch scales every row by the
   definition (1 crore = 10 millions), the way Wipro's face is scaled. PUBLISHED
   below is crores throughout; the printed figures are the same numbers ten times
   over.

2. Glyph damage in the captions and, in one block, in the values. The FY26 column
   between "-na.d'e recei:Vabl'es" and the non-current subtotal yields five tokens
   for six caption slots, so captions from "-Loans" down pair one cell late against
   the true figures. The page's own subtotals prove it and witness what survives:
   the non-current assets subtotal 4,619,362 closes over the clean lines plus
   191,413 -- the single mangled token where the two tax assets print -- and the
   current-assets subtotal 902,154 closes exactly over 6,009 + 137,006 + 5,040 +
   79,776 + 137,222 + 166,546 + 244,264 + 125,718 + 573, so 125,718 is printed and
   the extracted 1,125,718 is a spurious leading digit.

3. Six withdrawals. Four captions whose cells cannot be trusted ("-Other
   ffinancral' assets" 37,471 / 35,700 where the subtotal arithmetic assigns the
   FY26 figure to "-Loans"; "Income taoc assets (net}" pairing the same shifted
   cell; "other current assets" reading the nine-times figure; "-Other financial
   liabilities" beside the exact-name line) and two whose keys the engine gives to
   lines that are not what they name ("-other financial: assets" 267,662 / 244,264
   to intangibles beside the printed intangibles, and the parent-only equity
   subtotal 1,136,719 / 1,490,566 to a share-count key). Three statics pin damaged
   captions whose figures the subtotals witness, and one routes the damaged
   investments caption directly to the current key the way Wipro's "lnvcstmcnts"
   was routed.

4. Four liability captions print in both sections and refuse each other as
   same-page same-half twins by design: "-Borrowings" (434,485 + 1,048,638 FY25),
   "-Lease liabilities" (96,597 + 556,701), "Deferred revenue" (35,185 + 97,729)
   and "Provisions" (30,396 + 361,552) publish nothing, and the debt stays
   feed-sourced. The receivables captions do NOT refuse: the damaged non-current
   printing carries no half claim, so it publishes beside the clean current line,
   the dual-row pattern Reliance shipped with.
"""
from __future__ import annotations

import json
from datetime import datetime
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

FILING = Path("backend/data/filings/nse/bhartiartl-annual-2026-05.pdf")
META = Path("backend/data/filings/nse/bhartiartl.json")

needs_bh = pytest.mark.skipif(
    not FILING.exists(), reason="the Bharti filing is absent"
)

# The whole face resolves to exactly these homes, on the model's crores basis
# (printed millions / 10). Lists, because trade receivables publishes two rows
# per period by design.
PUBLISHED = {
    "canonical.bs.cash_and_bank": {"FY25": [6105.6], "FY26": [13722.2]},
    "canonical.bs.current_investments": {"FY25": [1653.2], "FY26": [13700.6]},
    "canonical.bs.cwip": {"FY25": [10596.2], "FY26": [12613.1]},
    "canonical.bs.derivative_financial_assets_current": {
        "FY25": [192.1], "FY26": [191.8],
    },
    "canonical.bs.equity_capital": {"FY25": [2900.1], "FY26": [3046.8]},
    "canonical.bs.goodwill": {"FY25": [51697.4], "FY26": [56685.9]},
    "canonical.bs.intangible_assets": {"FY25": [133256.9], "FY26": [125260.4]},
    "canonical.bs.inventory": {"FY25": [451.7], "FY26": [600.9]},
    "canonical.bs.minority_interest": {"FY26": [46906.8]},
    "canonical.bs.non_current_investments": {"FY25": [543.5], "FY26": [1138.5]},
    "canonical.bs.other_current_liabilities": {"FY25": [7752.2], "FY26": [7734.1]},
    "canonical.bs.other_non_current_assets": {"FY26": [12477.0]},
    "canonical.bs.other_non_current_liabilities": {
        "FY25": [141.4], "FY26": [149.7],
    },
    "canonical.bs.ppe": {"FY25": [143272.4], "FY26": [157065.9]},
    "canonical.bs.total_assets": {"FY25": [514360.4], "FY26": [552151.6]},
    "canonical.bs.total_liabilities": {"FY25": [360892.7], "FY26": [356188.2]},
    "canonical.bs.total_liabilities_and_equity": {
        "FY25": [514360.4], "FY26": [552151.6],
    },
    "canonical.bs.trade_payables": {"FY25": [38153.7], "FY26": [45015.2]},
    # Two rows per period: the clean current line (74,557 / 79,776 printed) and
    # the damaged non-current printing with no half claim (2,131 / 2,544).
    "canonical.bs.trade_receivables": {
        "FY25": [213.1, 7455.7], "FY26": [254.4, 7977.6],
    },
}

# (caption, the FY26 figure the extraction would publish), AS PRINTED in millions:
# the decision is about which figure sits under which key, not about the scale.
WITHDRAWN = [
    ("-Other ffinancral' assets", 35700.0),
    ("-other financial: assets", 244264.0),
    ("Income taoc assets (net}", 20181.0),
    ("other current assets", 1125718.0),
    ("-Other financial liabilities", 408659.0),
    ("Equity attributable to owners of the parent", 1490566.0),
]

# Two printings of one line per period, millions as printed; none may publish.
TWINS = [
    ("-Borrowings", 434485.0, 1048638.0),
    ("-Lease liabilities", 96597.0, 556701.0),
    ("Deferred revenue", 35185.0, 97729.0),
    ("Provisions", 30396.0, 361552.0),
]


@lru_cache(maxsize=1)
def _face_rows():
    """The rows the product itself builds from the installed record."""
    meta = json.loads(META.read_text(encoding="utf-8"))
    return _filing_datapoints_from_cached_pdf(FILING, meta, "bhartiartl_bhartiartl")


def _grouped(canonical):
    """{(key, period): sorted [values]}, so a second row cannot hide."""
    out = {}
    for c in canonical:
        out.setdefault(c.canonical_key, {}).setdefault(
            c.period_label, []).append(c.value)
    return {
        key: {period: sorted(values) for period, values in periods.items()}
        for key, periods in out.items()
    }


def _raw(label: str, value: float, period: str = "FY25", *,
         page: str | None = None):
    from backend.data.store import RawDatapoint

    # With a page coordinate the same-page twin gate reads the rows as
    # printings of one page; without it the location carries no coordinate
    # and the gate never counts them, which is what the withdrawal fixtures
    # want because a withdrawal refuses before staging.
    location = ("bhartiartl-annual.pdf %s y=42" % page) if page else "fixture p.3"
    return RawDatapoint(
        id="bh-%s-%.1f-%s-%s" % (label[:8].replace(" ", ""), value, period,
                                 page or "n"),
        company_id="bhartiartl_bhartiartl",
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


class TestTheSixWithdrawnCaptionsNeverPublish:
    def test_each_is_withdrawn_and_not_mapped(self):
        for label, _value in WITHDRAWN:
            assert label in WITHDRAWN_LABELS, "%r is not recorded as withdrawn" % label
            assert label not in RAW_METRIC_MAP, (
                "%r is withdrawn AND mapped; a confirmed mapping outranks the "
                "withdrawal and the refusal would be dead on arrival" % label
            )
        assert len(WITHDRAWN) == 6, (
            "the withdrawal family changed size (%d); add or remove the caption "
            "itself, not silently the count" % len(WITHDRAWN)
        )

    def test_none_reaches_a_canonical_datapoint(self, tmp_path):
        for label, value in WITHDRAWN:
            canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
                [_raw(label, value)],
                db_path=tmp_path / "queue.db",
            )
            assert canonical == [], (
                "%r reached %s; a damaged cell or a misrouted subtotal must not "
                "publish under a key the reader takes as the whole" % (
                    label, [c.canonical_key for c in canonical],
                )
            )


class TestTheFourLiabilityTwinsRefuseBothPrintings:
    def test_the_twin_gate_refuses_all_eight_printings(self, tmp_path):
        for label, first, second in TWINS:
            canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
                [_raw(label, first, page="p.3"), _raw(label, second, page="p.3")],
                db_path=tmp_path / "queue.db",
            )
            assert canonical == [], (
                "%r published one of its two printings (%s); one key cannot "
                "hold two figures for one period" % (
                    label, [c.value for c in canonical],
                )
            )


@needs_bh
class TestTheDeclaredBasisIsRecordedAndThenScaled:
    def test_the_parser_reads_the_recorded_basis_as_printed(self):
        rows = parse_predicted_statement_page(
            FILING, 2, "BALANCE SHEET", "nse_filing",
            annual_only=False, company_id="bhartiartl_bhartiartl",
            declared_units_override=("INR", "millions"),
        )
        assert {(d.currency, d.units) for d in rows} == {("INR", "millions")}, (
            "the recorded basis did not reach every row"
        )
        total = [
            d.value for d in rows
            if d.metric_raw == "Total assets" and d.period_label == "FY25"
        ]
        assert total == [5143604.0], (
            "the printed total must read as printed before any scaling: %s" % total
        )

    def test_the_branch_delivers_the_rows_on_the_model_basis(self):
        rows = _face_rows()
        assert len(rows) == 85, "the page reads %d rows" % len(rows)
        assert {(d.currency, d.units) for d in rows} == {("INR", "crores")}, (
            "rows must arrive on the basis the model declares; got %s"
            % {(d.currency, d.units) for d in rows}
        )
        assert {d.period_label for d in rows} == {"FY25", "FY26"}
        total = [
            d.value for d in rows
            if d.metric_raw == "Total assets" and d.period_label == "FY25"
        ]
        assert total == [514360.4], (
            "the total must be the printed figure scaled by the recorded "
            "factor: %s" % total
        )


@needs_bh
class TestTheWholeFaceResolvesToExactlyTheseHomes:
    def test_every_caption_reaches_its_home_with_the_expected_figure(
        self, tmp_path
    ):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=tmp_path / "queue.db"
        )
        assert _grouped(canonical) == PUBLISHED, (
            "the face must resolve to exactly nineteen homes on the model's "
            "crores basis; extra: %s, missing: %s" % (
                {k: _grouped(canonical)[k]
                 for k in set(_grouped(canonical)) - set(PUBLISHED)},
                {k: PUBLISHED[k] for k in set(PUBLISHED) - set(_grouped(canonical))},
            )
        )
        assert len(canonical) == 38, (
            "the face publishes %d rows, two of them second receivables "
            "printings" % len(canonical)
        )


@needs_bh
class TestTheLinesBesideTheWithdrawalsTakeTheirKeys:
    def test_the_completed_intangibles_hold_their_key_alone(self, tmp_path):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=tmp_path / "queue.db"
        )
        by = _grouped(canonical)
        assert by["canonical.bs.intangible_assets"]["FY26"] == [125260.4], (
            "the key must hold the printed \"Other intangible assets\" "
            "(1,252,604 millions), not a financial-asset line"
        )

    def test_the_damaged_current_line_left_its_key_to_the_exact_name(
        self, tmp_path
    ):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=tmp_path / "queue.db"
        )
        by = _grouped(canonical)
        assert by["canonical.bs.other_current_liabilities"]["FY26"] == [7734.1], (
            "the key must hold the printed \"Other current liabilities\" "
            "(77,341 millions) alone"
        )
        assert by["canonical.bs.current_investments"]["FY26"] == [13700.6], (
            "the damaged investments caption must reach the current key "
            "directly (137,006 millions printed)"
        )
        assert by["canonical.bs.other_non_current_assets"]["FY26"] == [12477.0], (
            "the witnessed figure (124,770 printed) must survive its damaged "
            "caption"
        )

    def test_the_nine_times_reading_did_not_publish(self, tmp_path):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=tmp_path / "queue.db"
        )
        keys = {c.canonical_key for c in canonical}
        assert "canonical.bs.prepayments_other_current_assets" not in keys, (
            "the extracted 1,125,718 would publish nine times the printed "
            "125,718 the current-assets subtotal closes with"
        )
        assert "canonical.bs.income_tax_assets" not in keys, (
            "the income-tax caption's FY26 cell pairs another line's figure"
        )
        assert "canonical.meta.share_count" not in keys, (
            "a balance-sheet subtotal reached the share-count key"
        )


@needs_bh
class TestTheFootingClosesWhereThePagePrintsBothSides:
    def test_both_sides_report_the_same_total(self, tmp_path):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=tmp_path / "queue.db"
        )
        by = _grouped(canonical)
        for period, total, liabilities in (
            ("FY25", 514360.4, 360892.7),
            ("FY26", 552151.6, 356188.2),
        ):
            assert by["canonical.bs.total_assets"][period] == [total]
            assert by["canonical.bs.total_liabilities_and_equity"][period] == [total]
            assert by["canonical.bs.total_liabilities"][period] == [liabilities], (
                "the total must be the sum of the two printed liability "
                "halves: 1,804,525 + 1,804,402 at FY25, 1,816,825 + "
                "1,745,057 at FY26, millions"
            )

    def test_the_identity_closes_on_the_printed_equity_block(self, tmp_path):
        """The equity side publishes no total of its own; the printed one closes it.

        Total equity prints as the parent-only caption plus the non-controlling
        interests (1,490,566 + 469,068 at FY26, 1,136,719 + 368,957 at FY25,
        millions). The parent caption is withdrawn -- the engine routed it to a
        share-count key -- so the witnessed figure bridges the identity beside
        the two published totals.
        """
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=tmp_path / "queue.db"
        )
        by = _grouped(canonical)
        for period, total, liabilities, equity in (
            ("FY25", 514360.4, 360892.7, 153467.7),
            ("FY26", 552151.6, 356188.2, 195963.4),
        ):
            got = by["canonical.bs.total_liabilities"][period][0] + equity
            assert abs(got - total) < 1e-9, (
                "%s: liabilities %s + the witnessed printed equity %s does "
                "not foot to %s" % (
                    period, by["canonical.bs.total_liabilities"][period][0],
                    equity, total,
                )
            )
