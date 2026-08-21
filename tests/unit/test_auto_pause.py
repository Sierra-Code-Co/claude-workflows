"""Auto-pause state session: fcntl.flock spans read-modify-write; concurrent writers don't tear."""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

# Direct execution needs `scripts` on the path; pytest supplies it via
# pyproject's `pythonpath` and nothing supplies it outside pytest. Without
# this the `__main__` guard below is a promise the file cannot keep —
# T005i-b found seven such modules here, none able to run standalone.
import sys
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
