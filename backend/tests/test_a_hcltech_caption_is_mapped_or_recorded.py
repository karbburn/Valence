"""A printed HCLTech caption is either mapped to its key or recorded as withdrawn.

The audited Ind-AS balance sheet (printed page 4 of `hcltech-indas-2026-04.pdf`)
prints 43 distinct captions. Twenty-six reach existing keys with the figure the
face prints under those exact words, sixteen are withdrawn with the reason on
file, and one -- "(ii) Trade receivables -unbilled", whose only prints sit in
the non-current block -- is registered but declined by the half guard, which
claims current-asset keys for current rows exactly as it declines TCS's
non-current "Unbilled".

An unmapped caption reads as an accident; a caption publishing under a name
that states something false about it is worse, which is most of what the
withdrawn sixteen would do. "Billed" and "Unbilled" each print twice under the
same half (the gate refuses both printings; see
`test_a_line_printed_twice_on_one_page_publishes_neither.py`), the equity
component captions whose keys would collide across the two blocks of one face,
and "Equity attributable to owners of the Company", whose own components were
withdrawn so publishing the roll-up would restate equity twice.

Three captions carry ToUnicode artifacts in their extracted text ("non..:urrent"
for "non-current", "Non..:ontrolling" for "Non-controlling"): the figures
beside them read clean and foot the page, so the extracted strings are what the
registry maps -- a prettier caption would never match what the reader receives.
"""
from __future__ import annotations

from datetime import datetime

from backend.data.store import RawDatapoint
from backend.normalization.financials import mapper
from backend.normalization.taxonomy.registry import (
    RAW_METRIC_MAP,
    WITHDRAWN_LABELS,
)

# (printed caption, printed FY26 figure, canonical key)
MAPPED_FIGURES = [
    ("(a) Property, plant and equipment", 4657.0, "canonical.bs.ppe"),
    ("(b) Capital work in progress", 60.0, "canonical.bs.cwip"),
    ("(d) Goodwill", 23888.0, "canonical.bs.goodwill"),
    ("(e) Other intangible assets", 5160.0, "canonical.bs.intangible_assets"),
    ("(h) Deferred tax assets (net)", 1146.0, "canonical.bs.deferred_tax_assets"),
    ("(i) Investments", 130.0, "canonical.bs.non_current_investments"),
    ("(i) Other non..:urrent assets", 2765.0, "canonical.bs.other_non_current_assets"),
    ("Total non..:urrent assets", 45716.0, "canonical.bs.total_non_current_assets"),
    ("(a) Inventories", 239.0, "canonical.bs.inventory"),
    ("(iii) Cash and cash equivalents", 8265.0, "canonical.bs.cash_and_bank"),
    ("(c) Current tax assets (net)", 226.0, "canonical.bs.current_income_tax_assets"),
    ("(d ) Other current assets", 5508.0, "canonical.bs.prepayments_other_current_assets"),
    ("Total current assets", 70542.0, "canonical.bs.total_current_assets"),
    ("TOTAL ASSETS", 116258.0, "canonical.bs.total_assets"),
    ("(a ) Equity share capital", 543.0, "canonical.bs.equity_capital"),
    ("Non..:ontrolling interest", 32.0, "canonical.bs.minority_interest"),
    ("TOTAL EQUITY", 75197.0, "canonical.bs.total_equity"),
    ("(e ) Other non-current liabilities", 73.0, "canonical.bs.other_non_current_liabilities"),
    ("Total non-current liabilities", 9235.0, "canonical.bs.total_non_current_liabilities"),
    ("(c) Other current liabilities", 2315.0, "canonical.bs.other_current_liabilities"),
    ("(d ) Provisions", 1664.0, "canonical.bs.provisions"),
    ("Total current liabilities", 31826.0, "canonical.bs.total_current_liabilities"),
    ("TOTAL LIABILITIES", 41061.0, "canonical.bs.total_liabilities"),
    ("TOTAL EQUITY AND LIABILITIES", 116258.0, "canonical.bs.total_liabilities_and_equity"),
    # One of the two prints each; the face prints both under the same half and
    # the gate refuses both on the real document. The fixture location below
    # carries no page coordinate, so what is pinned here is the registry's
    # decision for the words, not the fate of the row.
    ("Billed", 23585.0, "canonical.bs.trade_receivables"),
    ("Unbilled", 7956.0, "canonical.bs.unbilled_revenue"),
]

