"""Every caption on Wipro's audited consolidated face is mapped or recorded.

The filing (`wipro-annual-2026-04.pdf`) prints its audited consolidated balance
sheet at printed page 21, and the page reads 100 rows across 40 distinct
captions for FY25 and FY26. Fifteen captions reach a canonical key; the rest
are recorded elsewhere or refuse by design. Three facts about this face are
decided against its printed figures rather than its labels:

1. Basis. The face prints INR in millions: the page declares nothing a pattern
   can read, the record in `wipro.json` carries the witnessed basis, and the
   statement's own arithmetic confirms it (paid-up 20,944 million is 1,047 crore
   shares at Rs 2). The model for `wipro_wipro` declares crores, and a model is
   single-basis by design, so `_in_model_basis` scales the rows by the
   definition -- millions are a tenth of a crore -- the way `us_live.py`
   divides dollars by 1e6 before its rows exist. The store therefore holds the
   model's crores; every figure in PUBLISHED below is that. The printed figure
   is the same number ten times over, and the record of what the page declared
   stays beside the page it was declared on.

2. Separators. The thousands separator extracts as a period in some cells, a
   comma in others, and both inside one figure ("1.414,077"), so the number
   reader takes the dot-grouped form as thousands (pinned in
   test_a_figure_grouped_with_dots_reads_as_thousands). The page witnesses the
   reading in its own printing: 587,723 + 826,354 = 1,414,077, the
   comma-printed total, and both sides of the sheet report the same total on
   both periods.

3. Four captions lost their final words in extraction, and on each the words
   that went were the ones saying assets or liabilities. "Non-current" carries
   the non-current TAX LIABILITIES (42,024 / 48,195 as printed) and the engine
   would publish them as non_current_investments; "Other non-current" carries
   the other non-current LIABILITIES (12,757 / 17,877) toward
   other_non_current_assets; "Total current" carries the total current
   LIABILITIES (286,253 / 403,232) toward total_current_assets, where they
   would collide with the caption that does say assets; "Equity attributable"
   carries the parent-only equity (823,641 / 880,183) toward total_equity,
   where it would collide with the printed TOTAL EQUITY that includes the
   non-controlling interests (2,138 / 2,509). All four are withdrawn, and the
   two collisions resolve: the totals publish.

The current block foots only with the damaged "lnvcstmcnts" line included:
the parsed current assets plus the one refused cash cell sum to 777,775 at
FY25 and 826,354 at FY26, the printed subtotals, to the rupee. That line is
the current investments (411,474 / 437,680 as printed) and it is mapped as
such.

The face also prints two visible refusals rather than guesses: FY26 cash
extracts as "I 05.555" and FY25 capital work-in-progress as "1,96-1", so
cash_and_bank carries FY25 alone and cwip FY26 alone.
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

FILING = Path("backend/data/filings/nse/wipro-annual-2026-04.pdf")
META = Path("backend/data/filings/nse/wipro.json")

needs_wipro = pytest.mark.skipif(
    not FILING.exists(), reason="the Wipro filing is absent"
)

# The whole face resolves to exactly these fifteen homes, on the model's crores
# basis. The two keys that must stay EMPTY are the two the fragments would
# have fed: non_current_investments (the engine's home for "Non-current") and
# other_non_current_assets (the engine's home for "Other non-current").
PUBLISHED = {
    "canonical.bs.cash_and_bank": {"FY25": 12197.4},
    "canonical.bs.current_income_tax_assets": {"FY25": 641.7, "FY26": 1076.2},
    "canonical.bs.current_investments": {"FY25": 41147.4, "FY26": 43768.0},
    "canonical.bs.cwip": {"FY26": 412.2},
    "canonical.bs.equity_capital": {"FY25": 2094.4, "FY26": 2097.7},
    "canonical.bs.goodwill": {"FY25": 32034.6, "FY26": 38221.4},
    "canonical.bs.intangible_assets": {"FY25": 2745.0, "FY26": 2917.6},
    "canonical.bs.inventory": {"FY25": 69.4, "FY26": 51.7},
    "canonical.bs.minority_interest": {"FY25": 213.8, "FY26": 250.9},
    "canonical.bs.ppe": {"FY25": 7847.3, "FY26": 7722.4},
    "canonical.bs.total_assets": {"FY25": 128185.2, "FY26": 141407.7},
    "canonical.bs.total_current_assets": {"FY25": 77777.5, "FY26": 82635.4},
    "canonical.bs.total_equity": {"FY25": 82577.9, "FY26": 88269.2},
    "canonical.bs.total_liabilities": {"FY25": 45607.3, "FY26": 53138.5},
    "canonical.bs.total_liabilities_and_equity": {
        "FY25": 128185.2, "FY26": 141407.7,
    },
}

# (printed caption, printed figure, period) for the four fragments whose
# final words were lost, stated AS PRINTED in millions because the decision is
# about which figure sits under which words, not about the scale: 48,195 is a
# tax liability, 17,877 a liability, 403,232 the total current liabilities,
# and 880,183 the equity attributable to the parent alone. The branch scales
# these rows to crores (4,819.5 and so on) before the mapper ever sees them;
# the registry does not read units, so either statement of the same figure
# reaches the same decision.
WITHDRAWN_FIGURES = [
    ("Non-current", 48195.0, "FY26"),
    ("Other non-current", 17877.0, "FY26"),
    ("Total current", 403232.0, "FY26"),
    ("Equity attributable", 880183.0, "FY26"),
]


@lru_cache(maxsize=1)
def _face_rows():
    """The rows the product itself builds from the installed record."""
    meta = json.loads(META.read_text(encoding="utf-8"))
    return _filing_datapoints_from_cached_pdf(FILING, meta, "wipro_wipro")


def _raw(label: str, value: float, period: str = "FY26"):
    from datetime import datetime

    from backend.data.store import RawDatapoint

    # The location carries no " y=" on purpose: the same-page twin gate reads a
    # page coordinate as a second printing, and what these tests pin is the
    # registry's decision for the caption rather than the row's fate on the
    # real page.
    return RawDatapoint(
        id="wipro-%s-%.0f-%s" % (
            label[:8].replace(" ", ""), value, period,
        ),
        company_id="wipro_wipro",
        metric_raw=label,
        period_label=period,
        period_end_date=datetime(2026 if period == "FY26" else 2025, 3, 31).date(),
        value=value,
        currency="INR",
        units="millions",
        source="nse_filing",
        source_location="fixture p.21",
        section="BALANCE SHEET",
        bs_half=None,
        status="reported",
        update_date=datetime.now(),
    )


class TestTheFragmentsThatLostTheirNounsAreRecorded:
    def test_each_is_withdrawn_and_not_mapped(self):
        for label, _value, _period in WITHDRAWN_FIGURES:
            assert label in WITHDRAWN_LABELS, "%r is not recorded as withdrawn" % label
            assert label not in RAW_METRIC_MAP, (
                "%r is withdrawn AND mapped; a confirmed mapping outranks the "
                "withdrawal and the refusal would be dead on arrival" % label
            )
        assert len(WITHDRAWN_FIGURES) == 4, (
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
                "%r reached %s; it is a liability the engine would have "
                "published under an asset key" % (
                    label, [c.canonical_key for c in canonical],
                )
            )


class TestTheWithdrawalResolvesTheTotalsThatShareTheirWords:
    """The two collisions the withdrawals were chosen to break.

    "Equity attributable" and "TOTAL EQUITY" both reach total_equity, and
    "Total current" and "Total current assets" both reach
    total_current_assets. Before the withdrawals the mapper refused every row
    of both pairs as a same-page conflict; the point of withdrawing the
    fragments is that the totals publish.
    """

    def test_the_printed_totals_publish_with_the_printed_figures(self, tmp_path):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            [
                _raw("Equity attributable", 880183.0),
                _raw("TOTAL EQUITY", 882692.0),
                _raw("Total current", 403232.0),
                _raw("Total current assets", 826354.0),
            ],
            db_path=tmp_path / "queue.db",
        )
        by = {(c.canonical_key, c.period_label): c.value for c in canonical}
        assert by == {
            ("canonical.bs.total_equity", "FY26"): 882692.0,
            ("canonical.bs.total_current_assets", "FY26"): 826354.0,
        }, "the totals must publish and the fragments must not: %s" % by


@needs_wipro
class TestTheDeclaredBasisIsReadAndThenScaled:
    """Two mechanisms, each asserted where it acts.

    The parser reads what the page's record declares: INR in millions, every
    row, the printed total untouched. The branch then scales to the model's
    crores. A test that saw only the store's rows could not tell a declared
    basis from an assumed one, and a test that saw only the parser's rows
    would let the store hold a scale its model rejects.
    """

    def test_the_parser_reads_the_recorded_basis_as_printed(self):
        rows = parse_predicted_statement_page(
            FILING, 20, "BALANCE SHEET", "nse_filing",
            annual_only=False, company_id="wipro_wipro",
            declared_units_override=("INR", "millions"),
        )
        assert {(d.currency, d.units) for d in rows} == {("INR", "millions")}, (
            "the recorded basis did not reach every row"
        )
        total = [
            d.value for d in rows
            if d.metric_raw == "TOTAL ASSETS" and d.period_label == "FY26"
        ]
        assert total == [1414077.0], (
            "the printed total must read as printed before any scaling: %s" % total
        )

    def test_the_branch_delivers_the_rows_on_the_model_basis(self):
        rows = _face_rows()
        assert len(rows) == 100, "the page reads %d rows" % len(rows)
        assert {(d.currency, d.units) for d in rows} == {("INR", "crores")}, (
            "rows must arrive on the basis the model declares; got %s"
            % {(d.currency, d.units) for d in rows}
        )
        assert {d.period_label for d in rows} == {"FY25", "FY26"}
        total = [
            d.value for d in rows
            if d.metric_raw == "TOTAL ASSETS" and d.period_label == "FY26"
        ]
        assert total == [141407.7], (
            "the total must be the printed figure scaled by the recorded "
            "factor: %s" % total
        )


@needs_wipro
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
            "the face must resolve to exactly fifteen homes on the model "
            "basis; extra: %s, missing: %s" % (
                {k: by[k] for k in set(by) - set(expected)},
                {k: expected[k] for k in set(expected) - set(by)},
            )
        )

    def test_the_two_inversion_keys_stay_empty(self, tmp_path):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=tmp_path / "queue.db"
        )
        keys = {c.canonical_key for c in canonical}
        assert "canonical.bs.non_current_investments" not in keys, (
            "the non-current tax liabilities (4,202.4 / 4,819.5 crores) "
            "published as an investment"
        )
        assert "canonical.bs.other_non_current_assets" not in keys, (
            "the other non-current liabilities (1,275.7 / 1,787.7 crores) "
            "published in the asset column"
        )
        assert "canonical.meta.share_count" not in keys, (
            "a balance-sheet figure reached the share-count key: %s" % keys
        )


@needs_wipro
class TestTheFootingClosesOnBothPeriods:
    """The identity the whole face turns on, on the basis the store holds.

    Equity plus liabilities equals the printed total on both periods, and the
    footing line reports the same figure on both sides of the sheet. If any
    caption routed elsewhere -- or the dot-grouped read ever changed its mind
    about "1.414,077" -- these pairs would disagree. The printed figures and
    the stored ones are the same arithmetic at a tenth the scale: 128,185.2 =
    82,577.9 + 45,607.3 crores is 1,281,852 = 825,779 + 456,073 million.
    """

    def test_both_sides_report_the_same_total(self, tmp_path):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=tmp_path / "queue.db"
        )
        by = {(c.canonical_key, c.period_label): c.value for c in canonical}
        for period, total, equity, liabilities in (
            ("FY25", 128185.2, 82577.9, 45607.3),
            ("FY26", 141407.7, 88269.2, 53138.5),
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


@needs_wipro
class TestTheRecordStatesWhatThePageCannot:
    """The installed record, pinned beside the page it governs.

    The face prints no units banner any pattern can read, and its statements
    are the second balance sheet in the document. The record carries both
    facts -- the printed page and the witnessed basis -- and the end-to-end
    rows above prove they are consulted: the basis drives the parse, and the
    parse drives the scale.
    """

    def test_the_record_names_the_face_and_its_basis(self):
        meta = json.loads(META.read_text(encoding="utf-8"))
        assert meta["balance_sheet_pages"] == [21]
        assert meta["declared_units"] == {"21": ["INR", "millions"]}
        assert meta["symbol"] == "WIPRO"
