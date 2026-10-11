"""Every caption on Larsen & Toubro's audited consolidated face is mapped or recorded.

The filing (`lt-annual-2026-05.pdf`) prints its audited consolidated balance sheet
across printed pages 617-618 of the FY26 integrated report, and the two pages read
107 rows across 47 distinct captions for FY25 and FY26 in INR crores -- the basis
the model declares, so no branch scales. Twenty-two canonical keys publish; the rest
are recorded elsewhere or refuse by design. Five facts about this face are decided
against its printed figures:

1. The whole face closes. At FY26: equity 128,530.46 + non-current liabilities
   69,521.91 + current liabilities 233,531.47 + the held-for-sale liability
   20,966.04 (no key of its own) = 452,549.88 = the printed TOTAL ASSETS =
   TOTAL EQUITY AND LIABILITIES, and each asset half foots to its printed
   sub-total (134,238.56 + 292,841.13 + 25,470.19 held for sale = 452,549.88).
   FY25 closes the same way.

2. The title's year is not a column. The caption "Consolidated Balance Sheet as
   at March 31, 2026" ends right of the label boundary, and the companion test
   (`test_a_lone_year_in_a_title_is_not_a_column_anchor.py`) pins the anchoring
   rule this required. With the title refused, the note column stays notes and
   the figures read as printed.

3. Five withdrawals. The note-suffixed deferred-tax LIABILITY the engine sends
   to the tax-assets key, where the printed assets (3,792.88 / 4,252.76) already
   sit; the three section subtotals the engine sends to each section's exact-name
   detail key, where the twin gate would refuse both lines; and the trade-payables
   slice the engine sends to the whole-line key while the filer prints payables
   in two parts and states no sum (1,840.35 + 67,615.28 = 69,455.63 at FY26).
   "Sub-total - Current assets" is NOT withdrawn: it reaches its own key
   (total_current_assets) with no rival beside it.

4. The reviewed investments decision. Bare "Investments" is withdrawn globally
   because no label rule can pick current against non-current, but the store
   carries a human-confirmed row for THIS company's caption, made by reading the
   sheet: the filing's current-section row (43,360.62 / 59,524.86, foot-verified
   in the current-assets sub-total) reaches current_investments through it, and
   without that row the line would be refused like every other bare
   "Investments". The test seeds exactly that decision.

5. Three liability captions print in both sections and refuse each other as
   same-page twins by design: Borrowings (57,503.34 + 35,861.30 at FY25),
   Lease liabilities (2,265.24 + 584.34) and Provisions (4,691.67 + 1,124.01)
   publish nothing from the filing and the debt stays feed-sourced. The standing
   withdrawals of the earlier faces carry their cost here as recorded: other
   equity, the parent-only equity subtotal the engine would have sent to net
   profit, the current tax liabilities, intangibles under development and the
   financial-asset and financial-liability lines all stay out. Nine captions
   queue unmapped with no key of their own.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pytest

from backend.data.pipeline import _filing_datapoints_from_cached_pdf
from backend.normalization.financials import mapper
from backend.normalization.taxonomy.registry import (
    RAW_METRIC_MAP,
    WITHDRAWN_LABELS,
)

FILING = Path("backend/data/filings/nse/lt-annual-2026-05.pdf")
META = Path("backend/data/filings/nse/lt.json")

needs_lt = pytest.mark.skipif(
    not FILING.exists(), reason="the L&T filing is absent"
)

# The whole face resolves to exactly these homes, in crores as printed (the
# model declares crores, so no branch scales), WITH the reviewed "Investments"
# decision the live store carries seeded below.
PUBLISHED = {
    "canonical.bs.cash_and_bank": {"FY25": [12187.0], "FY26": [15391.24]},
    "canonical.bs.current_investments": {"FY25": [43360.62], "FY26": [59524.86]},
    "canonical.bs.cwip": {"FY25": [2390.86], "FY26": [3036.25]},
    "canonical.bs.deferred_tax_assets": {"FY25": [3792.88], "FY26": [4252.76]},
    "canonical.bs.equity_capital": {"FY25": [275.04], "FY26": [275.13]},
    "canonical.bs.goodwill": {"FY25": [8348.48], "FY26": [8481.54]},
    "canonical.bs.intangible_assets": {"FY25": [17050.76], "FY26": [1828.21]},
    "canonical.bs.inventory": {"FY25": [7670.55], "FY26": [9530.93]},
    "canonical.bs.minority_interest": {"FY25": [17748.08], "FY26": [19240.66]},
    "canonical.bs.non_current_investments": {"FY25": [2318.42], "FY26": [2258.01]},
    "canonical.bs.other_current_liabilities": {
        "FY25": [63326.97], "FY26": [85861.52],
    },
    "canonical.bs.other_non_current_assets": {
        "FY25": [2659.78], "FY26": [2699.49],
    },
    "canonical.bs.other_non_current_liabilities": {
        "FY25": [594.74], "FY26": [36.82],
    },
    "canonical.bs.ppe": {"FY25": [14128.56], "FY26": [15663.02]},
    "canonical.bs.prepayments_other_current_assets": {
        "FY25": [75559.83], "FY26": [91303.18],
    },
    "canonical.bs.short_term_borrowings": {"FY25": [36194.7], "FY26": [23165.9]},
    "canonical.bs.total_assets": {"FY25": [379524.1], "FY26": [452549.88]},
    "canonical.bs.total_current_assets": {
        "FY25": [245184.27], "FY26": [292841.13],
    },
    "canonical.bs.total_equity": {"FY25": [115403.68], "FY26": [128530.46]},
    "canonical.bs.total_liabilities": {"FY25": [264120.42], "FY26": [324019.42]},
    "canonical.bs.total_liabilities_and_equity": {
        "FY25": [379524.1], "FY26": [452549.88],
    },
    "canonical.bs.trade_receivables": {
        "FY25": [53713.68], "FY26": [60461.26],
    },
}

# (caption, the FY26 figure that must not publish), crores as printed: the
# decision is about which figure sits under which key, not about the scale.
WITHDRAWN = [
    ("Deferred tax liabilities (net) 51(d)", 167.11),
    ("Sub-total - Current liabilities", 233531.47),
    ("Sub-total - Non-current assets", 134238.56),
    ("Sub-total - Non-current liabilities", 69521.91),
    ("Due to micro enterprises and small enterprises", 1840.35),
]

# Two printings of one line per period (the two sections), FY25 pairings as
# printed; none may publish.
TWINS = [
    ("Borrowings", 35861.3, 57503.34),
    ("Lease liabilities", 584.34, 2265.24),
    ("Provisions", 1124.01, 4691.67),
]


@lru_cache(maxsize=1)
def _face_rows():
    """The rows the product itself builds from the installed record."""
    meta = json.loads(META.read_text(encoding="utf-8"))
    return _filing_datapoints_from_cached_pdf(FILING, meta, "lt_lt")


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


def _db_with_reviewed_investment(path):
    """The reviewed decision the live store carries for this company's caption."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE taxonomy_mappings (id TEXT PRIMARY KEY, company_id TEXT, "
        "canonical_key TEXT, metric_raw TEXT, statement TEXT, source TEXT, "
        "human_confirmed INTEGER, update_date TEXT)"
    )
    conn.execute(
        "INSERT INTO taxonomy_mappings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("lt-investments", "lt_lt", "canonical.bs.current_investments",
         "Investments", "bs", "screener", 1, "2026-10-02T12:13:02"),
    )
    conn.commit()
    conn.close()
    return path


