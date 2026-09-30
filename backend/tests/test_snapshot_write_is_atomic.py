"""A model snapshot must never be readable in a partial state.

The model cache is written by a rebuild and read by the QA gate, the sitemap, and
the test suite, all in the same working tree. So the write has to be atomic: a
reader gets the whole previous snapshot or the whole new one, never a file cut
off partway through an object.

These tests exist because the write was not atomic and the only symptom was a
race. Five tests in test_peer_price_chain.py failed intermittently while a rebuild
was rewriting eight cache files, passed in isolation, and passed again on a
re-run -- which reads exactly like a flaky test that has stopped mattering. A
truncating ``open(path, "w")`` is the cause, and a test that asserts "no reader
sees a partial file" is the thing that would have said so the first time.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from backend.data.snapshot_io import read_model_snapshot, write_model_snapshot


def _valid_payload(marker: str) -> str:
    """A payload whose parseability is obvious only if the whole thing arrived."""
    body = {"company_id": "testco", "marker": marker, "nested": {"values": list(range(200))}}
    return json.dumps(body)


def test_a_reader_never_sees_a_partial_snapshot(tmp_path: Path) -> None:
    """Hammer the target while it is being rewritten; every read must parse.

    The payload is large enough that a plain truncating write leaves a readable
    gap: the file is emptied first, then filled, so a reader landing in the middle
    sees zero bytes or a prefix. With an atomic rename there is no window at all,
    so every one of these reads returns either the old payload or the new one.
    """
    target = tmp_path / "testco.json"
    old = _valid_payload("old")
    new_marker = "new-and-much-longer" * 40
    new = _valid_payload(new_marker)
    target.write_text(old, encoding="utf-8")

    failures: list[str] = []
    stop = threading.Event()

    def read_repeatedly() -> None:
        while not stop.is_set():
            try:
                text = read_model_snapshot(target)
            except OSError as exc:  # pragma: no cover - would be the bug
                failures.append(f"read failed outright: {exc}")
                return
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                failures.append(f"observed a partial snapshot: {exc}; got {len(text)} bytes")
                return
            if parsed.get("marker") not in ("old", new_marker):
                failures.append(f"observed an unrecognised payload: {parsed.get('marker')!r}")
                return
            # Real readers are not a hot loop -- the gate reads each file once and
            # the sitemap reads it once -- and Windows denies a rename for as long
            # as a handle is open, so the pause models the gap a reader leaves.
            time.sleep(0.001)

    readers = [threading.Thread(target=read_repeatedly) for _ in range(3)]
    for r in readers:
        r.start()
    try:
        for _ in range(40):
            write_model_snapshot(target, new)
            write_model_snapshot(target, old)
    finally:
        stop.set()
        for r in readers:
            r.join(timeout=10)

    assert not failures, failures[0]


def test_the_previous_snapshot_survives_a_failed_write(tmp_path: Path) -> None:
    """A write that fails partway must not cost the reader the snapshot it had.

    An ingest failure that half-completes should leave the last good model in
    place. Truncating in place would leave a zero-byte or short file, and the QA
    gate and the sitemap would then report a company as having no model at all --
    the engine loses a working answer to a failure it had already recovered from.

    A lone surrogate is used because it fails during encoding, partway through
    writing the temp file. That is the case that matters: the temp file is
    genuinely partial, and only the rename being deferred keeps the target intact.
    """
    target = tmp_path / "testco.json"
    good = _valid_payload("good")
    target.write_text(good, encoding="utf-8")

    with pytest.raises(UnicodeEncodeError):
        write_model_snapshot(target, '{"marker": "truncated \ud800"}')

    assert json.loads(target.read_text(encoding="utf-8"))["marker"] == "good"


def test_a_failed_write_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    """The temp file is cleaned up, so debris does not accumulate in the cache dir.

    The cache directory is walked by tooling that decides which companies have a
    snapshot. A ``*.tmp`` sibling left by a crash would either be mistaken for a
    company or, worse, be counted as one, and the directory is the same one the
    sitemap reads.
    """
    target = tmp_path / "testco.json"

    with pytest.raises(TypeError):
        write_model_snapshot(target, object())  # type: ignore[arg-type]

    leftovers = list(tmp_path.glob("*.tmp"))
    assert not leftovers, f"temp files left behind: {leftovers}"


def test_the_write_replaces_rather_than_appends(tmp_path: Path) -> None:
    """A second, shorter payload must fully replace the first.

    Guards the mode of the write independently of the atomicity: a snapshot that
    retained a tail from a longer previous write would still be valid JSON in
    some cases and silently wrong in others.
    """
    target = tmp_path / "testco.json"
    write_model_snapshot(target, _valid_payload("x" * 500))
    first_size = target.stat().st_size
    write_model_snapshot(target, _valid_payload("y"))
    assert target.stat().st_size < first_size
    assert json.loads(target.read_text(encoding="utf-8"))["marker"] == "y"


def test_the_temp_file_is_a_sibling_so_the_rename_stays_atomic(tmp_path: Path) -> None:
    """The swap only holds if the temp file is on the same filesystem.

    A temp file under the system temp directory would make os.replace a copy
    rather than a rename on Windows, reintroducing exactly the window this module
    exists to close -- and it would keep working on the developer's machine,
    because both paths are often the same volume in practice.
    """
    seen: list[Path] = []
    real_replace = os.replace

    def spy(src, dst):  # type: ignore[no-untyped-def]
        seen.append(Path(src))
        return real_replace(src, dst)

    target = tmp_path / "nested" / "testco.json"
    os.replace = spy  # type: ignore[assignment]
    try:
        write_model_snapshot(target, _valid_payload("m"))
    finally:
        os.replace = real_replace  # type: ignore[assignment]

    assert seen, "the writer did not go through a rename at all"
    assert seen[0].parent == target.parent, (
        f"temp file {seen[0]} is not beside the target {target}, so the swap is a copy"
    )
