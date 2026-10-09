"""The exchange line is a memo outside the sections, and the check absorbs it.

Infosys prints "Effect of exchange rate changes on cash and cash equivalents"
on the continuation page under the three cash-flow sections ((84) at FY24, 82
at FY25, 1,600 at FY26). The three sections already sum to the printed bottom
line without it (26,066 - 5,865 - 17,504 = 2,697 at FY24, and likewise at FY25
and FY26), so the row publishes OUTSIDE the sections as a memo: the sections
still add to the bottom line exactly, and the reconciliation check reads the
row as a fourth term that closes the balance-sheet tie.

What this pins, with a synthetic three-period fixture whose roll closes only
with the row (beginning 10,000, sections summing to 0, movement 300, fx 300):

- the caption maps to `canonical.cf.fx_effect`, and is neither withdrawn nor
  an unmapped gap;
- the assembled statement publishes the filing's figures on the fx line while
  net change stays the three-section sum;
- the check passes with fx absorbed, and still skips without it -- with
  byte-identical text to before the key existed, so every company without fx
  rows keeps the verdict it had.
"""
from __future__ import annotations

import datetime as dt
from datetime import datetime

from backend.data.store import RawDatapoint
from backend.models.spec.historicals import HistoricalLineItem, Historicals
from backend.models.spec.metadata import ModelMetadata
from backend.models.spec.model_specification import ModelSpecification
from backend.models.statements.cash_flow import assemble_cash_flow, derive_net_change_in_cash
from backend.normalization.financials import mapper
from backend.normalization.taxonomy.models import CanonicalDatapoint
from backend.normalization.taxonomy.registry import RAW_METRIC_MAP, WITHDRAWN_LABELS
from backend.validation.accounting_checks import check_cash_flow_reconciles

CAPTION = "Effect of exchange rate changes on cash and cash equivalents"
KEY = "canonical.cf.fx_effect"
_END = dt.date(2026, 3, 31)


def _raw(label: str, value: float) -> RawDatapoint:
    return RawDatapoint(
        id="figure-fx",
        company_id="fixture_co",
        metric_raw=label,
        period_label="FY26",
        period_end_date=_END,
        value=value,
        currency="INR",
        units="crores",
        source="nse_filing",
        source_location="fixture p.105",
        section="CASH FLOW",
        status="reported",
        update_date=datetime.now(),
    )


def _canon(key: str, period: str, value: float) -> CanonicalDatapoint:
    return CanonicalDatapoint(
        company_id="fixture_co",
        canonical_key=key,
        metric_raw=key,
        period_label=period,
        period_end_date=_END,
        value=value,
        currency="INR",
        units="crores",
        status="reported",
        source_datapoint_ids=["fixture"],
    )


def _line(key: str, period: str, value: float) -> HistoricalLineItem:
    return HistoricalLineItem(
        canonical_key=key,
        period_label=period,
        period_end_date=_END,
        value=value,
        currency="INR",
        units="crores",
        status="reported",
        source_datapoint_ids=[f"{key}-{period}"],
    )


def _spec(rows: dict[str, list[tuple[str, float]]]) -> ModelSpecification:
    items = []
    for period, pairs in rows.items():
        items.extend(_line(k, period, v) for k, v in pairs)
    spec = ModelSpecification(
        metadata=ModelMetadata(
            company_id="fx_co",
            ticker="FX",
            name="FX Testco",
            market="india",
            currency="INR",
            units="crores",
            fiscal_year_end="March 31",
        ),
        historicals=Historicals(periods=list(rows.keys()), line_items=items),
    )
    # The default factory builds an empty five-year forecast the check would
    # fail on missing cash; these tests exercise the historical identity only.
    spec.forecast = None
    return spec


def _roll(fx: dict[str, float] | None) -> dict[str, list[tuple[str, float]]]:
    """Beginning 10,000, sections summing to 0, movement 300: open without fx."""
    rows = {
        "FY24": [
            ("canonical.bs.cash_and_bank", 10000.0),
        ],
        "FY25": [
            ("canonical.bs.cash_and_bank", 10100.0),
            ("canonical.cf.operating_activities", 500.0),
            ("canonical.cf.investing_activities", -300.0),
            ("canonical.cf.financing_activities", -150.0),
        ],
        "FY26": [
            ("canonical.bs.cash_and_bank", 10300.0),
            ("canonical.cf.operating_activities", 600.0),
            ("canonical.cf.investing_activities", -400.0),
            ("canonical.cf.financing_activities", -250.0),
        ],
    }
    if fx:
        for period, value in fx.items():
            rows[period].append((KEY, value))
    return rows