def _raw(label: str, value: float, period: str = "FY25", *,
         page: str | None = None, bs_half: str | None = None):
    from backend.data.store import RawDatapoint

    location = ("lt-annual.pdf %s y=42" % page) if page else "fixture p.618"
    return RawDatapoint(
        id="lt-%s-%.1f-%s-%s" % (label[:8].replace(" ", ""), value, period,
                                 page or "n"),
        company_id="lt_lt",
        metric_raw=label,
        period_label=period,
        period_end_date=datetime(2026 if period == "FY26" else 2025, 3, 31).date(),
        value=value,
        currency="INR",
        units="crores",
        source="nse_filing",
        source_location=location,
        section="BALANCE SHEET",
        bs_half=bs_half,
        status="reported",
        update_date=datetime.now(),
    )


class TestTheFiveWithdrawnCaptionsNeverPublish:
    def test_each_is_withdrawn_and_not_mapped(self):
        for label, _value in WITHDRAWN:
            assert label in WITHDRAWN_LABELS, "%r is not recorded as withdrawn" % label
            assert label not in RAW_METRIC_MAP, (
                "%r is withdrawn AND mapped; a confirmed mapping outranks the "
                "withdrawal and the refusal would be dead on arrival" % label
            )
        assert len(WITHDRAWN) == 5, (
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
                "%r reached %s; a sub-total is not the line it totals and a "
                "liability is not an asset" % (
                    label, [c.canonical_key for c in canonical],
                )
            )


