"""A reviewed confirmation for one company's caption outranks a static withdrawal.

Bare "Investments" is withdrawn in the registry because no label-level rule can
pick current against non-current. But a human_confirmed=1 row for the exact
(company, caption) says somebody resolved it for that company by reading its
sheet, and refusing that decision over the static rule deleted published
balance sheet lines the moment a full re-normalization reprocessed their raw
rows: lt_lt and tatasteel_tatasteel lost current_investments for all three
periods, swinging the DCF bridge by the full 51,000 and 14,000. Only reviewed
decisions count: medium auto-accepts and engine-learned rows stay refused, and
a label the registry maps never reaches the confirmation lookup.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from backend.data.store import RawDatapoint
from backend.normalization.financials import mapper
from backend.normalization.taxonomy.registry import WITHDRAWN_LABELS


def _db(path, confirmations=()):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE taxonomy_mappings (id TEXT PRIMARY KEY, company_id TEXT, "
        "canonical_key TEXT, metric_raw TEXT, statement TEXT, source TEXT, "
        "human_confirmed INTEGER, update_date TEXT)"
    )
    for i, (company, label, key, human) in enumerate(confirmations):
        conn.execute(
            "INSERT INTO taxonomy_mappings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"row-{i}", company, key, label, "bs", "screener", human,
             datetime.now().isoformat()),
        )
    conn.commit()
    conn.close()
    return path


def _raw(label: str, value: float) -> RawDatapoint:
    return RawDatapoint(
        id="figure-%s" % label[:6].replace(" ", ""),
        company_id="fixture_co",
        metric_raw=label,
        period_label="FY26",
        period_end_date=datetime(2026, 3, 31).date(),
        value=value,
        currency="INR",
        units="crores",
        source="screener",
        source_location="fixture sheet",
        section="BALANCE SHEET",
        status="estimated",
        update_date=datetime.now(),
    )


class TestAReviewedConfirmationOutranksAWithdrawal:
    def test_confirmed_caption_maps_to_its_confirmed_key(self, tmp_path):
        assert "Investments" in WITHDRAWN_LABELS
        db = _db(tmp_path / "store.db", [
            ("fixture_co", "Investments", "canonical.bs.current_investments", 1),
        ])
        canonical, _mappings, unmapped = mapper.map_raw_datapoints(
            [_raw("Investments", 51000.0)], db_path=db
        )
        assert [c.canonical_key for c in canonical] == [
            "canonical.bs.current_investments"
        ], "the reviewed decision did not survive the static withdrawal"
        assert canonical[0].value == 51000.0
        assert "Investments" not in unmapped

    def test_medium_auto_accept_does_not_outrank(self, tmp_path):
        db = _db(tmp_path / "store.db", [
            ("fixture_co", "Investments", "canonical.bs.current_investments", 0),
        ])
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            [_raw("Investments", 51000.0)], db_path=db
        )
        assert canonical == [], (
            "an unreviewed auto-accept resurrected a withdrawn caption"
        )

    def test_no_confirmation_still_refused(self, tmp_path):
        db = _db(tmp_path / "store.db", [])
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            [_raw("Investments", 51000.0)], db_path=db
        )
        assert canonical == [], "a withdrawn caption mapped with nothing behind it"

    def test_confirmation_for_another_company_does_not_apply(self, tmp_path):
        db = _db(tmp_path / "store.db", [
            ("other_co", "Investments", "canonical.bs.current_investments", 1),
        ])
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(
            [_raw("Investments", 51000.0)], db_path=db
        )
        assert canonical == [], (
            "one company's review leaked onto another company's caption"
        )
