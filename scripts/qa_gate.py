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

Usage
-----
    python scripts/qa_gate.py                     # gate against the baseline
    python scripts/qa_gate.py --update-baseline   # accept the current state
    python scripts/qa_gate.py --company nvda_us   # one company
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

BASELINE_PATH = Path("data/qa_gate_baseline.json")


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


def collect_failures(company_ids: List[str]) -> Dict[str, List[str]]:
    """Build every model and return the failing check names per company.

    The model is built through the same path the API uses, so the gate measures
    what a visitor would actually be served rather than a reimplementation of
    the pipeline.
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
        checks = getattr(getattr(spec, "qa", None), "checks", None) or []
        failed = sorted(c.check_name for c in checks if not c.passed)
        if failed:
            out[cid] = failed
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", action="append", help="company_id (repeatable)")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--baseline-path", default=str(REPO_ROOT / BASELINE_PATH))
    args = ap.parse_args()

    baseline_file = Path(args.baseline_path)
    baseline = _load_baseline(baseline_file)

    # The baseline stores every company that was checked, including the ones
    # that passed. Storing only the failures would make a bare re-run check only
    # the already-broken models, so a company that was clean could break without
    # anything noticing. The passing entries are what make this a gate rather
    # than a list.
    company_ids = args.company or sorted(baseline)
    if not company_ids:
        raise SystemExit(
            "no companies to check: no --company given and no baseline file at "
            f"{baseline_file}"
        )

    current = collect_failures(company_ids)

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
