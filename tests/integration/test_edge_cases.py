"""Edge cases: empty diff, malformed yaml, shell-injection-safe analyzer, degraded providers."""
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
# `scripts` too — same omission as test_cascade.py, same cause: the
# `review_plan_v2` import is indented inside a test method, so the line above
# covers the visible `support` imports and the file reads as bootstrapped.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from support.fixture_server import FixtureServer
from support.runner import cleanup_repo, make_repo_from_diff, run_v2

REPO = Path(__file__).resolve().parents[2]


FIXTURES = REPO / "tests" / "fixtures"


class EmptyDiffTests(unittest.TestCase):
    def setUp(self):
        self.server = FixtureServer()
        self.base_url = self.server.start()
        self.repo = make_repo_from_diff(FIXTURES / "01-clean.diff")
        # Reset to make HEAD == main (no diff)
        import subprocess
        subprocess.run(["git", "checkout", "main"], cwd=self.repo, check=True, capture_output=True)

    def tearDown(self):
        self.server.stop()
        cleanup_repo(self.repo)

    def test_empty_diff_exits_zero_no_llm_spend(self):
        result = run_v2(
            "--plain", "--base", "main", "--no-static-analyzers",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=30,
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Nothing to review", result.stdout)


class MalformedYamlTests(unittest.TestCase):
    def setUp(self):
        self.server = FixtureServer()
        self.base_url = self.server.start()
        self.repo = make_repo_from_diff(FIXTURES / "01-clean.diff")
        # Drop a malformed YAML
        (self.repo / ".coderabbit.yaml").write_text("path_filters: [unclosed-list\n", encoding="utf-8")

    def tearDown(self):
        self.server.stop()
        cleanup_repo(self.repo)

    def test_malformed_yaml_default_warns_then_runs(self):
        result = run_v2(
            "--plain", "--base", "main", "--no-static-analyzers",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=30,
        )
        # Default mode: warning + exit follows findings
        self.assertEqual(result.exit_code, 0, msg=f"stderr={result.stderr}")
        self.assertIn("WARNING", result.stderr)
        self.assertIn(".coderabbit.yaml", result.stderr)

    def test_malformed_yaml_strict_exits_five(self):
        result = run_v2(
            "--plain", "--base", "main", "--no-static-analyzers", "--strict-config",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=30,
        )
        self.assertEqual(result.exit_code, 5, msg=f"stderr={result.stderr}")


class DegradedProviderTests(unittest.TestCase):
    def setUp(self):
        self.server = FixtureServer()
        self.base_url = self.server.start()
        self.repo = make_repo_from_diff(FIXTURES / "01-clean.diff")

    def tearDown(self):
        self.server.stop()
        cleanup_repo(self.repo)

    def test_missing_broad_provider_key_with_no_other_provider_is_a_tool_error(self):
        """Zero operable providers MUST NOT report a clean review.

        Blanks whichever provider the BROAD pass actually uses, read from the
        registry rather than named here. It named DEEPSEEK_API_KEY, and when the
        broad default moved off deepseek that env_extra became a no-op: the run
        went green and the test passed while asserting nothing. A test that
        hardcodes the thing under configuration stops testing it the moment the
        configuration changes, and passes on the way out.

        This assertion was inverted until 2026-08-13: it required exit 0 and
        called that "graceful degradation". FR-009 does say affected reviewers
        are skipped gracefully — but that clause governs PARTIAL availability,
        and the rest of the spec is explicit about the zero-provider case:

          spec.md:178  "degrades gracefully if some are missing but cannot
                        operate with zero providers"
          spec.md:180  "silent skip would create false confidence"
          tasks.md T062 "missing DEEPSEEK_API_KEY (with no other configured
                        provider) → exit 2" (deepseek was the broad provider
                        when T062 was written; the requirement is about the
                        broad provider, not that vendor)

        T062 also specified this live in `test_degraded_providers.py`; the test
        that actually shipped was a different file asserting the opposite
        number. Exit 0 here means "reviewed, nothing found" to every pre-push
        hook and CI caller, on a run where no reviewer executed at all — the
        exact false-confidence failure the spec names twice.
        """
        from review_plan_v2.providers import registry

        # Blank EVERY key var of EVERY provider. Two separate traps:
        #   - Per provider, clearing one name is not enough: google accepts either
        #     GEMINI_API_KEY or GOOGLE_API_KEY, so it stays operable on the other.
        #   - Across providers, clearing only the broad one leaves this test's own
        #     premise ("zero operable providers") false, since run_v2 keys every
        #     provider in the registry. Exit 2 today is decided by the broad provider
        #     alone, so the narrower version passed — for a reason the test does not
        #     assert and that a change to the refusal rule would quietly invalidate.
        blanked = {var: "" for keys in registry.KEY_ENV.values() for var in keys}
        self.assertTrue(blanked, "registry has no key env vars at all")
        # Assert the broad provider HAS key vars, not that they are in `blanked`.
        # The `assertIn` this replaces was a tautology: `blanked` is built from
        # every value of KEY_ENV, so KEY_ENV[DEFAULT_BROAD]'s vars are members by
        # construction — and if that entry were empty the loop body never ran, so
        # the one thing worth checking was the one thing it skipped. Exit 2 below
        # is decided by the broad provider alone, so an unkeyed broad provider is
        # what makes this test's premise true.
        self.assertTrue(
            registry.KEY_ENV.get(registry.DEFAULT_BROAD),
            f"broad provider {registry.DEFAULT_BROAD!r} has no key env vars in "
            "registry.KEY_ENV, so blanking cannot make it inoperable and this "
            "test's premise of zero operable providers is false",
        )

        result = run_v2(
            "--plain", "--base", "main", "--no-static-analyzers",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            env_extra=blanked,
            timeout=30,
        )
        self.assertEqual(
            result.exit_code, 2,
            msg=f"zero operable providers must exit 2 (spec.md:178, T062), got {result.exit_code}; stderr={result.stderr}",
        )
        # Degrading is not crashing: the run still has to render a verdict that
        # says WHY, rather than dying or printing a bare "No findings."
        self.assertIn("DEAD-LEG", result.stdout.upper() + result.stderr.upper())


class ShellInjectionTests(unittest.TestCase):
    """Verify analyzers use shell=False and an args list (no command interpolation possible)."""

    def test_shellcheck_argv_includes_path_as_arg_not_shell(self):
        # Just exercise build_argv on a malicious-looking filename and ensure it lands as-is in argv (not shell-interpolated)
        from review_plan_v2.analyzers.shellcheck import ShellcheckAnalyzer
        from review_plan_v2.types import FileChange

        bad = FileChange(
            path="; rm -rf ~.sh", is_binary=False, is_renamed_from=None,
            added_lines=((1, 1),), diff_text="", language="shell",
        )
        argv = ShellcheckAnalyzer().build_argv([bad], "/tmp")
        self.assertEqual(argv[0], "shellcheck")
        self.assertIn("; rm -rf ~.sh", argv)
        # The malicious string is a single argv element — never going through a shell.


if __name__ == "__main__":
    unittest.main()
