"""An unmapped caption is a coverage gap, and the build must not die of it.

`normalization.pipeline.run` raised `ValueError` on any unmapped label. It was a forcing
function for taxonomy work, and it became a shipping defect the moment the NSE fetcher's
located pages reached that stage: TCS's audited balance sheet contributes 174 rows carrying
9 captions the taxonomy has no entry for, and the entire ingest failed. TCS and HCLTech both
ingested cleanly from the market feed a moment earlier, so closing the filing last mile would
have shipped as a regression against two working companies.

What makes continuing safe is not that the raise was redundant. It is that a DIFFERENT check
catches the consequence, and these tests are here to show that check firing rather than to
assert that it would.

Measured on a copy of the live store after the change, per company, per period:

    TCS      sum of kept current assets   filed subtotal      gap
             FY25     99,834              103,163         -3,329
             FY26    104,417              110,270         -5,853

    HCLTech  sum of kept current assets   filed subtotal      gap
             FY26     23,855                6,885        +16,970

Neither statement foots, so `current_assets_reconcile` fails with a signed per-period gap and
the model stays `opinion_only`. That is the guard doing its job, and it is downstream of the
point where the raise used to be.
"""
from __future__ import annotations

import pytest

from backend.normalization.pipeline import run as normalize_run


class _Stub:
    """Just enough of a raw datapoint for the mapper to reject on its caption."""

    def __init__(self, metric_raw, company_id="probe_us", section="BALANCE SHEET"):
        self.metric_raw = metric_raw
        self.company_id = company_id
        self.section = section
        self.bs_half = None
        self.value = 1.0
        self.period_label = "FY26"
        self.currency = "INR"
        self.units = "crores"
        self.source = "nse_filing"
        self.source_location = "probe p.1"
        self.status = "reported"
        self.id = "probe"
        self.superseded_by_id = None


def test_normalization_continues_past_an_unmapped_caption(tmp_path, monkeypatch):
    """The build completes and REPORTS the gap, rather than raising and reporting nothing."""
    db = tmp_path / "probe.sqlite"
    db.touch()

    monkeypatch.setattr(
        "backend.normalization.pipeline.query_datapoints",
        lambda *a, **k: [_Stub("A caption the taxonomy has never heard of")],
    )
    monkeypatch.setattr(
        "backend.normalization.pipeline.map_raw_datapoints",
        lambda dps: ([], [], ["A caption the taxonomy has never heard of"]),
    )
    monkeypatch.setattr(
        "backend.normalization.pipeline.derive_canonical_metrics", lambda dps: []
    )
    monkeypatch.setattr(
        "backend.normalization.pipeline.validate_currencies_and_units",
        lambda *a, **k: {"is_valid": True, "inconsistent_datapoints": []},
    )
    monkeypatch.setattr(
        "backend.normalization.pipeline.align_fiscal_periods",
        lambda *a, **k: {"is_aligned": True, "misaligned_datapoints": []},
    )
    monkeypatch.setattr("backend.normalization.pipeline.connect", lambda *a, **k: _Conn())
    monkeypatch.setattr("backend.normalization.pipeline.save_canonical_datapoints",
                        lambda *a, **k: None)
    monkeypatch.setattr("backend.normalization.pipeline.save_taxonomy_mappings",
                        lambda *a, **k: None)
    monkeypatch.setattr("backend.models.spec.metadata.get_metadata_for_company",
                        lambda cid: type("M", (), {"currency": "INR", "units": "crores"})())

    summary = normalize_run("probe_us", db_path=db)

    assert summary["unmapped_labels_count"] == 1
    assert summary["unmapped_labels"] == ["A caption the taxonomy has never heard of"], (
        "the gap was counted but not named, so the record says something is missing without "
        "saying what. Whoever fixes it has to re-derive the list."
    )


class _Conn:
    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_the_other_validations_still_stop_the_build(tmp_path, monkeypatch):
    """Removing ONE fatal is not removing the guard.

    Currency and period validation remain fatal, because those are arithmetic the engine
    cannot proceed past: a model built on mixed units is wrong rather than incomplete.
    """
    db = tmp_path / "probe2.sqlite"
    db.touch()
    monkeypatch.setattr("backend.normalization.pipeline.query_datapoints", lambda *a, **k: [])
    monkeypatch.setattr(
        "backend.normalization.pipeline.map_raw_datapoints", lambda dps: ([], [], [])
    )
    monkeypatch.setattr(
        "backend.normalization.pipeline.derive_canonical_metrics", lambda dps: []
    )
    monkeypatch.setattr(
        "backend.normalization.pipeline.validate_currencies_and_units",
        lambda *a, **k: {"is_valid": False, "inconsistent_datapoints": ["x"]},
    )
    monkeypatch.setattr(
        "backend.models.spec.metadata.get_metadata_for_company",
        lambda cid: type("M", (), {"currency": "INR", "units": "crores"})(),
    )

    with pytest.raises(ValueError, match="Currency/Units validation failed"):
        normalize_run("probe_us", db_path=db)
