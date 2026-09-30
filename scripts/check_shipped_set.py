"""Refuse to let the shipped set change shape without being noticed.

Why this exists, twice over.

The QA gate derives its scope from the snapshots on disk. That is deliberate: a
company missing from the baseline must not go ungated, which is how Meta went
ungated for a week. But it means the scope is whatever happens to be in
backend/data/cache, and anything that compiles a model there silently widens the
launch surface.

Twice now a verification run has done exactly that. Asking the live API for a
company it has never seen triggers on-demand ingestion, which compiles AND
persists a snapshot. The sampling harness wrote 139 of them and grew the shipped
set from 23 companies to 162, which turned a clean gate into 121 regressions for
models nobody had reviewed. Later, verifying a single fix end to end against UXIN
and American Well added 2 more and broke 5 tests -- the second time doing the thing
I had already written a fix for, which is the real argument for making it
structural.

An audit tool must not change what is under audit. This makes that a build-time
failure rather than something to remember.

    python scripts/check_shipped_set.py           # compare against git
    python scripts/check_shipped_set.py --allow-new aapl_us amzn_us
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "backend" / "data" / "cache"

# Runtime caches that legitimately appear and are not companies. market_data_cache
# holds provider responses and ticker_index/ holds the symbol universe.
IGNORED = {"market_data_cache.json"}


def tracked() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", "backend/data/cache"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    ).stdout
    return {Path(line).name for line in out.splitlines() if line.strip()}


def on_disk() -> set[str]:
    return {p.name for p in CACHE.glob("*.json")} - IGNORED


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-new", nargs="*", default=[],
                    help="company ids intentionally added to the shipped set")
    args = ap.parse_args()

    if not CACHE.exists():
        print(f"  no cache directory at {CACHE}")
        return 0

    known, actual = tracked(), on_disk()
    stray = sorted(actual - known - set(args.allow_new))
    missing = sorted(known - actual)

    for name in stray:
        print(f"  UNTRACKED SNAPSHOT  {name}")
    for name in missing:
        print(f"  MISSING SNAPSHOT    {name}")

    if not stray and not missing:
        print(f"  shipped set is {len(actual)} companies, matching git exactly")
        return 0

    print()
    print(f"  {len(stray)} untracked, {len(missing)} missing.")
    print()
    print("  An untracked snapshot here means something compiled a model into the")
    print("  shipped cache. That is usually a verification run reaching the live API,")
    print("  and it silently widens the launch surface -- the gate then reports")
    print("  regressions for models nobody reviewed.")
    print()
    print("  If the addition is intended, commit the file:")
    print("      git add backend/data/cache/<id>.json")
    print("  If not, remove it and re-run:")
    print(f"      {' '.join(f'del backend\\\\data\\\\cache\\\\{n}' for n in stray)}")
    print()
    print("  A missing snapshot means the shipped set shrank, which breaks every")
    print("  consumer that expects a company to be there. Restore it from git.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
