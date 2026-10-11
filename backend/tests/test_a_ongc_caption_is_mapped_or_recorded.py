"""A printed ONGC caption is either mapped to its key or recorded as withdrawn.

The audited consolidated face (printed p.35 and its p.36 liability continuation in
`ongc-annual-2026-05.pdf`) prints 57 distinct captions. All of them resolve: 24 canonical
keys publish, 12 families are withdrawn with the reason on file, and only the
"(ii) Lease Liabilities" pair publishes neither printing, because it prints once per half
under one caption and there are no half-specific keys to split it to.

Both columns read cleanly here (unlike Reliance's FY26), so every figure below is a
figure the filer prints in both periods, and the metadata records no readable-periods
restriction. The banner is a complete declaration, "(Rs. in Crore)" with a readable rupee
glyph, so the rows carry INR crores read from the page rather than asserted.

Three mappings the engine would otherwise have made, each caught in the dry run and each
decided here against the printed figure: "(c) Deferred Tax liabilities (net)" suggested
the deferred-tax ASSET key, which published a 38,765 liability as an asset and doomed the
true 7,081 asset beside it; "(d) Current Tax Liabilities (net)" did the same to a
current tax asset with its 642; and "(j) Non-current tax assets (net)" was suggested the
deferred-tax key too, which put it in the same refusal bucket as the real deferred-tax
asset. All three are withdrawn or redirected here, and the three true asset lines
survive.

The face also prints no subtotal for its property, plant and equipment or capital
work-in-progress blocks -- components only -- so every one of those captions is
withdrawn rather than publishing a component as the whole.
"""
from __future__ import annotations

from datetime import datetime

from backend.data.store import RawDatapoint
from backend.normalization.financials import mapper
from backend.normalization.taxonomy.registry import (
    RAW_METRIC_MAP,
    WITHDRAWN_LABELS,
)

# (printed caption, printed FY26 figure, canonical key, half as the filing prints it)
#
# The half is carried because it decides one of these keys rather than decorating it:
# "(i) Investments" is registered under the non-current key and reaches
# `current_investments` only through `_key_for_half`, which routes on the half the
# printed block gives it. A fixture that drops the half would test the registry's
# fallback rather than the behaviour the filing produces.
MAPPED_FIGURES = [
    ("Total non-current assets", 649965.8, "canonical.bs.total_non_current_assets", "noncurrent"),
    ("Total current assets", 141731.58, "canonical.bs.total_current_assets", "current"),
    ("Total assets", 791905.18, "canonical.bs.total_assets", None),
    ("(a) Inventories", 64918.27, "canonical.bs.inventory", "current"),
    ("(i) Investments", 3106.83, "canonical.bs.current_investments", "current"),
    ("(iii) Cash and cash equivalents", 1554.39, "canonical.bs.cash_and_bank", "current"),
    ("(d) Other current assets", 8840.51, "canonical.bs.prepayments_other_current_assets", "current"),
    ("(i) Deferred tax assets (net)", 7503.98, "canonical.bs.deferred_tax_assets", "noncurrent"),
    ("(j) Non-current tax assets (net)", 15562.77, "canonical.bs.income_tax_assets", "noncurrent"),
    ("(c) Current Tax Assets (net)", 315.27, "canonical.bs.current_income_tax_assets", "current"),
    ("(g) Investments in Joint Ventures and Associates", 63753.21,
     "canonical.bs.non_current_investments", "noncurrent"),
    ("(k) Other non-current assets", 4266.75, "canonical.bs.other_non_current_assets", "noncurrent"),
    ("(d) Goodwill (including Goodwill on Consolidation)", 13821.82, "canonical.bs.goodwill", "noncurrent"),
    ("(e) Other intangible assets", 1538.49, "canonical.bs.intangible_assets", "noncurrent"),
    ("(a) Equity share capital", 6290.14, "canonical.bs.equity_capital", None),
    ("Non-controlling interests", 37925.48, "canonical.bs.minority_interest", None),
    ("Total Equity", 409693.28, "canonical.bs.total_equity", None),
    ("Total non-current liabilities", 213323.32, "canonical.bs.total_non_current_liabilities", None),
    ("(d) Other non-current liabilities", 1495.87, "canonical.bs.other_non_current_liabilities", None),
    ("(b) Provisions", 54453.47, "canonical.bs.provisions", None),
    ("Total current liabilities", 168795.3, "canonical.bs.total_current_liabilities", None),
    ("(b) Other current liabilities", 12900.75, "canonical.bs.other_current_liabilities", None),
    ("Total liabilities", 382211.9, "canonical.bs.total_liabilities", None),
    ("Total equity and liabilities", 791905.18, "canonical.bs.total_liabilities_and_equity", None),
]

# (printed caption, printed FY26 figure). Eleven families, none of which has a key that
# holds it: the PPE and CWIP components of two blocks the filer prints no subtotal for,
# the two tax liabilities, and the site-restoration, held-for-sale, right-of-use and
# investment-property lines.
WITHDRAWN_FIGURES = [
    ("(a) Tangible", 153004.74),
    ("(b) Intangible", 1183.67),
    ("(ii) Other property, plant and equipment", 146272.11),
    ("(i) Exploratory wells in progress", 20070.42),
    ("a) Development wells in progress", 6460.31),
    ("b) Oil and gas facilities in progress", 49039.67),
    ("c) Acquisition Cost", 23823.0),
    ("(ii) Others", 12154.64),
    ("(iii) Intangible Oil and Gas Assets in progress", 4654.21),
    ("(vii) Others", 9867.77),
    ("(iii) Right of Use Assets", 30244.65),
    ("(c) Investment Property", 7.7),
    ("(c) Deferred Tax liabilities (net)", 40654.59),
    ("(d) Current Tax Liabilities (net)", 639.24),
    ("(iv) Deposit under site restoration fund", 33168.14),
    ("(vi) Deposit under site restoration fund", 35.78),
    ("Assets classified as held for sale", 207.8),
    ("Liabilities directly associated with assets classified as held for sale", 93.28),
    ("(ii) Trade receivables", 22014.47),
    ("- to micro and small enterprises", 1615.8),
    ("- to other than micro and small enterprises", 45317.28),
    ("(i) Other Investments", 34224.36),
]