# (printed caption, printed FY26 figure). Seventeen figures, sixteen captions:
# "(iv) Others" prints in both the non-current asset block and the current
# liabilities block, and one key cannot hold both.
WITHDRAWN_FIGURES = [
    ("(c) Right-of-use assets", 3592.0),
    ("(f) Intangible assets under development", 82.0),
    ("(iii) Loans", 50.0),
    ("(iv) Others", 3585.0),
    ("(iv) Others", 9228.0),
    ("(iv) Other bank balances", 15160.0),
    ("(v) Loans", 1017.0),
    ("(vi) Others", 1626.0),
    ("(b) Other equity", 74622.0),
    ("Equity attributable to owners of the Company", 75165.0),
    ("(i) Borrowings", 122.0),
    ("(ii) Lease liabilities", 3180.0),
    ("(iii) Others", 1401.0),
    ("(b) Contract liabilities", 5053.0),
    ("(c) Provisions", 2001.0),
    ("(d) Deferred tax liabilities (net)", 1381.0),
    ("(e) Current tax liabilities (net)", 3862.0),
]


def _raw(label: str, value: float, half: str | None = None) -> RawDatapoint:
    # The location carries no " y=" on purpose: the same-page twin gate reads a
    # page coordinate as a second printing, and what this file pins is the
    # registry's decision for the caption rather than the row's fate on the
    # real page.
    return RawDatapoint(
        id="hcl-%s-%.0f" % (label[:8].replace(" ", ""), value),
        company_id="fixture_co",
        metric_raw=label,
        period_label="FY26",
        period_end_date=datetime(2026, 3, 31).date(),
        value=value,
        currency="INR",
        units="crores",
        source="nse_filing",
        source_location="fixture p.4",
        section="BALANCE SHEET",
        bs_half=half,
        status="reported",
        update_date=datetime.now(),
    )


class TestTheHclCaptionsWithHomesReachThem:
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

    def test_the_two_artifact_captions_map_under_the_strings_the_reader_gets(self):
        """"non..:urrent" is what the face's table font extracts as.

        Mapping a corrected spelling would never match, so the extracted string
        is the key the registry keeps -- with the artifact named in its comment.
        """
        artifacts = {
            label for label, _v, _k in MAPPED_FIGURES if "..:" in label
        }
        assert artifacts == {
            "(i) Other non..:urrent assets",
            "Total non..:urrent assets",
            "Non..:ontrolling interest",
        }


class TestTheHclCaptionsWithoutAHomeAreRecorded:
    def test_every_one_of_them_is_a_withdrawn_label(self):
        missing = [
            label
            for label, _value in WITHDRAWN_FIGURES
            if label not in WITHDRAWN_LABELS
        ]
        assert not missing, "%r is not recorded as withdrawn" % missing
        assert len({label for label, _v in WITHDRAWN_FIGURES}) == 16, (
            "the withdrawn family changed size (%d captions); add or remove the "
            "caption itself, not silently the count"
            % len({label for label, _v in WITHDRAWN_FIGURES})
        )
        assert len(WITHDRAWN_FIGURES) == 17, (
            "(iv) Others prints two figures under one withdrawn caption; the figure "
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


class TestTheCaptionTheHalfGuardDeclines:
    """Registered, not withdrawn, and still reaching no key -- the TCS shape."""

    def test_the_noncurrent_unbilled_receivable_is_registered(self):
        label = "(ii) Trade receivables -unbilled"
        assert label in RAW_METRIC_MAP
        assert label not in WITHDRAWN_LABELS

    def test_its_only_print_declines_the_current_asset_key(self, tmp_path):
        canonical, _mappings, unmapped = mapper.map_raw_datapoints(
            [_raw("(ii) Trade receivables -unbilled", 601.0, half="noncurrent")],
            db_path=tmp_path / "queue.db",
        )
        assert canonical == [], (
            "a non-current figure was published as unbilled revenue, which is a "
            "current-asset line: %s" % [c.canonical_key for c in canonical]
        )
        assert unmapped == [], (
            "the decline is a recorded decision, not a coverage gap: %s" % unmapped
        )
