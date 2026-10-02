"""The audit loop must be able to report what a gate said, whatever the console.

On 2026-10-02 loops 2 through 6 all came back "BLOCKED" with no failing gate
named. None of them was red. `_run` decoded child output as UTF-8 while the child
inherited the console's locale, so `audit_valuation_figures.py` writing

    === aapl_us (AAPL — Apple Inc.)
    shares: 15,014.75  WACC=9.79%  (rfr 5.24 · beta 1.03 · erp 4.50)

arrived as 46 lines of U+FFFD. `main()` then tried to print those lines back to a
cp1252 console, which cannot encode U+FFFD, and raised UnicodeEncodeError -- while
printing a gate it had just marked PASS. The process exited 1 with no verdict, and
the qa, tests, self_check and site gates never ran at all.

That is the worst failure mode a gate has: exit code 1 that does not mean "a gate
blocked", arriving from a print statement, on a run where every gate that had
actually executed had passed. It is indistinguishable from a real block, so it
cannot be triaged -- only re-run.

Three properties are guarded here, and the first two are the whole fix:

  1. `_run` makes the child WRITE utf-8, so the utf-8 decode below it is exact
     rather than lossy. A company name or a figure can never become U+FFFD.
  2. `main()` installs errors="replace" on stdout and stderr, so a character this
     console cannot encode is replaced instead of raised. Reporting cannot be the
     thing that fails.
  3. The exit code still means one thing: a gate blocked.

Mutation-checked. Removing either half fails these tests: dropping PYTHONIOENCODING
from `_run` fails the round-trip, and removing the reconfigure call fails the
structural test.
"""

from __future__ import annotations

import importlib.util
import io
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "audit_loop.py"
SOURCE = GATE.read_text(encoding="utf-8")


