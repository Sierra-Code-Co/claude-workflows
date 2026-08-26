"""Sequential gitleaks-first; halts run on actionable secrets WITHOUT calling LLMs."""
from __future__ import annotations

import shutil
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

from support.fixture_server import (
    FixtureServer,
    get_request_count,
    reset_request_count,
)
from support.runner import cleanup_repo, make_repo_from_diff, run_v2

REPO = Path(__file__).resolve().parents[2]


FIXTURES = REPO / "tests" / "fixtures"


class StaticAnalyzersTests(unittest.TestCase):
    """FAIL when gitleaks is missing. Never skip.

    This class used to carry `@unittest.skipIf(shutil.which("gitleaks") is
    None)`, and the pytest job never installed gitleaks — so from the day it was
    written until 2026-08-15 the assertion that a secret-bearing diff is never
    transmitted to an external LLM API did not run anywhere but a laptop. The
    separate `gitleaks` CI job scans for committed secrets and shares no runner
    with this one, which is why its presence bought these tests nothing.

    The skip was the wrong construct for a reason stronger than "coverage gap".
    MEASURED 2026-08-15 with gitleaks as the ONLY absent binary (every other
    tool symlinked into a shim PATH, so the variable is isolated):

        EXIT: 0                                          <- does not halt
        LLM REQUESTS WITH THE SECRET-BEARING DIFF: 4     <- it is transmitted

    In an environment without gitleaks the security property is not merely
    unverified — it is FALSE. `skipIf` reported silence about a configuration
    that leaks the thing this test exists to protect, which is Principle I
    stated as sharply as this repo can state it.

    A hard failure is also the cheaper contract now: CI installs gitleaks at the
    Dockerfile's pin, and test_toolchain_declared.py fails if the two drift.
    """

    @classmethod
    def setUpClass(cls):
        if shutil.which("gitleaks") is None:
            raise AssertionError(
                "gitleaks is not installed, so the secret-detection guarantee was "
                "NOT checked — and in this configuration it does not hold. Measured "
                "2026-08-15: a secret-bearing diff reaches the LLM endpoint 4 times "
                "and the run exits 0. Hard failure, not a skip. Install it "
                "(brew install gitleaks), or see the pinned install in "
                ".github/workflows/tests.yml."
            )

    def setUp(self):
        reset_request_count()
        self.server = FixtureServer()
        self.base_url = self.server.start()
        self.repos: list[Path] = []

    def tearDown(self):
        self.server.stop()
        for r in self.repos:
            cleanup_repo(r)

    def test_secret_in_diff_halts_with_exit_one(self):
        repo = make_repo_from_diff(FIXTURES / "04-secret-leak.diff")
        self.repos.append(repo)
        result = run_v2(
            "--plain", "--base", "main",
            cwd=repo, fixture_base_url=self.base_url, fixture_name="04-secret-leak",
            timeout=60,
        )
        # Secret in diff → gitleaks halts → exit 1, AND no LLM calls
        self.assertEqual(result.exit_code, 1, msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        self.assertIn("[ACTIONABLE]", result.stdout)
        self.assertIn("[secrets]", result.stdout)
        # Security contract: diff containing a secret must NEVER be transmitted to external LLM APIs.
        self.assertEqual(get_request_count(), 0,
                         msg=f"Diff was sent to external LLM despite secret detection ({get_request_count()} requests recorded)")

    def test_clean_diff_runs_all_local_analyzers(self):
        repo = make_repo_from_diff(FIXTURES / "01-clean.diff")
        self.repos.append(repo)
        result = run_v2(
            "--plain", "--base", "main",
            cwd=repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=60,
        )
        # Clean → exit 0
        self.assertEqual(result.exit_code, 0, msg=f"stdout={result.stdout}\nstderr={result.stderr}")


if __name__ == "__main__":
    unittest.main()
