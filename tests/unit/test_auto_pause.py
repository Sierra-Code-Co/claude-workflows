"""Auto-pause state session: fcntl.flock spans read-modify-write; concurrent writers don't tear."""
from __future__ import annotations

import json
import shutil

# Direct execution needs `scripts` on the path; pytest supplies it via
# pyproject's `pythonpath` and nothing supplies it outside pytest. Without
# this the `__main__` guard below is a promise the file cannot keep —
# T005i-b found seven such modules here, none able to run standalone.
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from review_plan_v2.auto_pause import state_session


class AutoPauseTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "state.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fresh_state_starts_at_zero(self):
        with state_session("/repo/a", "main", state_path=self.state_path) as s:
            self.assertEqual(s.consecutive_trivial, 0)
            self.assertFalse(s.should_pause(3))

    def test_record_trivial_increments(self):
        with state_session("/repo/a", "main", state_path=self.state_path) as s:
            s.record(was_trivial=True, head_commit="aaa")
        with state_session("/repo/a", "main", state_path=self.state_path) as s:
            self.assertEqual(s.consecutive_trivial, 1)
            self.assertEqual(s.last_run_commits, ["aaa"])

    def test_record_actionable_resets(self):
        for _ in range(2):
            with state_session("/repo/a", "main", state_path=self.state_path) as s:
                s.record(was_trivial=True)
        with state_session("/repo/a", "main", state_path=self.state_path) as s:
            self.assertEqual(s.consecutive_trivial, 2)
            s.record(was_trivial=False)
        with state_session("/repo/a", "main", state_path=self.state_path) as s:
            self.assertEqual(s.consecutive_trivial, 0)

    def test_should_pause_threshold(self):
        for _ in range(3):
            with state_session("/repo/a", "main", state_path=self.state_path) as s:
                s.record(was_trivial=True)
        with state_session("/repo/a", "main", state_path=self.state_path) as s:
            self.assertTrue(s.should_pause(3))
            self.assertFalse(s.should_pause(4))

    def test_per_repo_per_branch_isolation(self):
        with state_session("/repo/a", "main", state_path=self.state_path) as s:
            s.record(was_trivial=True)
        with state_session("/repo/a", "feature", state_path=self.state_path) as s:
            self.assertEqual(s.consecutive_trivial, 0)
        with state_session("/repo/b", "main", state_path=self.state_path) as s:
            self.assertEqual(s.consecutive_trivial, 0)

    def test_concurrent_serialized_no_torn_writes(self):
        # Two threads doing 10 increments each. Lock spans full session, so no race.
        #
        # That comment was TRUE OF THE LOCKED REGION and false of the code that
        # ran before it: creation happened outside the lock, so this test failed
        # 9 times in 25 container runs with `19 != 20` and was written off as
        # flaky (T011a). It was reporting a real lost update, correctly, every
        # time it lost the race. It never once failed on macOS, which is why the
        # deterministic simulation below exists — a probabilistic test that
        # cannot reproduce on the machine you develop on cannot prove a fix.
        def worker():
            for _ in range(10):
                with state_session("/repo/a", "main", state_path=self.state_path) as s:
                    s.record(was_trivial=True)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        with state_session("/repo/a", "main", state_path=self.state_path) as s:
            self.assertEqual(s.consecutive_trivial, 20)
        # File is also valid JSON (no torn writes)
        data = json.loads(self.state_path.read_text())
        self.assertIsInstance(data, dict)

    def test_a_queued_run_says_it_is_waiting(self):
        """A silent wait is indistinguishable from a hang, and this one cost 20
        minutes of diagnosis.

        The lock is exclusive and spans a whole review, and the DEFAULT path is
        one file shared by every repo on the machine. Two real runs were started
        three minutes apart in different repos; the second printed the
        gate-portfolio line and then nothing at all, while `ps` showed a live pid
        with no child process and the network kept moving for the first run. Every
        hang diagnostic said "fine", because it was fine — it was queued.

        The blocking wait itself is correct and is NOT what is asserted here. What
        is asserted is that it announces itself BEFORE the wait ends, because this
        tool also tells its operator that a run may legitimately exceed ten
        minutes, which removes the one signal a silent queue could otherwise have
        been read from. A message printed on the way out is worth nothing to the
        person staring at a stalled terminal, and the ordering is what makes it a
        signal rather than a log line.
        """
        import io
        import subprocess as sp

        # A separate PROCESS, not a thread: fcntl locks are per open file
        # description and a second flock from the same process would be granted
        # rather than blocked, so a threaded version of this test would assert
        # nothing. That is the same "the check cannot fail" shape this suite keeps
        # finding, so it is worth the subprocess.
        #
        # The holder blocks on stdin rather than sleeping, and that is the whole
        # design of this test. It used to `time.sleep(1.5)`, which made the test
        # brittle in one direction and vacuous in the other. Brittle: on a loaded
        # CI box, if this process took longer than 1.5s to reach the flock, the
        # lock was already free, nothing was contended, and the WAITING assertion
        # failed for a reason that has nothing to do with the tool. Vacuous: 1.5s
        # is also long enough that the message could have been emitted at the END
        # of the wait and still landed in the buffer, so the ordering the docstring
        # claims was assumed rather than checked.
        #
        # Blocking on stdin removes both. The lock is held until something closes
        # the pipe, so there is no deadline to lose a race against, and the closer
        # is the arrival of the message itself (see the stderr below) — so the wait
        # cannot end before the message is printed, and the ordering is a fact
        # about the run rather than a hope about timing.
        #
        # Mutation-checked both ways, on a copy: deleting the message fails this
        # test in 30s (backstop, buffer empty), and MOVING the message below the
        # blocking flock — a message on the way out — also fails it, with the full
        # WAITING line present in the buffer. The old `assertIn` alone passed that
        # second mutant, which is what "vacuous in the other direction" meant.
        holder = sp.Popen(
            [sys.executable, "-c",
             "import fcntl,os,sys\n"
             "fd=os.open(sys.argv[1], os.O_RDWR|os.O_CREAT, 0o600)\n"
             "fcntl.flock(fd, fcntl.LOCK_EX)\n"
             "print('held', flush=True)\n"
             # Blocks until the test closes the pipe. Returns '' on EOF, so this
             # is a clean exit and the lock is released by process teardown.
             "sys.stdin.read()\n",
             str(self.state_path)],
            stdin=sp.PIPE, stdout=sp.PIPE, text=True,
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.terminate)
        self.assertEqual(holder.stdout.readline().strip(), "held",
                         "the holder process never acquired the lock")

        released = threading.Event()

        def release():
            released.set()
            try:
                holder.stdin.close()
            except (OSError, ValueError):
                pass

        # Cleanup, not just a happy path: if an assertion below fires first, the
        # pipe is closed anyway so the holder exits on EOF instead of being killed
        # with an open fd. Registered last, so LIFO runs it before terminate/wait.
        self.addCleanup(release)

        # The backstop exists so a tool that never prints the message FAILS this
        # test rather than hanging it. Without it, the regression this test guards
        # — a wait that says nothing — would manifest as a suite that never
        # returns, which is the exact symptom the message is meant to prevent, now
        # inflicted on CI. 30s is far past the microseconds the real path needs and
        # far short of any pytest timeout.
        by_backstop = threading.Event()

        def backstop_release():
            by_backstop.set()
            release()

        backstop = threading.Timer(30.0, backstop_release)
        backstop.daemon = True
        backstop.start()
        self.addCleanup(backstop.cancel)

        class ReleaseOnWaiting(io.StringIO):
            """A stderr that frees the lock the moment it sees the message.

            Checked against the accumulated buffer, not the single write: `print`
            emits the text and the newline as two separate writes, and a substring
            test against one write alone would miss a message split across them.
            """

            def write(self, s):
                n = super().write(s)
                if not released.is_set() and "WAITING" in self.getvalue():
                    release()
                return n

        err = ReleaseOnWaiting()
        with mock.patch.object(sys, "stderr", err):
            with state_session("/repo/a", "main", state_path=self.state_path) as s:
                s.record(was_trivial=True)
        backstop.cancel()
        msg = err.getvalue()
        # Ordering, asserted rather than assumed. The lock could only have been
        # freed by the message arriving or by the backstop firing, so a backstop
        # release means the wait ended without the operator being told anything
        # while it was happening — even if the string turns up in the buffer later.
        self.assertFalse(
            by_backstop.is_set(),
            f"the 30s backstop released the lock, so the run waited in silence: {msg!r}")
        self.assertIn("WAITING", msg, f"a queued run printed nothing: {msg!r}")
        self.assertIn(str(self.state_path), msg,
                      "the message must name the file that is contended")
        self.assertIn("not a hang", msg)
        # And it must not name a holder pid. Every holder_pid in the file is
        # written by record() on clean exit, so the live holder has written
        # nothing and the pid on disk is the PREVIOUS run's — a claim that looks
        # checkable and is wrong exactly when someone checks it.
        #
        # Searched with the state path REMOVED first. The assertion above requires
        # that path to be in the message, and it is a mkdtemp path, so a run that
        # happened to land in /tmp/tmpr4pid9x/ would fail this line for a reason
        # that has nothing to do with the tool — a verdict that depends on a random
        # temp name is the same environment-dependent shape this suite keeps
        # removing. Only the tool's own words are checked.
        without_path = msg.replace(str(self.state_path), "")
        self.assertNotIn("pid", without_path.lower())

    def test_an_uncontended_run_says_nothing(self):
        """Anti-vacuous control. A message printed unconditionally would satisfy
        the test above while telling the operator every quiet run is queued."""
        import io

        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            with state_session("/repo/a", "main", state_path=self.state_path) as s:
                s.record(was_trivial=True)
        self.assertEqual(err.getvalue(), "",
                         "an uncontended run must not claim it is waiting")

    def test_corrupt_state_file_resets(self):
        self.state_path.write_text("not-json")
        with state_session("/repo/a", "main", state_path=self.state_path) as s:
            self.assertEqual(s.consecutive_trivial, 0)

    def test_creation_never_truncates_a_committed_value(self):
        """Deterministic guard for the lost update behind the `19 != 20` flake.

        The old `if not path.exists(): path.write_text("{}")` ran OUTSIDE the
        lock, so a thread that had already evaluated `exists()` as False could
        truncate a value another thread committed in the meantime — losing
        exactly one increment, every time, which is why the symptom was always
        19 and never 18.

        The concurrent test above reproduced it 9 times in 25 container runs and
        NEVER on macOS, so it could not be relied on to prove the fix. This
        forces the losing side's exact view — "the file did not exist when I
        looked" — while the file really does hold a committed value. That is a
        deterministic simulation of the interleaving, not a race to lose.
        """
        with state_session("/repo/a", "main", state_path=self.state_path) as s:
            s.record(was_trivial=True)
        persisted = json.loads(self.state_path.read_text())["/repo/a:main"]
        self.assertEqual(persisted["consecutive_trivial_runs"], 1)

        with mock.patch.object(Path, "exists", return_value=False):
            with state_session("/repo/a", "main", state_path=self.state_path) as s2:
                s2.record(was_trivial=True)
                observed = s2.consecutive_trivial

        self.assertEqual(
            observed, 2,
            "a session that thought the state file was missing destroyed a "
            "committed value; creation must not truncate (use O_CREAT, not "
            "exists()-then-write)",
        )


def test_a_round_whose_findings_were_all_suppressed_is_not_trivial():
    """`was_trivial` feeds auto-pause and must mean "the reviewers found nothing
    actionable", not "nothing actionable was displayed".

    A round where findings were suppressed because the developer fixed them is a
    round where work happened. Counting it trivial pauses reviews precisely when
    the branch is moving. Reported by review of T048.
    """
    import inspect

    from review_plan_v2 import orchestrator

    source = inspect.getsource(orchestrator.run)
    assert 'was_trivial = not any(f.severity == "actionable" for f in merged)' in source, (
        "was_trivial is no longer computed from the reviewers' own findings"
    )


if __name__ == "__main__":
    unittest.main()
