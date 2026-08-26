"""Exit-code semantics per contracts/cli-flags.md."""
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

from support.fixture_server import FixtureServer
from support.runner import cleanup_repo, make_repo_from_diff, run_v2

REPO = Path(__file__).resolve().parents[2]


FIXTURES = REPO / "tests" / "fixtures"


class ExitCodeTests(unittest.TestCase):
    def setUp(self):
        self.server = FixtureServer()
        self.base_url = self.server.start()
        self.repos: list[Path] = []

    def tearDown(self):
        self.server.stop()
        for r in self.repos:
            cleanup_repo(r)

    def _run(self, fixture_diff: str, fixture_name: str, *extra: str):
        repo = make_repo_from_diff(FIXTURES / fixture_diff)
        self.repos.append(repo)
        return run_v2(
            "--plain", "--base", "main", "--no-static-analyzers", *extra,
            cwd=repo, fixture_base_url=self.base_url, fixture_name=fixture_name,
            timeout=120,
        )

    def test_clean_diff_exit_zero(self):
        r = self._run("01-clean.diff", "01-clean")
        self.assertEqual(r.exit_code, 0)

    def test_actionable_finding_exit_one(self):
        r = self._run("02-pascalcase-bug.diff", "02-pascalcase-bug")
        self.assertEqual(r.exit_code, 1)

    def test_invalid_base_exit_two(self):
        repo = make_repo_from_diff(FIXTURES / "01-clean.diff")
        self.repos.append(repo)
        r = run_v2(
            "--plain", "--base", "nonexistent-branch-xyz", "--no-static-analyzers",
            cwd=repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=30,
        )
        self.assertEqual(r.exit_code, 2)
        self.assertIn("nonexistent-branch-xyz", r.stderr)

    def test_cost_cap_exit_three(self):
        # Use a tiny cost cap so even the small fixture diff exceeds it.
        r = self._run("01-clean.diff", "01-clean", "--max-cost-usd", "0.000001")
        self.assertEqual(r.exit_code, 3)
        self.assertIn("estimated cost", r.stderr.lower())


if __name__ == "__main__":
    unittest.main()