def _raw(label: str, value: float, half: str | None = None,
         location: str = "fixture p.35") -> RawDatapoint:
    # The default location carries no " y=" on purpose: the same-page twin gate reads a
    # page coordinate as a second printing, and what the mapped and withdrawn classes
    # pin is the registry's decision for the caption rather than the row's fate on the
    # real page. The gate class below passes real coordinates.
    return RawDatapoint(
        id="ongc-%s-%.0f" % (label[:8].replace(" ", "").replace("(", "").replace(")", ""), value),
        company_id="fixture_co",
        metric_raw=label,
        period_label="FY26",
        period_end_date=datetime(2026, 3, 31).date(),
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


class TestTheOngcCaptionsWithHomesReachThem:
    def test_each_reaches_its_key_with_the_printed_figure(self, tmp_path):
        for label, value, key, half in MAPPED_FIGURES:
            canonical, _mappings, unmapped = mapper.map_raw_datapoints(
                [_raw(label, value, half=half)], db_path=tmp_path / "queue.db"
            )
            keys = [c.canonical_key for c in canonical]
            assert keys == [key], (
                "%r reached %s; it belongs on %s, and the figure the filing "
                "prints under these exact words is %.2f" % (label, keys, key, value)
            )
            assert canonical[0].value == value
            assert label not in unmapped
        assert len(MAPPED_FIGURES) == 24, (
            "the mapped family changed size (%d); add or remove the caption itself, "
            "not silently the count" % len(MAPPED_FIGURES)
        )

    def test_each_is_registered_and_not_withdrawn(self):
        for label, _value, _key, _half in MAPPED_FIGURES:
            assert label in RAW_METRIC_MAP, "%r has no registry entry" % label
            assert label not in WITHDRAWN_LABELS


class TestTheOngcCaptionsWithoutAHomeAreRecorded:
    def test_every_one_of_them_is_a_withdrawn_label(self):
        missing = [
            label
            for label, _value in WITHDRAWN_FIGURES
            if label not in WITHDRAWN_LABELS
        ]
        assert not missing, "%r is not recorded as withdrawn" % missing
        assert len(WITHDRAWN_FIGURES) == 22, (
            "the withdrawn family changed size (%d); add or remove the caption "
            "itself, not silently the count" % len(WITHDRAWN_FIGURES)
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


class TestTheTaxLinesAreNotInverted:
    """The three engine suggestions that would have published a liability as an asset.

    Each is refused in the classes above; these pin the consequence, because a
    withdrawal that stopped working would put a 40,654 liability back on
    `deferred_tax_assets` without any other signal moving.
    """

    def test_the_true_deferred_tax_asset_survives_its_liability(self, tmp_path):
        canonical, _m, _u = mapper.map_raw_datapoints(
            [_raw("(i) Deferred tax assets (net)", 7503.98, half="noncurrent")],
            db_path=tmp_path / "queue.db",
        )
        assert [(c.canonical_key, c.value) for c in canonical] == [
            ("canonical.bs.deferred_tax_assets", 7503.98)
        ]

    def test_the_true_current_tax_asset_survives_its_liability(self, tmp_path):
        canonical, _m, _u = mapper.map_raw_datapoints(
            [_raw("(c) Current Tax Assets (net)", 315.27, half="current")],
            db_path=tmp_path / "queue.db",
        )
        assert [(c.canonical_key, c.value) for c in canonical] == [
            ("canonical.bs.current_income_tax_assets", 315.27)
        ]

    def test_income_tax_does_not_land_on_the_deferred_tax_key(self, tmp_path):
        canonical, _m, _u = mapper.map_raw_datapoints(
            [_raw("(j) Non-current tax assets (net)", 15562.77, half="noncurrent")],
            db_path=tmp_path / "queue.db",
        )
        assert [(c.canonical_key, c.value) for c in canonical] == [
            ("canonical.bs.income_tax_assets", 15562.77)
        ], (
            "a non-current income-tax asset published as a deferred-tax asset would "
            "overstate deferred tax by the whole figure and refuse the real one"
        )


class TestTheLeaseTwinPublishesNeither:
    def test_neither_printing_of_one_caption_reaches_a_key(self, tmp_path):
        # No half on either row, which is what the filing produces: ONGC's liability
        # block headers read "Non-current liabilities" and "Current Liabilities", and
        # the half reader matches ASSET headers only -- deliberately, because a
        # liability half would put these two into different buckets and let one of
        # them publish silently on a key that cannot hold both. They share one bucket
        # here, so the gate refuses both.
        dps = [
            _raw("(ii) Lease Liabilities", 9680.08,
                 location="ongc-annual-2026-05.pdf p.36 y=189.1 (ii) Lease Liabilities"),
            _raw("(ii) Lease Liabilities", 24384.46,
                 location="ongc-annual-2026-05.pdf p.36 y=243.9 (ii) Lease Liabilities"),
        ]
        canonical, _m, unmapped = mapper.map_raw_datapoints(
            dps, db_path=tmp_path / "queue.db"
        )
        assert [c.canonical_key for c in canonical] == [], (
            "the non-current 9,680 and the current 24,384 share one caption and one key; "
            "publishing either states the other half's figure as this line"
        )
        assert unmapped == []
