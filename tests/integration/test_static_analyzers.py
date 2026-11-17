"""Sequential gitleaks-first; halts run on actionable secrets WITHOUT calling LLMs."""
from __future__ import annotations

import json
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


class StaticOnlyModeTests(unittest.TestCase):
    """`--static-only` is the supported pre-push mode as of 2026-08-28.

    The model legs are retired: separately billed for a subset of what the
    PR-side reviewer finds anyway, and a run buffered per-file reviewer output
    at foreground priority with no cross-process guard, which panicked a 24 GB
    machine twice when three runs overlapped. What survives is the deterministic
    half, so these tests pin the two properties that make it worth keeping:
    nothing is transmitted, and a static run is not counted as a review round.
    """

    def setUp(self):
        reset_request_count()
        self.server = FixtureServer()
        self.base_url = self.server.start()
        self.repos: list[Path] = []

    def tearDown(self):
        self.server.stop()
        for r in self.repos:
            cleanup_repo(r)

    def test_static_only_calls_no_provider_and_says_what_it_did_not_check(self):
        repo = make_repo_from_diff(FIXTURES / "01-clean.diff")
        self.repos.append(repo)
        result = run_v2(
            "--plain", "--static-only", "--base", "main",
            cwd=repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=60,
        )
        self.assertEqual(result.exit_code, 0,
                         msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        # The whole point of the mode. A fixture server is wired and every
        # provider holds a key, so a request reaching it means a reviewer ran.
        self.assertEqual(get_request_count(), 0,
                         msg=f"--static-only called a provider "
                             f"({get_request_count()} requests recorded)")
        # A clean static run and a clean full review print the same "No findings"
        # body, so the banner is the only thing that keeps them apart.
        self.assertIn("STATIC ONLY", result.stderr)
        self.assertIn("CodeRabbit is the review", result.stderr)

    def test_static_only_does_not_advance_the_auto_pause_counter(self):
        # A static run reviews nothing, so counting it as a trivial round would
        # let three of them auto-pause the next real review.
        repo = make_repo_from_diff(FIXTURES / "01-clean.diff")
        self.repos.append(repo)
        state_file = repo / ".rpv2-state.json"
        result = run_v2(
            "--plain", "--static-only", "--base", "main",
            cwd=repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=60,
        )
        self.assertEqual(result.exit_code, 0,
                         msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        self.assertFalse(state_file.exists(),
                         msg=f"--static-only took the auto-pause state lock and "
                             f"wrote {state_file}")

    def _summary(self, stdout: str) -> dict:
        """The `type: summary` record out of an `--agent` NDJSON run."""
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            rec = json.loads(line)
            if rec.get("type") == "summary":
                return rec
        raise AssertionError(f"no summary record in agent output:\n{stdout}")

    def test_static_only_with_no_static_analyzers_is_a_tool_error(self):
        # The two flags together check nothing at all. Exit 2, because exit 0
        # here would be a clean verdict from a run that ran no gate of any kind.
        repo = make_repo_from_diff(FIXTURES / "01-clean.diff")
        self.repos.append(repo)
        result = run_v2(
            "--plain", "--static-only", "--no-static-analyzers", "--base", "main",
            cwd=repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=60,
        )
        self.assertEqual(result.exit_code, 2,
                         msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        self.assertEqual(get_request_count(), 0)

    # The three below exist because the check above passed while the guard it
    # tests was defeated by any of three other flags. CodeRabbit caught it on
    # PR #72: the check lived inside the step-6b static-only block, which the
    # empty-diff, --dry-run, and deterministic-short-circuit returns all precede.
    # Testing one spelling of an invalid combination proved nothing about the
    # combination, only about that spelling.

    def test_static_only_conflict_is_a_tool_error_even_with_dry_run(self):
        # MEASURED before the fix: exit 0, because --dry-run returned at step 6
        # and the contradiction was never reported.
        repo = make_repo_from_diff(FIXTURES / "01-clean.diff")
        self.repos.append(repo)
        result = run_v2(
            "--plain", "--static-only", "--no-static-analyzers", "--dry-run",
            "--base", "main",
            cwd=repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=60,
        )
        self.assertEqual(result.exit_code, 2,
                         msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        self.assertEqual(get_request_count(), 0)

    def test_static_only_conflict_is_a_tool_error_even_with_an_empty_diff(self):
        # MEASURED before the fix: exit 0 via the [NOTHING REVIEWED] return. The
        # worst spelling of the three — a run that both checked nothing and was
        # configured to check nothing, reporting success twice over.
        repo = make_repo_from_diff(FIXTURES / "01-clean.diff")
        self.repos.append(repo)
        result = run_v2(
            "--plain", "--static-only", "--no-static-analyzers", "--base", "HEAD",
            cwd=repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=60,
        )
        self.assertEqual(result.exit_code, 2,
                         msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        self.assertEqual(get_request_count(), 0)

    def test_static_only_reports_the_mode_when_an_analyzer_finds_something(self):
        # The clean-run test above cannot see this: a finding takes a different
        # render path, and `static_only` in the summary is what tells an agent
        # consumer that an exit 1 came from the deterministic half alone.
        repo = make_repo_from_diff(FIXTURES / "07-static-finding.diff")
        self.repos.append(repo)
        result = run_v2(
            "--agent", "--static-only", "--base", "main",
            cwd=repo, fixture_base_url=self.base_url,
            fixture_name="07-static-finding", timeout=60,
        )
        self.assertEqual(result.exit_code, 1,
                         msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        self.assertEqual(get_request_count(), 0)
        self.assertIn("STATIC ONLY", result.stderr)
        summary = self._summary(result.stdout)
        self.assertTrue(summary.get("static_only"),
                        msg=f"summary did not report static_only: {summary}")
        self.assertEqual(summary.get("providers_called"), [])
        self.assertIn("ruff", result.stdout)

    def test_static_only_halting_on_a_secret_still_reports_the_mode(self):
        # gitleaks halts at the deterministic short-circuit, which returns BEFORE
        # step 6b — so this path never runs the block that sets `static_only`, and
        # it has to be set at the short-circuit instead. Without it an exit 1 from
        # a static run is indistinguishable from an exit 1 from a full review.
        repo = make_repo_from_diff(FIXTURES / "04-secret-leak.diff")
        self.repos.append(repo)
        result = run_v2(
            "--agent", "--static-only", "--base", "main",
            cwd=repo, fixture_base_url=self.base_url,
            fixture_name="04-secret-leak", timeout=60,
        )
        self.assertEqual(result.exit_code, 1,
                         msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        self.assertEqual(get_request_count(), 0)
        summary = self._summary(result.stdout)
        self.assertTrue(summary.get("halted_on_secret"),
                        msg=f"summary did not report the secret halt: {summary}")
        self.assertTrue(summary.get("static_only"),
                        msg=f"summary did not report static_only: {summary}")


if __name__ == "__main__":
    unittest.main()
