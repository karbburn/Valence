"""Serving the stale hero artwork is a decision, and a decision must be checkable.

`scripts/check_launch_artwork.py` compares the launch film's poster against the live model
and has three branches: figures match (serve it), artwork served nowhere (figures free to be
wrong), or stale AND served. The third is the one the defect lives in, and it used to be an
unconditional exit 1.

That was the right rule while the film was off the page. The film is on the page now, because
the hero reserves six columns for a visual and an empty column beside a headline is not a
restraint, it is a hole. Serving it is the owner's decision, so it gets a record rather than
a silenced gate: `valence-launch-acceptance.json`, carrying a reason, the date it was taken,
and a `review_by` date after which it stops applying.

Three properties are guarded, and the third is the one a naive fix breaks:

  1. A stale, served artwork with a valid acceptance PASSES, and says why.
  2. A stale, served artwork with NO record still FAILS -- this is the original defect and
     it must survive, or the gate has become decoration.
  3. The acceptance EXPIRES. Past `review_by` it fails again, and it fails for a record
     that cannot be checked: no reason, no review date, or a date that does not parse.

Property 3 is what stops this from being bought with a hole. An acceptance that could not
expire would be a permanent way around the check rather than a decision with an end, and
one whose reason nobody wrote is a decision nobody can question.

The branch is called directly rather than through `main`, because `main` needs two live
servers -- and a test that reimplements the branch instead of calling it is a test a
mutation can survive, which is the failure mode this file's sibling documents.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "check_launch_artwork.py"


def _load_gate():
    """Import the gate module under a registered name.

    The module is plain functions, but registering before exec_module is what the sibling
    gate needs and copying its loader is cheaper than diverging.
    """
    spec = importlib.util.spec_from_file_location("valence_launch_artwork", GATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE_MOD = _load_gate()

REASON = "the card will be re-cut at the same dimensions"


def _with_acceptance(tmp_path, **overrides):
    """Point the gate at a temp acceptance file holding `overrides` over the defaults."""
    record = {"reason": REASON, "accepted_on": "2026-10-06", "review_by": "2026-11-06"}
    record.update(overrides)
    path = tmp_path / "valence-launch-acceptance.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    GATE_MOD.ACCEPTANCE = path
    return path


def _without_acceptance(tmp_path):
    GATE_MOD.ACCEPTANCE = tmp_path / "absent.json"
    return GATE_MOD.ACCEPTANCE


class TestAValidAcceptanceOpensTheBranch:
    def test_it_passes_and_says_the_review_date(self, tmp_path):
        _with_acceptance(tmp_path)
        code, lines = GATE_MOD.stale_and_served("2026-10-06")
        assert code == 0, "a current, reasoned acceptance did not open the branch"
        text = "\n".join(lines)
        assert "2026-11-06" in text, "the printed verdict names no review date"
        assert REASON in text, "the printed verdict drops the recorded reason"

    def test_it_passes_on_the_review_date_itself(self, tmp_path):
        """Expiry is after the date, not on it -- a decision holds through its last day."""
        _with_acceptance(tmp_path)
        code, _ = GATE_MOD.stale_and_served("2026-11-06")
        assert code == 0

    def test_the_message_admits_the_figures_are_stale(self, tmp_path):
        """Accepted is not the same as fine, and the output must not read as clean.

        The CLEAN branch exists above this one; what this prints has to be
        distinguishable from it, or a reader skimming for one word sees a pass and
        never learns the hero is carrying a figure eighteen points out.
        """
        _with_acceptance(tmp_path)
        _, lines = GATE_MOD.stale_and_served("2026-10-06")
        text = "\n".join(lines)
        assert "ACCEPTED" in text
        assert "CLEAN" not in text


class TestTheOriginalDefectStillFails:
    """The record is what opened this branch, so its absence must close it."""

    def test_no_record_is_a_failure(self, tmp_path):
        _without_acceptance(tmp_path)
        code, lines = GATE_MOD.stale_and_served("2026-10-06")
        assert code == 1, (
            "stale artwork served with nothing recording it passed. That is the original "
            "defect: a false claim on the hero with no decision behind it."
        )
        assert "NOT ACCEPTED" in "\n".join(lines)

    def test_the_absent_record_is_not_a_parse_error(self, tmp_path):
        """A missing file and a broken file are different findings.

        Conflating them would let a deleted record read as a malformed one, and the
        message is what tells the next person which action fixes it.
        """
        _without_acceptance(tmp_path)
        record, bad = GATE_MOD.load_acceptance()
        assert record is None and bad is None


class TestTheAcceptanceCannotBecomeAPermanentHole:
    def test_it_fails_the_day_after_the_review_date(self, tmp_path):
        _with_acceptance(tmp_path)
        code, lines = GATE_MOD.stale_and_served("2026-11-07")
        assert code == 1, (
            "an expired acceptance still opened the branch. An acceptance that cannot "
            "expire is a permanent way around the check, not a decision with an end."
        )
        assert "expired" in "\n".join(lines)

    def test_a_record_with_no_reason_does_not_open_the_branch(self, tmp_path):
        """An unreasoned acceptance is a decision nobody can question."""
        _with_acceptance(tmp_path, reason="")
        code, lines = GATE_MOD.stale_and_served("2026-10-06")
        assert code == 1
        assert "no reason" in "\n".join(lines)

    def test_a_record_with_no_review_date_does_not_open_the_branch(self):
        """Without `review_by` there is no date for it to stop applying on."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "a.json"
            path.write_text(json.dumps({"reason": REASON}), encoding="utf-8")
            GATE_MOD.ACCEPTANCE = path
            code, lines = GATE_MOD.stale_and_served("2026-10-06")
            assert code == 1
            assert "review_by" in "\n".join(lines)

    def test_a_record_that_does_not_parse_does_not_open_the_branch(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{ not json", encoding="utf-8")
        GATE_MOD.ACCEPTANCE = path
        code, lines = GATE_MOD.stale_and_served("2026-10-06")
        assert code == 1
        assert "NOT ACCEPTED" in "\n".join(lines)


class TestTheCommittedAcceptanceIsUsable:
    """The record actually shipped beside the artwork, read as the gate reads it."""

    def test_it_parses_carries_a_reason_and_a_future_review_date(self):
        path = REPO / "frontend" / "public" / "media" / "valence-launch-acceptance.json"
        assert path.exists(), "the acceptance record is not in the tree"
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record.get("reason", "").strip(), "the shipped acceptance states no reason"
        review = record.get("review_by", "")
        assert review and review > "2026-10-06", (
            f"the shipped acceptance is already expired ({review!r}), so the gate it "
            f"exists to pass is failing on the day it lands"
        )

    def test_the_claim_and_the_decision_are_separate_files(self, tmp_path):
        """Editing the figures must not be able to reach the passing branch.

        One file holding both would make a measurement and a decision one edit apart,
        and the whole point of the split is that they are different statements.
        """
        claim_path = REPO / "frontend" / "public" / "media" / "valence-launch-poster.json"
        claim = json.loads(claim_path.read_text(encoding="utf-8"))
        assert "review_by" not in claim, "the claim file now carries the acceptance"
        assert "reason" not in claim, "the claim file now carries the acceptance"
        _without_acceptance(tmp_path)
        code, _ = GATE_MOD.stale_and_served("2026-10-06")
        assert code == 1, "with no acceptance file, a stale served poster passed"
