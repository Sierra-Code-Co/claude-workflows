"""Happy-path integration test: clean diff → exit 0, no findings."""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

# Restores direct execution (`python3 tests/integration/<file>.py`). pytest gets
# `tests` from pyproject's `pythonpath`, but a direct run has no such help, and
# the `if __name__ == "__main__"` guard at the foot of this file PROMISES that
# path works. Removing these two lines to clear an E402 broke that promise in
# eight modules at once, silently — pinned now by
# tests/unit/test_test_collection.py::test_a_guarded_module_runs_directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from support.fixture_server import FixtureServer
from support.runner import cleanup_repo, make_repo_from_diff, run_v2

REPO = Path(__file__).resolve().parents[2]



FIXTURE_01 = REPO / "tests" / "fixtures" / "01-clean.diff"


class HappyPathTests(unittest.TestCase):
    def setUp(self):
        self.server = FixtureServer()
        self.base_url = self.server.start()
        self.repo = make_repo_from_diff(FIXTURE_01)

    def tearDown(self):
        self.server.stop()
        cleanup_repo(self.repo)

    def test_clean_diff_exits_zero(self):
        started = time.monotonic()
        result = run_v2(
            "--plain", "--base", "main", "--no-static-analyzers",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=120,
        )
        wall = time.monotonic() - started
        self.assertEqual(result.exit_code, 0, msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        self.assertIn("No findings", result.stdout)
        self.assertLess(wall, 120, "happy-path should finish well under 2 min on canned responses")


if __name__ == "__main__":
    unittest.main()