class TestTheCaptionHasAHome:
    def test_it_is_registered_and_not_withdrawn(self):
        assert RAW_METRIC_MAP.get(CAPTION) == (KEY, "cf")
        assert CAPTION not in WITHDRAWN_LABELS, (
            "the fx caption cannot be both mapped and withdrawn; the registry "
            "lookup would succeed and the withdrawal would never be reached"
        )

    def test_it_reaches_its_key_and_is_not_a_gap(self, tmp_path):
        canonical, _mappings, unmapped = mapper.map_raw_datapoints(
            [_raw(CAPTION, 1600.0)], db_path=tmp_path / "queue.db"
        )
        assert [c.canonical_key for c in canonical] == [KEY]
        assert canonical[0].value == 1600.0
        assert CAPTION not in unmapped


class TestTheRowIsAMemoOutsideTheSections:
    def test_it_publishes_the_filing_figures_all_three_years(self):
        dps = [
            _canon("canonical.cf.operating_activities", p, v)
            for p, v in [("FY24", 26066.0), ("FY25", 36786.0), ("FY26", 35824.0)]
        ]
        dps += [
            _canon("canonical.cf.investing_activities", p, v)
            for p, v in [("FY24", -5865.0), ("FY25", 108.0), ("FY26", -5865.0)]
        ]
        dps += [
            _canon("canonical.cf.financing_activities", p, v)
            for p, v in [("FY24", -17504.0), ("FY25", -27307.0), ("FY26", -33813.0)]
        ]
        dps += [
            _canon(KEY, p, v)
            for p, v in [("FY24", -84.0), ("FY25", 82.0), ("FY26", 1600.0)]
        ]
        cf = assemble_cash_flow(dps)
        assert cf.get_value(KEY, "FY24") == -84.0
        assert cf.get_value(KEY, "FY25") == 82.0
        assert cf.get_value(KEY, "FY26") == 1600.0

    def test_net_change_is_still_the_three_section_sum(self):
        dps = [
            _canon("canonical.cf.operating_activities", p, v)
            for p, v in [("FY24", 26066.0), ("FY25", 36786.0), ("FY26", 35824.0)]
        ]
        dps += [
            _canon("canonical.cf.investing_activities", p, v)
            for p, v in [("FY24", -5865.0), ("FY25", 108.0), ("FY26", -5865.0)]
        ]
        dps += [
            _canon("canonical.cf.financing_activities", p, v)
            for p, v in [("FY24", -17504.0), ("FY25", -27307.0), ("FY26", -33813.0)]
        ]
        dps += [_canon(KEY, "FY26", 1600.0)]
        cf = assemble_cash_flow(dps)
        derive_net_change_in_cash(cf)
        # The sections sum to the printed bottom line exactly; the memo sits
        # outside them and must not move the total by a rupee.
        assert cf.get_value("canonical.cf.net_change_in_cash", "FY24") == 2697.0
        assert cf.get_value("canonical.cf.net_change_in_cash", "FY26") == -3854.0


class TestTheCheckAbsorbsIt:
    def test_it_passes_where_fx_explains_the_gap(self):
        result = check_cash_flow_reconciles(_spec(_roll({"FY25": 100.0, "FY26": 200.0})))
        assert result.passed, result.detail
        assert result.detail == "", result.detail

    def test_it_still_skips_byte_identical_without_fx_rows(self):
        result = check_cash_flow_reconciles(_spec(_roll(None)))
        assert result.passed
        assert result.detail == (
            "SKIPPED: Cash flow statement does not reconcile with balance sheet "
            "cash for historical periods FY24..FY26: ending cash 10300.0 vs "
            "implied 10000.0 + cfo 1100.0 + cfi -700.0 + cff -400.0 = 10000.0 "
            "(diff 300.00, tol 103.00)"
        ), result.detail
        assert KEY not in result.implicated_canonical_keys

    def test_a_remaining_gap_names_the_fx_term(self):
        result = check_cash_flow_reconciles(_spec(_roll({"FY25": 100.0, "FY26": 50.0})))
        assert result.passed
        assert "+ fx 150.0" in result.detail, result.detail
        assert KEY in result.implicated_canonical_keys