def _load_gate():
    """Import the gate module under a registered name.

    The module builds a @dataclass, which resolves `cls.__module__` through
    sys.modules while it is being defined -- so exec_module alone raises
    AttributeError on None. Registering first is the difference between importing
    the gate and not.
    """
    spec = importlib.util.spec_from_file_location("valence_audit_loop", GATE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["valence_audit_loop"] = mod
    spec.loader.exec_module(mod)
    return mod


# Characters that the child used to emit in cp1252 and that a cp1252 console
# cannot read back: middle dot, em dash, Greek beta, rupee sign.
PROBE = (
    "import sys; sys.stdout.write("
    "chr(0xB7) + chr(0x2014) + chr(0x3B2) + chr(0x20B9))"
)
EXPECTED = chr(0xB7) + chr(0x2014) + chr(0x3B2) + chr(0x20B9)


class TestTheChildWritesUtf8SoTheDecodeIsExact:
    """Property 1. The decode in `_run` is only correct if the child wrote utf-8.

    `text=True, encoding="utf-8"` describes how to READ the child. Without the
    matching env the child writes the console's locale instead, and reading cp1252
    bytes as utf-8 yields U+FFFD -- 46 lines of it, on a gate that passed.
    """

    def test_non_ascii_round_trips_exactly(self):
        gate = _load_gate()
        code, out = gate._run([sys.executable, "-c", PROBE])
        assert code == 0, "the probe itself failed"
        assert out == EXPECTED, (
            "child output did not round-trip: the child is not writing utf-8, so "
            f"this gate will report {out!r} where it means {EXPECTED!r}. On "
            "2026-10-02 this produced 46 U+FFFD lines and then crashed main() "
            "while printing them."
        )

    def test_no_replacement_character_is_manufactured(self):
        gate = _load_gate()
        _code, out = gate._run([sys.executable, "-c", PROBE])
        assert chr(0xFFFD) not in out, (
            "a U+FFFD reached the caller: `_run` decoded bytes the child did not "
            "write as utf-8. A replacement character in a gate's report is a "
            "manufactured defect, and printing one to a cp1252 console raises."
        )

    def test_the_child_is_told_to_write_utf8(self):
        """The env must reach the child, not just be constructed.

        `child_env` built but never passed to subprocess.run is the failure that
        looks fixed and is not, so the child is asked what it can see.
        """
        gate = _load_gate()
        _code, out = gate._run(
            [
                sys.executable,
                "-c",
                'import os; print(os.environ.get("PYTHONIOENCODING"), '
                'os.environ.get("PYTHONUTF8"))',
            ]
        )
        assert out.strip() == "utf-8 1", (
            f"the child saw {out.strip()!r}, so it still writes the console's "
            "locale encoding and `_run` will corrupt every non-ASCII byte it sends"
        )

    def test_a_caller_supplied_env_is_still_honoured(self):
        """Forcing utf-8 must not drop a caller's own env additions.

        `gate_self_check` passes PYTHONPATH; overriding env wholesale would break
        the one gate that needs it, and it would fail for a reason unrelated to
        encoding -- a regression reported as a different defect entirely.
        """
        gate = _load_gate()
        _code, out = gate._run(
            [sys.executable, "-c", "import os; print(os.environ.get('GATE_SENTINEL'))"],
            env={"GATE_SENTINEL": "kept"},
        )
        assert out.strip() == "kept"
        _code, out2 = gate._run(
            [sys.executable, "-c", "import os; print(os.environ.get('PYTHONIOENCODING'))"]
        )
        assert out2.strip() == "utf-8", "the caller env replaced the encoding fix"


class TestReportingCannotBeTheThingThatFails:
    """Property 2. A console that cannot encode a character must not end the run.

    The crash was in main()'s own print, one line after `[PASS] excel`. Any
    character outside cp1252 -- a beta in a workbook label, a rupee sign in a
    company name -- could do the same, so the policy is installed on the process
    streams before any gate is read.
    """

    def test_main_installs_a_replace_policy_on_the_streams(self):
        assert "reconfigure(errors=" in SOURCE, (
            "main() no longer installs errors=\"replace\" on stdout/stderr, so an "
            "unencodable character raises UnicodeEncodeError out of a print "
            "statement and the loop exits 1 with no verdict -- which is "
            "indistinguishable from a blocked gate"
        )

    def test_the_policy_is_installed_before_any_gate_runs(self):
        """Order matters: the header prints before the first gate.

        Installed after the gate loop, the fix protects nothing -- the crash
        happened while printing a result, which is exactly this window.
        """
        i_policy = SOURCE.find("reconfigure(errors=")
        i_header = SOURCE.find("LAUNCH AUDIT LOOP")
        i_first_gate = SOURCE.find("res = fn()")
        assert i_policy != -1
        assert i_header != -1 and i_first_gate != -1
        assert i_policy < i_header, (
            "the replace policy is installed after the first print, so the header "
            "or an early gate's report can still raise"
        )
        assert i_policy < i_first_gate

    def test_the_policy_is_installed_on_both_streams(self):
        assert "for _stream in (sys.stdout, sys.stderr)" in SOURCE, (
            "only one stream is reconfigured; stderr reports gate tracebacks and "
            "would still be able to kill the run"
        )

    def test_an_unencodable_write_does_not_raise(self):
        """The property itself, on a stream that really cannot encode it.

        cp1252 has no U+03B2. With errors="replace" the write succeeds and the
        byte becomes '?'; without it, UnicodeEncodeError.

        The character must be the actual Greek beta -- the ASCII word "beta" is
        perfectly encodable in cp1252 and would assert nothing at all, which is
        how a test of this kind passes while guarding nothing.
        """
        beta = chr(0x3B2)
        assert beta not in "beta", "the probe must be the Greek letter"
        buf = io.BytesIO()
        stream = io.TextIOWrapper(buf, encoding="cp1252", newline="")
        stream.reconfigure(errors="replace")
        stream.write(beta + "\n")
        stream.flush()
        assert buf.getvalue() == b"?\n"

    def test_the_same_write_raises_without_the_policy(self):
        """The control: prove the policy is what prevents the crash.

        Without errors="replace", writing U+03B2 to a cp1252 stream raises. This
        is the exact exception that ended loops 2 through 6, so it is recorded
        here in the form it actually arrives in.
        """
        buf = io.BytesIO()
        stream = io.TextIOWrapper(buf, encoding="cp1252", newline="")
        with pytest.raises(UnicodeEncodeError):
            stream.write(chr(0x3B2) + "\n")

    def test_a_stream_without_reconfigure_is_not_an_error(self):
        """A StringIO in a test, or a closed pipe, must not break main().

        The try/except is load-bearing: if reconfigure raises AttributeError on a
        stream that lacks it, main() dies before parsing arguments, and the loop
        reports nothing at all.
        """
        assert "except (AttributeError, ValueError, OSError)" in SOURCE, (
            "main() calls reconfigure unguarded, so a stream that does not support "
            "it takes the whole loop down before a single gate runs"
        )


class TestTheExitCodeStillMeansOneThing:
    """Property 3. Whatever the encoding, the verdict must still be readable.

    The 2026-10-02 failure was reported by the *caller* as BLOCKED with an empty
    list of failures, because the process died before printing CLEAN or BLOCKED.
    A loop that can exit 1 without saying which gate blocked cannot be triaged.
    """

    def test_the_verdict_is_printed_after_every_gate_has_run(self):
        """The verdict must come from the last gate, not from the first.

        Searching for the phrase "gate(s) blocking" alone finds the COMMENT in
        `gate_site` that quotes it ("the run finished with 0 gate(s) blocking"),
        not the print. Anchoring on the print statement itself is the difference
        between checking the order of real execution and comparing two comments.
        """
        i_verdict = SOURCE.find("{len(blocked)} gate(s) blocking")
        i_gates = SOURCE.find("res = fn()")
        assert i_verdict != -1, "the verdict print could not be located in main()"
        assert i_gates != -1
        assert i_verdict > i_gates, "the verdict is printed before gates run"

    def test_a_gate_that_raises_is_recorded_not_propagated(self):
        """An exception inside a gate must become a FAIL line, not a dead loop.

        If a gate raises and main() propagates, the run exits without a verdict
        and the next caller sees BLOCKED with nothing to fix -- the same symptom
        as the encoding crash, from a different cause.
        """
        assert "gate raised" in SOURCE
        i_raise = SOURCE.find("gate raised")
        i_except = SOURCE.find("except Exception as exc")
        assert i_except != -1 and i_raise > i_except

    def test_the_verdict_line_is_reachable_from_the_source(self):
        """The exit code must be derived from the blocked list, not hardcoded.

        `return 1 if blocked else 0` is the whole contract between this loop and
        whoever runs it. If it is ever replaced by a constant, every gate could
        pass and the run would still report failure -- or worse, every gate could
        fail and report success.
        """
        assert "BLOCKED" in SOURCE and "CLEAN" in SOURCE
        assert "1 if blocked else 0" in SOURCE, (
            "the exit code is no longer derived from the blocked gates, so the "
            "process's exit status no longer means what the verdict says"
        )
