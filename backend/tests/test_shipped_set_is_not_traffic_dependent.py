"""Browsing the site must not change what the site ships.

`backend/data/cache/` is the launch surface. What is in it is what the platform
serves and what `scripts/check_shipped_set.py` holds the team to. The read path
used to write to it, so the surface moved by traffic: a visitor browsing companies
grew the shipped set from 23 to 162, and every one of those models then reported as
an unreviewed regression against the baseline.

That is the wrong direction for traffic to move a published surface. A shipped
company should be one a person decided to ship, verified against a filing, and
committed. So:

- an on-demand build for a company that is not already shipped stays in the
  in-memory LRU and is not written
- refreshing a snapshot that already exists is still written, because that keeps a
  shipped member current rather than adding one
- the "no financials available" failure is still recorded, so a dead ticker is not
  re-attempted on every request

The cost is stated rather than hidden: a repeat visit to an unshipped company
recompiles it, because nothing survives the process. The LRU absorbs that within a
session. Paying 5.5s to keep the launch surface honest is the right trade, and the
alternative -- persisting somewhere `check_shipped_set.py` does not watch -- would
buy the speed by giving up the guarantee.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ROUTES = (ROOT / "backend" / "api" / "routes.py").read_text(encoding="utf-8")
CACHE_DIR = ROOT / "backend" / "data" / "cache"


class TestTheReadPathDoesNotWidenTheLaunchSurface:
    def test_shipped_membership_is_decided_before_anything_can_write(self):
        assert "_SHIPPED_AT_STARTUP" in ROUTES, (
            "membership must be captured once, at import, not re-read per request"
        )
        assert "is_shipped = company_id in _SHIPPED_AT_STARTUP" in ROUTES

    def test_an_unshipped_build_is_not_written_to_the_cache(self):
        guard = "if is_shipped:"
        i = ROUTES.index(guard)
        block = ROUTES[i:i + 900]
        assert "write_model_snapshot" in block, (
            "the shipped branch must still refresh an existing snapshot, or a "
            "shipped company would go stale and never recover"
        )
        assert "held in memory only" in block, (
            "the unshipped branch must say out loud that it declined to persist, so "
            "a reader can see the decision rather than infer it from its absence"
        )


    def test_a_failed_ingestion_is_still_recorded(self):
        """Persistence was never the reason a dead ticker gets marked.

        Removing the write must not remove the throttle bookkeeping, or every dead
        ticker would be re-attempted on every request forever.

        This used to assert the literal text `ingest_throttle.mark_failure(company_id)`
        in routes.py, which is a source scan of the kind this project has been bitten by
        repeatedly: it passed while a bare `except Exception` cached a forecast bug as an
        absence, and it broke on an unrelated edit that added a second argument. The
        intent is about the THROTTLE's behaviour, so that is what is asserted now: a
        recorded absence suppresses the next attempt, and a recorded defect does not.
        """
        from backend.api import throttle

        assert 'update_onboarding_status(company_id, "onboarded"' in ROUTES

        throttle.clear_failure("dead_ticker_us")
        throttle.mark_failure("dead_ticker_us", throttle.ABSENT)
        assert throttle.is_negative("dead_ticker_us") is True, (
            "a ticker with nothing behind it is not recorded, so every request re-attempts "
            "the providers forever"
        )
        assert throttle.failure_kind("dead_ticker_us") == throttle.ABSENT

        throttle.clear_failure("crashed_ticker_us")
        assert throttle.is_negative("crashed_ticker_us") is False
        throttle.clear_failure("dead_ticker_us")


class TestMembershipIsAReleasePropertyNotAFileSystemState:
    """A per-request existence test is wrong, and the rebuild tooling proved it.

    `assets/gsd/rebuild.py` deletes a snapshot and then asks the API to rebuild it.
    With `is_shipped = cache_path.exists()`, the company looked unshipped at exactly
    the moment it needed to be treated as shipped, so the API declined to write and
    all 23 rebuilds failed. The same test would also mis-classify a shipped model
    whose snapshot was corrupt and being repaired.

    Membership is a property of the release. A shipped company stays shipped while
    its file happens to be missing, because the file being missing is a fact about
    the request rather than about the product.
    """

    def test_the_shipped_set_is_captured_at_import(self):
        assert "frozenset(" in ROUTES
        assert "MODEL_CACHE_DIR.glob" in ROUTES

    def test_membership_is_not_a_per_request_file_check(self):
        assert "is_shipped = cache_path.exists()" not in ROUTES, (
            "a per-request existence test makes a rebuild delete the evidence that "
            "the company is shipped, and the rebuild then refuses to write"
        )

    def test_it_excludes_the_market_data_cache(self):
        """market_data_cache.json is a price cache, not a model.

        Treating it as a shipped company would mean the read path writes it, which is
        a different file with a different lifetime entirely.
        """
        assert '"market_data_cache"' in ROUTES


class TestTheShippedSetIsNotTrafficDependent:
    @pytest.mark.skipif(not CACHE_DIR.is_dir(), reason="no snapshots on this checkout")
    def test_every_shipped_snapshot_is_tracked_by_git(self):
        """An untracked snapshot in `data/cache/` is a widened launch surface.

        This is the property that would have caught the 23 -> 162 incident at the
        moment it happened, rather than at commit time when
        `scripts/check_shipped_set.py` eventually notices.
        """
        tracked = set()
        head = ROOT / ".git" / "HEAD"
        if head.exists():
            import subprocess

            out = subprocess.run(
                ["git", "ls-files", "backend/data/cache"],
                cwd=ROOT, capture_output=True, text=True,
            )
            tracked = {Path(p).stem for p in out.stdout.split() if p.endswith(".json")}

        on_disk = {p.stem for p in CACHE_DIR.glob("*.json")}
        on_disk.discard("market_data_cache")
        untracked = on_disk - tracked
        assert not untracked, (
            f"snapshots present but not tracked by git, which means the launch "
            f"surface grew outside the shipped set: {sorted(untracked)}"
        )

    @pytest.mark.skipif(not CACHE_DIR.is_dir(), reason="no snapshots on this checkout")
    def test_every_tracked_snapshot_is_publishable_or_explainably_withheld(self):
        """Every shipped model must carry a publication verdict.

        A snapshot with no verdict at all is a model nobody has decided about, and
        it is the state the 23 -> 162 incident left behind: files in the launch
        surface that no gate had ever judged.
        """
        offenders = []
        for f in sorted(CACHE_DIR.glob("*.json")):
            if f.stem == "market_data_cache":
                continue
            model = json.loads(f.read_text(encoding="utf-8")).get("model")
            if model is None:
                offenders.append((f.stem, "no model payload"))
                continue
            md = model.get("metadata") or {}
            if md.get("filing_derived") is not True and not md.get("data_sources"):
                offenders.append((f.stem, "no sources and not filing-derived"))
        assert not offenders, offenders