"""Regression tests for the override duplicate-append race (live audit finding).

Rapid sequential recompute POSTs raced the read-modify-write cycle: each one
took the `not found -> append` branch, producing duplicate user_override
objects with previous_model_value=None that reverted() could never restore.
"""
from backend.api.routes import _normalize_assumptions
from backend.models.spec.assumptions import AssumptionObject


def _mk(key="revenue_growth", value=9.0, typ="user_override", prev=None):
    return AssumptionObject(
        driver_key=key, value=value, period="all", scenario="base",
        type=typ, source="t", previous_model_value=prev,
    )


def test_normalize_dedups_race_duplicates_and_rescues_baseline():
    dupes = [_mk(prev=None), _mk(prev=None), _mk(prev=5.3), _mk(prev=None)]
    out = _normalize_assumptions(dupes)
    assert len(out) == 1
    assert out[0].type == "user_override"
    assert out[0].previous_model_value == 5.3
    # Revert now actually restores the baseline.
    assert out[0].reverted().value == 5.3
    assert out[0].reverted().type == "model_generated"


def test_normalize_rebases_when_baseline_unrecoverable():
    out = _normalize_assumptions([_mk(prev=None), _mk(prev=None)])
    assert len(out) == 1
    assert out[0].type == "model_generated"


def test_normalize_keeps_distinct_keys_and_scenarios():
    mixed = [_mk("a", 1.0, "model_generated"), _mk("a", 2.0, "user_override", 1.0)]
    out = _normalize_assumptions(mixed)
    assert len(out) == 1
    assert out[0].value == 2.0
    assert out[0].reverted().value == 1.0
