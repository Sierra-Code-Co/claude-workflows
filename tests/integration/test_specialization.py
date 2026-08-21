"""Specialization: each reviewer catches its kind of issue and only its kind."""
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



FIXTURES = REPO / "tests" / "fixtures"


class SpecializationTests(unittest.TestCase):
    def setUp(self):
        self.server = FixtureServer()
        self.base_url = self.server.start()
        self.repos: list[Path] = []

    def tearDown(self):
        self.server.stop()
        for r in self.repos:
            cleanup_repo(r)

    def _run_against(self, fixture_diff: str, fixture_name: str):
        repo = make_repo_from_diff(FIXTURES / fixture_diff)
        self.repos.append(repo)
        return run_v2(
            "--plain", "--base", "main", "--no-static-analyzers",
            cwd=repo, fixture_base_url=self.base_url, fixture_name=fixture_name,
            timeout=120,
        )

    def test_pascalcase_bug_caught_by_correctness_only(self):
        result = self._run_against("02-pascalcase-bug.diff", "02-pascalcase-bug")
        self.assertEqual(result.exit_code, 1, msg=f"stderr={result.stderr}\nstdout={result.stdout}")
        self.assertIn("[ACTIONABLE]", result.stdout)
        self.assertIn("[correctness]", result.stdout)
        self.assertNotIn("[security]", result.stdout)

    def test_sql_injection_caught_by_security_only(self):
        result = self._run_against("03-sql-injection.diff", "03-sql-injection")
        self.assertEqual(result.exit_code, 1, msg=f"stderr={result.stderr}\nstdout={result.stdout}")
        self.assertIn("[ACTIONABLE]", result.stdout)
        self.assertIn("[security]", result.stdout)
        self.assertNotIn("[correctness]", result.stdout)


if __name__ == "__main__":
    unittest.main()
