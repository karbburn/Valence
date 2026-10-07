"""`ensure_company_ingested(db_path=None)` must mean its default store.

Precomputation threads an unresolved db_path down the build path:
`run_precompute(company_id=...)` has no store of its own to give, so it forwards
None, and each layer is expected to resolve None to the store its own contract
names. `normalization.pipeline.run` does exactly that, with the reasoning in its
docstring. `run_historical` does. `ensure_company_ingested` did not: its default
is bound on the signature, so an explicit None bypassed it and reached the store
as the string "None", where the first query created a store with that name,
found no canonical rows, and re-ingested the company into it.

Measured on a five-company refresh: each company was fetched a second time, five
seconds after the first, and 551 raw rows were written to a store beside the repo
root that no reader opens. The intended store still received the right data,
because the refresh's own pass had written it and the second pass normalized
against the live store anyway. Nothing failed. The only visible cost was a
stray file, which is the worst shape this defect can take: the wasted fetch and
the wrong-store write both sit on a path that still produces a correct answer.

The test stops the function at its first store read and asserts what the read
was handed. Under the defect that value is the string "None"; the fix hands it
the default the signature names.
"""
from __future__ import annotations

import pytest


class _StoppedAtTheFirstRead(Exception):
    """Raised in place of the real store read, so nothing is fetched or written."""


def test_a_store_argument_of_none_uses_the_default_store(monkeypatch):
    """The refresh path calls with an unresolved db_path; it must land on the default.

    The company id is never consulted and no store is opened: the spy raises on
    arrival, which keeps the test offline and keeps it from writing to whichever
    store it is asserting about.
    """
    from backend.data import batch

    seen = {}

    def spy(db_path, company_id=None):
        seen["db_path"] = str(db_path)
        raise _StoppedAtTheFirstRead

    monkeypatch.setattr("backend.data.store.query_canonical_datapoints", spy)

    with pytest.raises(_StoppedAtTheFirstRead):
        batch.ensure_company_ingested("any_company", db_path=None, force=False)

    assert seen["db_path"].endswith("valence.db"), (
        f"ensure_company_ingested was handed {seen['db_path']!r} when its caller named "
        f"no store. An explicit None bypasses the default bound on the signature and "
        f"reaches sqlite as the literal path 'None', where the first query creates a "
        f"store with that name, finds no canonical rows, decides the company was "
        f"never ingested and re-ingests it there: a second fetch of every source, "
        f"rows no reader opens, and a live store fed twice."
    )
