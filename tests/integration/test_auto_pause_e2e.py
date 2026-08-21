"""End-to-end auto-pause: 3 trivial runs → 4th exits 0 with auto-paused notice."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
# Restores direct execution (`python3 tests/integration/<file>.py`). pytest gets
# `tests` from pyproject's `pythonpath`, but a direct run has no such help, and
# the `if __name__ == "__main__"` guard at the foot of this file PROMISES that
# path works. Removing these two lines to clear an E402 broke that promise in
# eight modules at once, silently — pinned now by
# tests/unit/test_test_collection.py::test_a_guarded_module_runs_directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from support.fixture_server import FixtureServer  # noqa: E402
from support.runner import cleanup_repo, make_repo_from_diff, run_v2  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


FIXTURE_01 = REPO / "tests" / "fixtures" / "01-clean.diff"


class AutoPauseE2ETests(unittest.TestCase):
    def setUp(self):
        self.server = FixtureServer()
        self.base_url = self.server.start()
        self.repo = make_repo_from_diff(FIXTURE_01)

    def tearDown(self):
        self.server.stop()
        cleanup_repo(self.repo)

    def test_pauses_after_threshold(self):
        # 3 trivial runs should accumulate; 4th paused
        for i in range(3):
            r = run_v2(
                "--plain", "--base", "main", "--no-static-analyzers", "--auto-pause-n", "3",
                cwd=self.repo, fixture_base_url=self.base_url, fixture_name="01-clean",
                timeout=60,
            )
            self.assertEqual(r.exit_code, 0, msg=f"run {i+1}: stderr={r.stderr}")

        r4 = run_v2(
            "--plain", "--base", "main", "--no-static-analyzers", "--auto-pause-n", "3",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=60,
        )
        # Auto-paused exit 0 with notice
        self.assertEqual(r4.exit_code, 0, msg=f"4th run: stderr={r4.stderr}")
        self.assertIn("Auto-paused", r4.stderr)

    def test_force_full_bypasses_pause(self):
        # Warm-up runs must succeed for the test premise (pause threshold reached) to hold.
        for i in range(3):
            warm = run_v2(
                "--plain", "--base", "main", "--no-static-analyzers", "--auto-pause-n", "3",
                cwd=self.repo, fixture_base_url=self.base_url, fixture_name="01-clean",
                timeout=60,
            )
            self.assertEqual(warm.exit_code, 0, msg=f"warm-up {i+1} failed: stderr={warm.stderr}")
        r = run_v2(
            "--plain", "--base", "main", "--no-static-analyzers", "--auto-pause-n", "3", "--force-full",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=60,
        )
        self.assertEqual(r.exit_code, 0)
        self.assertNotIn("Auto-paused", r.stderr)


if __name__ == "__main__":
    unittest.main()