class TestTheThreeLiabilityTwinsRefuseBothPrintings:
    def test_the_twin_gate_refuses_all_six_printings(self, tmp_path):
        """These pages print no asset header, so every row carries no half.

        The two sections' captions meet in the same bucket and refuse, which is
        the documented design: neither half publishes a figure the reader would
        take for the whole.
        """
        for label, first, second in TWINS:
            canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
                [_raw(label, first, page="p.618"),
                 _raw(label, second, page="p.618")],
                db_path=tmp_path / "queue.db",
            )
            assert canonical == [], (
                "%r published one of its two printings (%s)" % (
                    label, [c.value for c in canonical],
                )
            )


@needs_lt
class TestTheReviewedInvestmentsDecisionSurvives:
    def test_the_confirmed_mapping_publishes_the_printed_rows(self, tmp_path):
        db = _db_with_reviewed_investment(tmp_path / "store.db")
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=db
        )
        by = _grouped(canonical)
        assert by["canonical.bs.current_investments"] == {
            "FY25": [43360.62], "FY26": [59524.86],
        }, (
            "the reviewed decision did not survive the static withdrawal: %s"
            % by.get("canonical.bs.current_investments")
        )

    def test_without_the_confirmation_the_caption_stays_withdrawn(
        self, tmp_path
    ):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=tmp_path / "plain.db"
        )
        assert "canonical.bs.current_investments" not in {
            c.canonical_key for c in canonical
        }, (
            "bare \"Investments\" published with nothing behind the withdrawal; "
            "the reviewed row is what licenses it"
        )


@needs_lt
class TestTheWholeFaceResolvesToExactlyTheseHomes:
    def test_every_caption_reaches_its_home_with_the_expected_figure(
        self, tmp_path
    ):
        db = _db_with_reviewed_investment(tmp_path / "store.db")
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=db
        )
        assert _grouped(canonical) == PUBLISHED, (
            "the face must resolve to exactly twenty-two homes in crores; "
            "extra: %s, missing: %s" % (
                {k: _grouped(canonical)[k]
                 for k in set(_grouped(canonical)) - set(PUBLISHED)},
                {k: PUBLISHED[k] for k in set(PUBLISHED) - set(_grouped(canonical))},
            )
        )
        assert len(canonical) == 44, (
            "the face publishes %d rows" % len(canonical)
        )


@needs_lt
class TestTheLinesBesideTheWithdrawalsTakeTheirKeys:
    def test_the_subtotals_left_the_exact_name_lines_alone(self, tmp_path):
        db = _db_with_reviewed_investment(tmp_path / "store.db")
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=db
        )
        by = _grouped(canonical)
        assert by["canonical.bs.other_current_liabilities"]["FY26"] == [85861.52], (
            "the key must hold the printed \"Other current liabilities\" "
            "alone, not refuse both lines beside the 233,531.47 sub-total"
        )
        assert by["canonical.bs.other_non_current_assets"]["FY26"] == [2699.49]
        assert by["canonical.bs.other_non_current_liabilities"]["FY26"] == [36.82]
        assert by["canonical.bs.total_current_assets"]["FY26"] == [292841.13], (
            "this sub-total reaches its own key with no rival and must keep "
            "publishing"
        )

    def test_the_tax_asset_key_holds_the_assets_not_the_liability(
        self, tmp_path
    ):
        db = _db_with_reviewed_investment(tmp_path / "store.db")
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=db
        )
        by = _grouped(canonical)
        assert by["canonical.bs.deferred_tax_assets"] == {
            "FY25": [3792.88], "FY26": [4252.76],
        }, (
            "the key must hold the printed tax ASSETS, not the 410.01 / 167.11 "
            "liability the engine routed here at medium confidence"
        )

    def test_the_payables_slice_did_not_publish_as_the_line(self, tmp_path):
        db = _db_with_reviewed_investment(tmp_path / "store.db")
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=db
        )
        assert "canonical.bs.trade_payables" not in {
            c.canonical_key for c in canonical
        }, (
            "the micro-enterprises slice (1,840.35) would publish as the whole "
            "line the filer prints in two parts (1,840.35 + 67,615.28)"
        )


