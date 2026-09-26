"""The export endpoint must survive the load the browser actually creates.

Ten simultaneous exports took the deployed service down: it exhausted the
instance's memory and the container was killed, which reached the user as an
intermittent 500 and then a 502 or 503 while the instance restarted. Two things
were wrong and both are pinned here.

The exporter's formula-value registry is a module-level dict keyed by (sheet,
row, col), cleared at the start of every export. Two exports in flight share
those keys, so one wipes the other's values mid-write and each can write the
other's numbers into its own cells — a workbook that disagrees with the model it
came from. Exports are now serialised.

Output files were named for the ticker. Two onboarded companies share a ticker —
the same issuer listed in two markets — so both wrote one path and a download
could be served the other listing's workbook. Files are named per company.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi import HTTPException

import backend.api.routes as routes


class _FakeSpec:
    """The exporter only needs a ticker off the spec to name its output."""

    def __init__(self, ticker: str):
        self.metadata = type("Meta", (), {"ticker": ticker})()


@pytest.fixture
def stub_export(monkeypatch, tmp_path):
    """Replace the exporter with a slow, recording stand-in."""
    calls: list[str] = []
    gate = threading.Event()
    overlap = {"max": 0, "active": 0}
    lock = threading.Lock()

    def _fake_export(spec, path):
        with lock:
            overlap["active"] += 1
            overlap["max"] = max(overlap["max"], overlap["active"])
        try:
            # Long enough that a second request would overlap if unserialised.
            gate.wait(timeout=5)
            calls.append(str(path))
        finally:
            with lock:
                overlap["active"] -= 1
        from pathlib import Path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"xlsx")

    monkeypatch.setattr(routes, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(routes, "export_model_to_excel", _fake_export)
    monkeypatch.setattr(routes, "_get_or_build_spec", lambda cid: _FakeSpec("INFY"))
    return {"calls": calls, "overlap": overlap}


# --------------------------------------------------------------------------- #
# Capacity
# --------------------------------------------------------------------------- #

def test_simultaneous_exports_do_not_run_at_the_same_time(stub_export):
    """One export at a time is what fits in memory.

    Without the lock, ten requests each hold a specification and a workbook
    simultaneously and the instance is killed.

    The surplus beyond what may wait is refused with a 503 rather than queued, so
    a burst of clicks cannot fill the shared threadpool with threads doing
    nothing but waiting on a lock — which is what made the health check stop
    answering while the service was busy.
    """
    busy: list[str] = []
    served: list[str] = []
    lock = threading.Lock()

    def attempt(cid):
        try:
            routes.export_excel(company_id=cid)
            with lock:
                served.append(cid)
        except HTTPException as exc:
            with lock:
                busy.append(f"{cid}:{exc.status_code}")

    threads = [
        threading.Thread(target=attempt, args=(f"co{i}",)) for i in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert stub_export["overlap"]["max"] == 1, (
        f"{stub_export['overlap']['max']} exports ran concurrently; the exporter's "
        "formula-value registry is shared and one export clears another's values "
        "mid-write, and the instance cannot hold them all at once"
    )
    # Everything refused must be refused as BUSY, never as a fault.
    assert all(code.endswith(":503") for code in busy), f"unexpected refusals: {busy}"
    assert len(served) + len(busy) == 6, f"{len(served)} served, {len(busy)} refused"


def test_a_burst_does_not_starve_the_other_routes(stub_export, monkeypatch):
    """The health check must keep answering while exports are queued.

    The sync routes share one threadpool, so an unbounded queue of exports
    waiting on a lock would consume it and make the service look dead while
    doing exactly what it was asked to.
    """
    monkeypatch.setattr(routes, "_EXPORT_QUEUE_LIMIT", 1)
    monkeypatch.setattr(routes, "_EXPORT_WAIT_SECONDS", 0.05)
    routes._export_waiting = threading.Semaphore(routes._EXPORT_QUEUE_LIMIT)

    held = threading.Event()
    release = threading.Event()

    def _hold():
        routes._EXPORT_MUTEX.acquire()
        held.set()
        release.wait(timeout=10)
        routes._EXPORT_MUTEX.release()

    holder = threading.Thread(target=_hold)
    holder.start()
    assert held.wait(timeout=5)

    # A waiting export takes the only queue slot...
    waiter = threading.Thread(
        target=lambda: _swallow(lambda: routes.export_excel(company_id="aapl_us"))
    )
    waiter.start()
    try:
        # ...so a further request is turned away immediately rather than also
        # taking a thread to wait on.
        start = time.time()
        with pytest.raises(HTTPException) as caught:
            routes.export_excel(company_id="msft_us")
        assert caught.value.status_code == 503
        assert time.time() - start < 5.0, (
            "a request beyond the queue limit waited rather than being refused"
        )
    finally:
        release.set()
        holder.join(timeout=10)
        waiter.join(timeout=10)


def _swallow(fn):
    try:
        fn()
    except HTTPException:
        pass


def test_a_busy_service_says_so_instead_of_failing_opaquely(monkeypatch, tmp_path):
    """A waiting request gets an actionable answer, not a bare 500.

    A request that cannot get the lock is told the service is busy. Left to
    itself it would either pile onto an exhausted instance or time out, and both
    present as an unexplained failure.
    """
    monkeypatch.setattr(routes, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(routes, "_EXPORT_WAIT_SECONDS", 0.05)

    held = threading.Event()
    release = threading.Event()

    def _hold():
        routes._EXPORT_MUTEX.acquire()
        held.set()
        release.wait(timeout=10)
        routes._EXPORT_MUTEX.release()

    holder = threading.Thread(target=_hold)
    holder.start()
    assert held.wait(timeout=5)

    try:
        with pytest.raises(HTTPException) as caught:
            routes.export_excel(company_id="nvda_us")
    finally:
        release.set()
        holder.join(timeout=10)

    assert caught.value.status_code == 503
    assert "Retry-After" in (caught.value.headers or {})
    assert "busy" in caught.value.detail.lower() or "one at a time" in caught.value.detail.lower()


def test_the_lock_is_released_when_an_export_fails(stub_export, monkeypatch):
    """A failure must not leave the service permanently unable to export."""

    def _boom(spec, path):
        raise RuntimeError("workbook writer exploded")

    monkeypatch.setattr(routes, "export_model_to_excel", _boom)

    with pytest.raises(HTTPException) as caught:
        routes.export_excel(company_id="nvda_us")

    assert caught.value.status_code == 500
    # The detail names the company, because a bare "Internal Server Error"
    # tells the user nothing and tells us nothing.
    assert "nvda_us" in caught.value.detail

    assert routes._EXPORT_MUTEX.acquire(timeout=5), "the export lock was not released"
    routes._EXPORT_MUTEX.release()


def test_out_of_memory_is_reported_as_retryable(stub_export, monkeypatch):
    """The one failure a user can act on by trying again later."""
    monkeypatch.setattr(
        routes, "export_model_to_excel", lambda spec, path: (_ for _ in ()).throw(MemoryError())
    )

    with pytest.raises(HTTPException) as caught:
        routes.export_excel(company_id="nvda_us")

    assert caught.value.status_code == 503
    assert "Retry-After" in (caught.value.headers or {})


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #

def test_companies_sharing_a_ticker_get_separate_files(stub_export, monkeypatch):
    """The same issuer listed in two markets must not overwrite each other.

    Both onboarded companies carry the ticker INFY, so a ticker-keyed filename
    had them writing one path and a download could be served the other listing's
    workbook.
    """
    monkeypatch.setattr(routes, "_get_or_build_spec", lambda cid: _FakeSpec("INFY"))

    routes.export_excel(company_id="infy_infy")
    routes.export_excel(company_id="infy_us")

    paths = stub_export["calls"]
    assert len(set(paths)) == 2, f"both listings wrote the same file: {paths}"
    assert any("infy_infy" in p for p in paths)
    assert any("infy_us" in p for p in paths)


def test_the_output_path_cannot_escape_the_output_directory(stub_export):
    """A company id is used to build a filename, so it is treated as untrusted."""
    with pytest.raises(HTTPException):
        routes.export_excel(company_id="../../etc/passwd")
