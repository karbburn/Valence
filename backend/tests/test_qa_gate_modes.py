"""The gate must measure the same thing here as it does in CI.

The plausibility gate rebuilt every model through the API path. That path reads
`valence.db` when the file exists and reaches SEC, the exchanges and a market feed
when it does not — and `valence.db` is gitignored, so it exists on one machine and
nowhere else. A local run therefore measured a warm database and a CI run measured
a cold rebuild of the same companies, and the two disagreed: the CI gate reported
`wipro_wipro bridge_inputs_plausible` failing where the local run had it passing,
and went red on four consecutive pushes while the local loop reported it green on
every one. Neither number was wrong. They were answers to different questions.

So the gate has two modes and the distinction is the point. Snapshot mode reads the
compiled models that ship and runs the check suite over them with no database and
no network, which makes it deterministic and identical in both places. Live mode
still exists, because it is the only path that can notice an ingestion break, but
it reports rather than blocks: its verdict moves with whether an outside server
answered.

These tests hold both halves of that in place, and they hold the scope: the gate's
company list used to come from the baseline, so a company missing from the baseline
was never checked. Meta, a shipped filer, sat in no baseline at all while the gate
reported "22 models" on every run for a week.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "qa_gate.py"
CACHE = REPO / "backend" / "data" / "cache"
BASELINE = REPO / "data" / "qa_gate_baseline.json"


def _snapshots() -> set[str]:
    return {p.stem for p in CACHE.glob("*.json") if p.name != "market_data_cache.json"}


def _run(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class TestTheScopeIsWhatShips:
    def test_every_shipped_model_is_in_the_baseline(self):
        shipped = _snapshots()
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        missing = sorted(shipped - set(baseline))
        assert not missing, (
            f"{len(missing)} shipped model(s) are in no baseline, so the gate never "
            f"checks them: {missing}"
        )

    def test_the_gate_reports_one_model_per_snapshot(self):
        code, out = _run("--mode", "snapshot")
        assert code == 0, out
        line = next((l for l in out.splitlines() if l.strip().startswith("checked ")), "")
        assert line, f"no 'checked N models' line in:\n{out}"
        count = int(line.split()[1])
        assert count == len(_snapshots()), (
            f"the gate checked {count} model(s) while {len(_snapshots())} are "
            f"compiled; the difference is being checked less than ships"
        )

    def test_a_company_outside_the_baseline_is_called_out(self):
        """New scope must be visible, not absorbed."""
        code, out = _run("--mode", "snapshot")
        assert code == 0, out
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        extra = sorted(set(_snapshots()) - set(baseline))
        if not extra:
            return
        for cid in extra:
            assert cid in out, f"{cid} ships but the gate did not mention it"


class TestSnapshotModeIsOfflineAndDeterministic:
    def test_it_consults_no_database_and_no_network(self):
        code, out = _run("--mode", "snapshot")
        assert code == 0, out
        assert "no database and no network" in out, out
        assert "against the local database" not in out, (
            "snapshot mode took the database path, so it is measuring whatever this "
            "machine happens to hold rather than what ships"
        )

    def test_two_runs_agree_exactly(self):
        first_code, first = _run("--mode", "snapshot")
        second_code, second = _run("--mode", "snapshot")

        def verdict(text: str) -> list[str]:
            return sorted(
                l.strip() for l in text.splitlines()
                if l.strip().startswith("[REGRESSION]")
            )

        assert first_code == second_code == 0
        assert verdict(first) == verdict(second), (
            "two snapshot-mode runs disagreed, so the gate is not deterministic:\n"
            f"{verdict(first)}\n{verdict(second)}"
        )


class TestLiveModeReportsRatherThanBlocks:
    def test_a_live_regression_exits_zero_by_default(self, monkeypatch, tmp_path, capsys):
        """A gate that blocks on whether a market feed answered is a coin toss.

        `wipro_wipro` failed on a cold CI runner and passed on a warm one, and
        Yahoo was returning 404 for the same ticker during the run. Neither is
        something a commit caused, so neither may stop a deploy. Asserted on the
        exit code rather than on the wording, because the wording is not the
        contract.
        """
        from scripts import qa_gate

        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"wipro_wipro": []}), encoding="utf-8")

        def _regressed(company_ids):
            return {"wipro_wipro": ["bridge_inputs_plausible"]}

        monkeypatch.setattr(qa_gate, "collect_failures_live", _regressed)
        monkeypatch.setattr(
            sys, "argv",
            ["qa_gate.py", "--mode", "live", "--baseline-path", str(baseline)],
        )
        assert qa_gate.main() == 0, "a network-dependent regression blocked the run"

        captured = capsys.readouterr().out
        assert "wipro_wipro" in captured, captured
        assert "NOT gating" in captured or "not gating" in captured, (
            f"the run must say it is reporting rather than gating:\n{captured}"
        )

    def test_live_strict_does_fail(self, monkeypatch, tmp_path):
        from scripts import qa_gate

        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"wipro_wipro": []}), encoding="utf-8")

        monkeypatch.setattr(
            qa_gate, "collect_failures_live",
            lambda company_ids: {"wipro_wipro": ["bridge_inputs_plausible"]},
        )
        monkeypatch.setattr(
            sys, "argv",
            ["qa_gate.py", "--mode", "live", "--live-strict",
             "--baseline-path", str(baseline)],
        )
        assert qa_gate.main() == 1, "--live-strict must be able to fail the run"

    def test_a_snapshot_regression_does_fail(self, monkeypatch, tmp_path):
        """The deterministic path is the one that blocks, and it must still be able to."""
        from scripts import qa_gate

        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"aapl_us": []}), encoding="utf-8")

        monkeypatch.setattr(
            qa_gate, "collect_failures_snapshot",
            lambda company_ids: {"aapl_us": ["bridge_inputs_plausible"]},
        )
        monkeypatch.setattr(
            sys, "argv",
            ["qa_gate.py", "--mode", "snapshot", "--baseline-path", str(baseline)],
        )
        assert qa_gate.main() == 1, "snapshot mode must fail on a regression"

    def test_live_mode_still_exists(self):
        from scripts import qa_gate

        assert hasattr(qa_gate, "collect_failures_live"), (
            "the ingestion path is the only one that can notice a broken build, so "
            "it must not be deleted along with the gate that was failing on it"
        )
