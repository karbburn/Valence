from __future__ import annotations

"""Atomic writes for compiled model snapshots.

A compiled ``ModelSpecification`` is persisted to ``backend/data/cache/<id>.json``
and then read back by the QA gate, the sitemap, the frontend's build, and the test
suite -- all out of the same working tree that a rebuild writes into.

The obvious write is wrong for that topology:

    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)

``open(..., "w")`` truncates the target before any bytes are written, so a
concurrent reader can observe an empty file or a JSON document cut off partway
through an object. It fails as a ``JSONDecodeError`` in whatever process happened
to be reading, which reads as a broken test rather than a broken write. That is
how five tests in ``test_peer_price_chain.py`` came to fail intermittently, pass in
isolation, and pass again on a re-run -- and why the tempting response to a green
re-run is to conclude nothing was wrong.

Writing to a sibling temp file and renaming it onto the target makes the swap
atomic on both Windows and POSIX, so a reader sees either the whole previous
snapshot or the whole new one. Rename within a directory is the requirement: a
cross-filesystem move is a copy, which is not atomic.

There is one copy of this on purpose. The write is small, but it is the kind of
detail that is easy to re-derive slightly differently in each of the three places
that persist a model, and a second and third copy drifting from the first is how a
guarantee quietly stops holding.
"""

import os
import time
from pathlib import Path

# Windows refuses to replace a file that any process currently has open, because
# Python opens files without FILE_SHARE_DELETE. The readers here are short-lived --
# the QA gate, the sitemap, a request thread -- but a rebuild that gives up at the
# first refusal loses the snapshot it just spent a full valuation compiling, and
# `routes.py` logs that as a warning and serves the previous model, which is how a
# rebuild comes to "succeed" while persisting nothing.
#
# So the rename is retried briefly. This is a platform artefact, not a contention
# problem to solve more cleverly: the reader is going to close in microseconds, and
# the alternative -- write in place and accept partial reads -- reintroduces the
# bug this module exists to remove.
_RENAME_RETRY_SECONDS = 2.0
_RENAME_RETRY_INTERVAL = 0.005


def _replace_with_retry(tmp: Path, dest: Path) -> None:
    """``os.replace``, retried while Windows reports the target as open."""
    deadline = time.monotonic() + _RENAME_RETRY_SECONDS
    while True:
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(_RENAME_RETRY_INTERVAL)


def read_model_snapshot(cache_path: Path) -> str:
    """Read a model snapshot, tolerating a concurrent rename.

    On Windows it is the WRITER that hits the sharing violation, not the reader:
    with a handle open, ``os.replace`` raises PermissionError (winerror 5), so the
    rename does not land and the reader simply reads the intact previous file. That
    is why ``_replace_with_retry`` exists and why it is the load-bearing one.

    This retry exists anyway, and the reason is narrower than symmetry suggests.
    On POSIX a reader is never interrupted at all, and on Windows the observed
    behaviour is that it does not need to be. It is insurance against a platform
    or a filesystem where a reader does lose the race -- which was not observed and
    so is not claimed. Kept because the cost is a few milliseconds on a cache read,
    and removed because it is the kind of dead branch that misleads the next person
    into deciding whether reader-side retrying is load-bearing when it is not.

    The contract this actually keeps: a reader gets the whole snapshot or a
    retry, and never a document cut off mid-object.

    The filesystem is only sampled here, so a snapshot that is absent or truncated
    is returned to the caller to decide on rather than swallowed -- a caller asking
    about a company that has no model needs to be able to say so.
    """
    cache_path = Path(cache_path)
    deadline = time.monotonic() + _RENAME_RETRY_SECONDS
    while True:
        try:
            return cache_path.read_text(encoding="utf-8")
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(_RENAME_RETRY_INTERVAL)


def write_model_snapshot(cache_path: Path, payload: str) -> None:
    """Replace ``cache_path`` with ``payload`` as a single atomic step.

    Raises whatever the underlying write raised, after removing the temp file, so
    a caller that already logs and continues on failure keeps its old behaviour and
    does not leave debris beside the snapshots.
    """
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp, cache_path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
