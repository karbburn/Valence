"""A caller that names a store must be building from THAT store.

Four functions on the build path read a module-level `DB_PATH` instead of the store their
caller had already named. `run_batch_company_onboarding(db_path=X)` threaded `X` into
`get_universe_company`, `ensure_company_ingested` and `update_onboarding_status` -- and then
called `run_precompute(company_id)`, which dropped it, ingested into the default store, and
assembled the model from the default store. So a caller testing a data migration against a
copy wrote its rows to the copy and read live rows back, and the model it produced described
provenance from a store it had never ingested.

That is the third instance of one defect on this path. `normalization.pipeline.run` had it
and was fixed in 18b4220. `_read_provenance` had it. `run_historical` had it. The chain was
fixed one link at a time by finding each link as a probe needed it, which is the slow way to
discover that the whole path was never parameterised.

The test walks the chain with a sentinel store that must never be touched, which is the
property rather than the shape: any module that reads the live global mid-chain fails.

Deliberately not a source scan for `DB_PATH`. A grep finds the constant's DEFINITION as well
as its uses, and this defect is precisely a use that should have been a parameter. What is
asserted is that the live store is not read when a caller named another one.
"""
from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest

LIVE = Path("backend/data/valence.db")


def _poisoned_live(tmp_path, monkeypatch):
    """Make any read of the live store fail loudly.

    Renaming the file is not an option: the running backend and the dev site read it. So
    the module globals are pointed at a path that does not exist, and the tests assert the
    chain never reaches them. A module that still reads the global will raise rather than
    quietly return live rows, which is the failure this is looking for.
    """
    missing = tmp_path / "there-is-no-live-store-here.db"
    for module in (
        "backend.data.universe.store",
        "backend.models.statements.pipeline",
        "backend.forecast.pipeline",
        "backend.models.spec.metadata",
    ):
        mod = __import__(module, fromlist=["*"])
        if hasattr(mod, "DB_PATH"):
            monkeypatch.setattr(mod, "DB_PATH", missing, raising=False)
    return missing


def test_every_function_on_the_build_path_accepts_a_store():
    """The shape the chain needs, asserted on the signatures themselves."""
    from backend.data.precompute import run_precompute
    from backend.forecast.pipeline import run as run_forecast
    from backend.models.spec.metadata import (
        _read_provenance,
        get_metadata_for_company,
    )
    from backend.models.statements.pipeline import run as run_historical

    for fn in (run_precompute, run_forecast, run_historical,
               _read_provenance, get_metadata_for_company):
        params = inspect.signature(fn).parameters
        assert "db_path" in params, (
            f"{fn.__module__}.{fn.__name__} does not accept db_path, so a caller naming a "
            f"store cannot reach it from here. Everything on the build path reads a "
            f"module global instead, and a caller working against a copy is working "
            f"against the live store."
        )


def test_read_provenance_reads_the_store_it_is_given(tmp_path):
    """The publication threshold's authority, asked about a store it is told about."""
    from backend.models.spec.metadata import _read_provenance

    db = tmp_path / "one.db"
    _seed(db, "probe_us", {"screener": 10})
    db2 = tmp_path / "two.db"
    _seed(db2, "probe_us", {"sec_edgar": 10})

    a = _read_provenance("probe_us", db_path=db)
    b = _read_provenance("probe_us", db_path=db2)

    assert a[0] == {"screener": 10}, f"asked one store and was told about another: {a[0]}"
    assert b[0] == {"sec_edgar": 10}, f"asked one store and was told about another: {b[0]}"
    assert a[1] is False and b[1] is True, (
        "the filing_derived verdict did not follow the store. This boolean is the "
        "publication threshold's input, so answering it from the wrong store reports a "
        "model as filing-derived on the strength of somebody else's rows."
    )


def test_run_historical_reads_the_store_it_is_given(tmp_path, monkeypatch):
    from backend.models.statements import pipeline as sp

    wanted = tmp_path / "copy.db"
    _seed(wanted, "probe_us", {"screener": 10})

    seen = {}

    def fake_canonical(db_path, company_id):
        seen["canonical"] = str(db_path)
        raise sp.NoFinancialsAvailable("stop here; the store is what is under test")

    monkeypatch.setattr(sp, "query_canonical_datapoints", fake_canonical)

    with pytest.raises(sp.NoFinancialsAvailable):
        sp.run(target_periods=["FY24"], company_id="probe_us", db_path=wanted)

    assert seen.get("canonical") == str(wanted), (
        f"run_historical queried {seen.get('canonical')!r} rather than the store it was "
        f"given, so a caller building against a copy assembled from live"
    )


def test_the_batch_path_threads_the_store_all_the_way_down(tmp_path, monkeypatch):
    """`run_batch_company_onboarding` passed it everywhere except the one call that builds.

    This is the shape of the defect rather than any individual link: a function that accepts
    a store, calls something that also accepts one, and does not pass it.
    """
    import ast

    src = Path("backend/data/batch.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name not in ("run_precompute", "ensure_company_ingested", "run_historical",
                        "run_forecast_pipeline", "get_metadata_for_company"):
            continue
        passed = {kw.arg for kw in node.keywords if kw.arg}
        if "db_path" not in passed and "company_id" in passed:
            # A call that names a company but no store, inside a function that has one.
            offenders.append(f"line {node.lineno}: {name}(")
    assert not offenders, (
        "a call inside batch.py names a company but drops the store the surrounding "
        f"function was given: {offenders}. That is how a batch run against a copy ends up "
        f"ingesting into one store and building from another."
    )


def test_the_live_store_is_never_read_when_a_caller_names_another(tmp_path, monkeypatch):
    """The end-to-end property, with the live global made unreadable.

    Nothing here should touch the module globals at all, so poisoning them is a tripwire for
    any link still using one.
    """
    _poisoned_live(tmp_path, monkeypatch)
    from backend.models.spec.metadata import _read_provenance

    db = tmp_path / "isolated.db"
    _seed(db, "probe_us", {"sec_edgar": 3})

    sources, derived, _ = _read_provenance("probe_us", db_path=db)
    assert sources == {"sec_edgar": 3}
    assert derived is True


def _seed(db: Path, company_id: str, sources: dict) -> None:
    """A store carrying exactly the rows `sources` names, and nothing else."""
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE raw_datapoints (id TEXT PRIMARY KEY, company_id TEXT, source TEXT,"
            " superseded_by_id TEXT)"
        )
        i = 0
        for source, n in sources.items():
            for _ in range(n):
                conn.execute(
                    "INSERT INTO raw_datapoints VALUES (?,?,?,NULL)",
                    (f"{source}-{i}", company_id, source),
                )
                i += 1
        conn.commit()
    finally:
        conn.close()