@needs_lt
class TestTheFootingClosesOnBothPeriods:
    def test_both_sides_report_the_same_total(self, tmp_path):
        db = _db_with_reviewed_investment(tmp_path / "store.db")
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=db
        )
        by = _grouped(canonical)
        for period, total, equity, liabilities in (
            ("FY25", 379524.1, 115403.68, 264120.42),
            ("FY26", 452549.88, 128530.46, 324019.42),
        ):
            assert by["canonical.bs.total_assets"][period] == [total]
            assert by["canonical.bs.total_liabilities_and_equity"][period] == [total]
            assert by["canonical.bs.total_equity"][period] == [equity]
            assert by["canonical.bs.total_liabilities"][period] == [liabilities]
            assert abs(equity + liabilities - total) < 1e-6, (
                "%s: %s + %s does not foot to %s" % (
                    period, equity, liabilities, total,
                )
            )

    def test_the_equity_block_nests_as_printed(self, tmp_path):
        """The parent-attributable caption already contains the share capital.

        275.13 + 109,014.67 = 109,289.80 (the printed parent total at FY26;
        275.04 + 97,380.56 = 97,655.60 at FY25), so the printed TOTAL EQUITY is
        the parent total plus the non-controlling interests. The parent caption
        and other equity are withdrawn, so the witnessed figures close the
        block beside the published ones.
        """
        db = _db_with_reviewed_investment(tmp_path / "store.db")
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=db
        )
        by = _grouped(canonical)
        for period, equity, parent, nci in (
            ("FY25", 115403.68, 97655.60, 17748.08),
            ("FY26", 128530.46, 109289.80, 19240.66),
        ):
            assert abs(parent + nci - equity) < 1e-6, (
                "%s: the witnessed parent total %s + non-controlling "
                "interests %s does not foot to the published equity %s" % (
                    period, parent, nci, equity,
                )
            )
            assert by["canonical.bs.minority_interest"][period] == [nci]

    def test_the_sheets_bridge_on_the_withheld_subtotals(self, tmp_path):
        """Each side bridges to the total through figures the record keeps out.

        The non-current assets sub-total is withdrawn (its engine destination
        belonged to the exact-name line), and the held-for-sale lines have no
        key at all, so the published current-assets sub-total plus those two
        witnessed figures must reach TOTAL ASSETS; the liability side bridges
        the same way through the two withheld subtotals' sections.
        """
        db = _db_with_reviewed_investment(tmp_path / "store.db")
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            list(_face_rows()), db_path=db
        )
        by = _grouped(canonical)
        for period, total, current, noncur, held, nc_liab, cur_liab, held_liab in (
            ("FY25", 379524.1, 245184.27, 134182.39, 157.44,
             62149.52, 201970.9, 0.0),
            ("FY26", 452549.88, 292841.13, 134238.56, 25470.19,
             69521.91, 233531.47, 20966.04),
        ):
            got = by["canonical.bs.total_current_assets"][period][0] + noncur + held
            assert abs(got - total) < 1e-6, (
                "%s: current assets %s + the withheld non-current sub-total "
                "%s + held for sale %s does not bridge to %s" % (
                    period, current, noncur, held, total,
                )
            )
            got = nc_liab + cur_liab + held_liab
            assert abs(got - by["canonical.bs.total_liabilities"][period][0]) < 1e-6, (
                "%s: the printed liability sections %s + %s + the unmapped "
                "held-for-sale liability %s do not bridge to the published "
                "total liabilities" % (period, nc_liab, cur_liab, held_liab),
            )
