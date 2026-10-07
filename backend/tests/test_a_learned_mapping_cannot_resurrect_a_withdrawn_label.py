"""A learned mapping cannot put a withdrawn label back into service.

A withdrawal is enforced by two things: the label's absence from
RAW_METRIC_MAP, and the mapper's gate that consults WITHDRAWN_LABELS when the
registry returns None. The learned-mapping path attacked the first: one
resolved queue entry put the label back into the registry, so the gate at the
second never fired again, in that process and in every later one through the
hydrate pass that replays persisted resolutions on every suggestion call. The
withdrawn figure would publish once more (the case the withdrawal documents:
an aggregate overwriting the component it was withdrawn to protect).

Both directions now refuse labels in WITHDRAWN_LABELS: recording a resolution,
and loading persisted ones. Undoing a withdrawal is a registry edit, not a
queue resolution, so the queue entry stays pending until someone removes the
label from the withdrawn set.
"""
from __future__ import annotations

import sqlite3

from backend.data.universe.store import _UNIVERSE_SCHEMA
from backend.normalization.taxonomy import mapping_engine
from backend.normalization.taxonomy.mapping_engine import (
    _load_learned_mappings,
    _normalize_string,
    _record_learned,
    feedback_mapping_resolution,
    route_to_review_queue,
)
from backend.normalization.taxonomy.registry import (
    RAW_METRIC_MAP,
    WITHDRAWN_LABELS,
)
from backend.data.universe.models import MappingConfidenceResult

# The aggregate whose resurrection this guards against: the screener's
# "Investments" total was withdrawn precisely because it overwrote the filing's
# component figure, and it is a label the confidence engine still proposes.
WITHDRAWN = "Investments"
CANONICAL_KEY = "canonical.bs.non_current_investments"

CONTROL = "Learned Control Metric"


def _pending_row(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_UNIVERSE_SCHEMA)
    return conn


def test_a_resolution_of_a_withdrawn_label_records_nothing(tmp_path):
    db = tmp_path / "learned.db"
    conn = _pending_row(db)
    try:
        route_to_review_queue(
            "fixture_co",
            WITHDRAWN,
            MappingConfidenceResult(
                metric_raw=WITHDRAWN,
                canonical_key=None,
                statement=None,
                confidence_score=0.2,
                level="low",
                reason="Unrecognized label, requires human review",
            ),
            db_path=db,
        )
        conn.commit()
    finally:
        conn.close()

    feedback_mapping_resolution(
        WITHDRAWN, CANONICAL_KEY, "bs", db_path=db
    )

    assert WITHDRAWN not in RAW_METRIC_MAP, (
        "a resolution put %r back into RAW_METRIC_MAP, so the mapper's "
        "withdrawal gate never fires again and the withdrawn figure publishes"
        % WITHDRAWN
    )
    assert _normalize_string(WITHDRAWN) not in mapping_engine._NORMALIZED_MAP, (
        "the normalized lookup still carries %r" % WITHDRAWN
    )

    conn = sqlite3.connect(str(db))
    try:
        learned = conn.execute(
            "SELECT canonical_key FROM taxonomy_learned_mappings WHERE metric_raw = ?",
            (WITHDRAWN,),
        ).fetchall()
        status = conn.execute(
            "SELECT status FROM taxonomy_review_queue WHERE metric_raw = ?",
            (WITHDRAWN,),
        ).fetchone()
    finally:
        conn.close()
    assert learned == [], "a refused resolution was persisted anyway: %r" % (learned,)
    assert status == ("pending",), (
        "the queue entry was resolved although nothing was learned; a human must "
        "remove the label from the withdrawn set first (got %r)" % (status,)
    )


def test_the_runtime_record_refuses_a_withdrawn_label():
    _record_learned(WITHDRAWN, CANONICAL_KEY, "bs")
    assert WITHDRAWN not in RAW_METRIC_MAP, (
        "_record_learned applied a mapping for the withdrawn label %r" % WITHDRAWN
    )


def test_the_hydrate_path_refuses_a_persisted_withdrawn_mapping(tmp_path):
    """A poisoned row in the learned table must not survive the reload."""
    db = tmp_path / "poisoned.db"
    conn = _pending_row(db)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO taxonomy_learned_mappings "
            "(metric_raw, canonical_key, statement, update_date) VALUES (?, ?, ?, ?)",
            (WITHDRAWN, CANONICAL_KEY, "bs", "2026-10-07T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    was_loaded = mapping_engine._LEARNED_MAPPINGS_LOADED
    mapping_engine._LEARNED_MAPPINGS_LOADED = False
    try:
        _load_learned_mappings(db)
        assert WITHDRAWN not in RAW_METRIC_MAP, (
            "_load_learned_mappings hydrated the withdrawn label %r from disk, "
            "so every later process inherits the resurrection" % WITHDRAWN
        )
    finally:
        mapping_engine._LEARNED_MAPPINGS_LOADED = was_loaded


def test_a_normal_label_still_records_and_loads(tmp_path):
    """The guard is the withdrawn set, not learned mappings in general."""
    db = tmp_path / "learned.db"
    feedback_mapping_resolution(CONTROL, "canonical.bs.other_reserves", "bs", db_path=db)

    try:
        assert RAW_METRIC_MAP.get(CONTROL) == (
            "canonical.bs.other_reserves",
            "bs",
        ), "a legitimate resolution was refused"
        conn = sqlite3.connect(str(db))
        try:
            learned = conn.execute(
                "SELECT canonical_key FROM taxonomy_learned_mappings WHERE metric_raw = ?",
                (CONTROL,),
            ).fetchall()
        finally:
            conn.close()
        assert learned == [("canonical.bs.other_reserves",)], (
            "the resolution was not persisted: %r" % (learned,)
        )
    finally:
        RAW_METRIC_MAP.pop(CONTROL, None)
        mapping_engine._NORMALIZED_MAP.pop(_normalize_string(CONTROL), None)
