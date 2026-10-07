"""Run the QA gate over every built model and report what changed.

Why a baseline rather than a plain pass/fail
--------------------------------------------

The plausibility checks were added to a repository whose existing models already
contain the bugs those checks are designed to catch. Measured on 2026-09-27, 13
of 25 models fail at least one of them, including several of the hand-built
reference reports. A gate that simply fails when any check fails would therefore
be red on its first run and would stay red, and a permanently red gate is a gate
nobody reads.

So this compares against a committed baseline of known failures:

* a check that has started failing where it passed is a **regression**, and the
  exit code is non-zero, which is what stops the commit;
* a check that has started passing is reported as a fix, and the baseline is
  regenerated with ``--update-baseline``;
* a check that was already failing stays failing silently, so the backlog is
  visible and shrinking rather than blocking everything.

This is the same contract as a compiler's warning baseline, applied to model
inputs. It makes the loop safe to run over thousands of companies: a new company
whose numbers are wrong shows up as a new entry in the report on day one,
without requiring the pre-existing backlog to be clean first.

Two modes, and the difference is the whole point
------------------------------------------------

``--mode snapshot`` (the default, and what CI gates a push on) reads the compiled
model for each company out of ``backend/data/cache/``, re-runs the check suite over
it, and touches no database, no network and no ingestion. It is deterministic, it
takes seconds, and it measures the artifact that actually ships.

``--mode live`` builds every model the way the API does, which means reading the
local database if one exists and reaching out to SEC, the NSE and a market feed if
one does not. That path is worth running, because it is how an ingestion break
shows up, but its result depends on whether a third party answered: the run that
red-lit this gate on 2026-09-29 reported ``wipro_wipro bridge_inputs_plausible``
failing on a cold runner and passing on a warm one, and Yahoo returned 404 for
``TATAMOTORS.NS`` while it did so.

A gate whose verdict depends on whether an outside server replied is not a gate.
It is a coin toss that blocks deploys, and once it blocks deploys often enough
people route around it, which is worse than having no gate. So the two modes are
separated: the deterministic one blocks, the noisy one reports. Weekly triage runs
``--live``; every push runs ``--mode snapshot``.

The two also compute different things, which is why they need different
baselines. Local runs had a warm ``valence.db`` that is gitignored and exists only
on one machine, so a baseline written locally described the warm path while CI
measured the cold one. That divergence went unnoticed for four consecutive pushes
because both were reporting plausible numbers.

Usage
-----
    python scripts/qa_gate.py                     # snapshot mode, gate on the baseline
    python scripts/qa_gate.py --update-baseline   # accept the current state
    python scripts/qa_gate.py --company nvda_us   # one company
    python scripts/qa_gate.py --mode live         # rebuild everything; reports, does not gate
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.data.snapshot_io import read_model_snapshot  # noqa: E402

BASELINE_PATH = Path("data/qa_gate_baseline.json")
CACHE_DIR = REPO_ROOT / "backend" / "data" / "cache"


def _load_baseline(path: Path) -> Dict[str, List[str]]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        # A corrupt baseline must not silently read as "nothing was failing",
        # which would turn every known failure into a fresh regression and make
        # the gate unusable rather than wrong.
        raise SystemExit(
            f"baseline at {path} is not valid JSON. Delete it and re-run with "
            f"--update-baseline to start a new one."
        )


def _failures_from_spec(spec) -> List[str]:
    checks = getattr(getattr(spec, "qa", None), "checks", None) or []
    failed = {c.check_name for c in checks if not c.passed}
    # A check the engine SKIPPED reports passed=true with the discrepancy in
    # the detail, so reading only `not passed` made it invisible to the gate:
    # the cash-flow identity could miss by four figures and every surface that
    # counts failures stayed green. A skip is a known-and-held condition like
    # any other failure here: it enters the same list, is baselined the same
    # way, and a skip that appears where there was none is a regression.
    failed.update(
        c.check_name
        for c in checks
        if c.passed and (c.detail or "").startswith("SKIPPED")
    )
    return sorted(failed)


def collect_failures_snapshot(company_ids: List[str]) -> Dict[str, List[str]]:
    """Run the check suite over each company's compiled snapshot. No network.

    The snapshot is re-validated rather than read for its baked-in QA result. The
    baked result is whatever the check suite said on the day that company was last
    built, so a company not rebuilt since a check was added carries no verdict for
    it at all: twelve of twenty-three snapshots reported no
    ``current_assets_reconcile`` failure simply because they predate the check.
    Re-running the suite over the snapshot's own data keeps the gate current
    without needing a rebuild, a database or a market feed.
    """
    from backend.models.spec.model_specification import ModelSpecification
    from backend.validation.pipeline import run_qa

    out: Dict[str, List[str]] = {}
    for cid in company_ids:
        path = CACHE_DIR / f"{cid}.json"
        if not path.exists():
            # A company with no compiled model is not a company that passed.
            out[cid] = ["NO_SNAPSHOT"]
            continue
        try:
            spec = ModelSpecification.model_validate(
                json.loads(read_model_snapshot(path))["model"]
            )
            run_qa(spec)
        except Exception as exc:  # noqa: BLE001
            out[cid] = [f"BUILD_FAILED: {type(exc).__name__}"]
            continue
        failed = _failures_from_spec(spec)
        if failed:
            out[cid] = failed
    return out


def collect_failures_live(company_ids: List[str]) -> Dict[str, List[str]]:
    """Build every model the way the API does, and return the failing check names.

    Includes the database when one is present, so a local run and a cold CI run are
    not the same measurement. Use it to find ingestion breakage, not to gate.
    """
    from backend.api.routes import _get_or_build_spec

    out: Dict[str, List[str]] = {}
    for cid in company_ids:
        try:
            spec = _get_or_build_spec(cid)
        except Exception as exc:  # noqa: BLE001
            # A build that will not run is a failure of the platform, and it is
            # recorded as such rather than skipped. Silently skipping is how a
            # company that cannot be modelled becomes a company that is missing.
            out[cid] = [f"BUILD_FAILED: {type(exc).__name__}"]
            continue
        failed = _failures_from_spec(spec)
        if failed:
            out[cid] = failed
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", action="append", help="company_id (repeatable)")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--baseline-path", default=str(REPO_ROOT / BASELINE_PATH))
    ap.add_argument(
        "--mode",
        choices=("snapshot", "live"),
        default="snapshot",
        help=(
            "snapshot: run the check suite over the committed compiled models, "
            "offline and deterministic, and gate on it. live: rebuild every model "
            "through the API path, which may read a local database and reach the "
            "network, and report without gating unless --live-strict is given."
        ),
    )
    ap.add_argument(
        "--live-strict",
        action="store_true",
        help="Make --mode live exit non-zero on a regression. Off by default because "
        "the live path's verdict depends on whether SEC, the NSE and a market feed "
        "answered, and a gate that depends on that blocks deploys for reasons no "
        "commit caused.",
    )
    args = ap.parse_args()

    baseline_file = Path(args.baseline_path)
    baseline = _load_baseline(baseline_file)

    # The baseline stores every company that was checked, including the ones
    # that passed. Storing only the failures would make a bare re-run check only
    # the already-broken models, so a company that was clean could break without
    # anything noticing. The passing entries are what make this a gate rather
    # than a list.
    #
    # In snapshot mode the scope comes from the COMPILED MODELS, not from the
    # baseline. Deriving scope from the baseline means a company missing from it is
    # never checked, silently and indefinitely: the gate reported "22 models" on
    # every run for a week while Meta — a shipped filer — was in no baseline at all,
    # because the live-mode run that wrote the baseline had not built it. A gate
    # that quietly checks less is worse than one that checks nothing, because its
    # result is believed. Scope is what ships; the baseline is only the record of
    # which failures are already known.
    snapshots = {
        p.stem for p in CACHE_DIR.glob("*.json") if p.name != "market_data_cache.json"
    }
    if args.mode == "snapshot":
        company_ids = args.company or sorted(snapshots)
    else:
        company_ids = args.company or sorted(baseline) or sorted(snapshots)

    uncovered = sorted(set(baseline) - set(company_ids))
    if uncovered:
        print(
            f"  note: {len(uncovered)} baseline entr(y/ies) have no compiled model and "
            f"were not checked: {', '.join(uncovered)}"
        )
    newly_in_scope = sorted(set(company_ids) - set(baseline))
    if newly_in_scope and not args.update_baseline:
        print(
            f"  note: {len(newly_in_scope)} shipped model(s) are not in the baseline and "
            f"will be reported as new: {', '.join(newly_in_scope)}"
        )

    if not company_ids:
        raise SystemExit(
            "no companies to check: no --company given, no compiled snapshots, and no "
            f"baseline file at {baseline_file}"
        )

    print(f"  mode           : {args.mode}")
    if args.mode == "snapshot":
        print(
            "  the committed snapshots are re-checked offline; no database and no "
            "network are consulted"
        )
    else:
        db = REPO_ROOT / "backend" / "data" / "valence.db"
        print(
            f"  rebuilding every model through the API path"
            f"{' against the local database, which is gitignored and exists only here' if db.exists() else ' cold, with no database'}"
        )

    current = (
        collect_failures_snapshot(company_ids)
        if args.mode == "snapshot"
        else collect_failures_live(company_ids)
    )

    regressions: Dict[str, List[str]] = {}
    fixed: Dict[str, List[str]] = {}
    for cid, failed in current.items():
        was = set(baseline.get(cid, []))
        now = set(failed)
        new = now - was
        if new:
            regressions[cid] = sorted(new)
        gone = was - now
        if gone:
            fixed[cid] = sorted(gone)
    for cid, was in baseline.items():
        if cid not in current and cid in company_ids:
            # It was failing and is no longer in scope to check. Not a fix.
            continue

    print(f"checked {len(company_ids)} models")
    print(f"  failing now : {len(current)}")
    print(f"  in baseline : {len(baseline)}")
    print(f"  regressions : {len(regressions)}")
    print(f"  fixed       : {len(fixed)}")

    if fixed:
        print("\nfixed since the last baseline:")
        for cid, names in sorted(fixed.items()):
            print(f"  {cid:28s} {', '.join(names)}")

    if current:
        print("\nfailing:")
        for cid, names in sorted(current.items()):
            # Print the NEW failures and the KNOWN ones under separate headings. The
            # line used to carry every check the company was failing under a single
            # REGRESSION marker as soon as one of them was new, so Amazon was reported
            # as having three regressions when it had one and two long-standing
            # known failures. A gate that over-reports is a gate whose numbers stop
            # being read, which is the one property it cannot afford to lose.
            new = [n for n in names if n not in baseline.get(cid, [])]
            known = [n for n in names if n in baseline.get(cid, [])]
            if new:
                print(f"  [REGRESSION] {cid:28s} {', '.join(new)}")
            if known:
                tag = "also failing" if new else "known"
                print(f"  [{tag:10s}] {cid:28s} {', '.join(known)}")

    if args.update_baseline:
        # Every checked company is written, passing ones included, as an empty
        # list of failures. Dropping the passes would shrink the scope of every
        # future bare run to only the models that are already broken.
        full = {cid: current.get(cid, []) for cid in company_ids}
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        baseline_file.write_text(
            json.dumps(full, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\nbaseline written to {baseline_file.relative_to(REPO_ROOT)}")
        return 0

    if regressions and args.mode == "live" and not args.live_strict:
        print(
            f"\n{len(regressions)} regression(s) on the live path, reported and NOT "
            "gating. This path rebuilds from SEC, the exchanges and a market feed, so "
            "its verdict moves with whether those answered rather than with the "
            "commit. Re-run with --mode snapshot to gate on the shipped artifact, or "
            "with --live-strict to fail the job anyway."
        )
        return 0

    if regressions:
        print(
            "\nREGRESSION. A model started failing a check it previously passed. "
            "Either fix the input, or if the new failure is correct, regenerate the "
            "baseline with --update-baseline and say why in the commit."
        )
        return 1

    print("\nno regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
