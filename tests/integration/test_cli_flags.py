"""CLI flag surface tests — drop-in compat with `coderabbit review --plain`."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
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


def _bare_run(*args: str) -> tuple[str, str, int]:
    """Invoke the module with an isolated HOME so per-user state doesn't leak across tests."""
    isolated_home = tempfile.mkdtemp(prefix="rpv2-cli-home-")
    try:
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
               "PYTHONPATH": str(REPO / "scripts"),
               "HOME": isolated_home}
        p = subprocess.run([sys.executable, "-m", "review_plan_v2", *args],
                           capture_output=True, text=True, env=env, timeout=30)
        return p.stdout, p.stderr, p.returncode
    finally:
        shutil.rmtree(isolated_home, ignore_errors=True)


class CliFlagTests(unittest.TestCase):
    def test_help_exits_zero(self):
        stdout, _stderr, rc = _bare_run("--help")
        self.assertEqual(rc, 0)
        self.assertIn("review-plan-v2", stdout)
        self.assertIn("--plain", stdout)
        self.assertIn("--base", stdout)
        self.assertIn("--type", stdout)
        self.assertIn("--agent", stdout)

    def test_version_exits_zero(self):
        stdout, _, rc = _bare_run("--version")
        self.assertEqual(rc, 0)
        self.assertIn("review-plan-v2", stdout)

    def test_unknown_flag_exits_two(self):
        # argparse exits 2 on unknown flag (matches contracts/cli-flags.md "tool error" tier)
        _, _, rc = _bare_run("--nonsense-flag")
        self.assertEqual(rc, 2)

    def test_type_choices_enforced(self):
        _, stderr, rc = _bare_run("--type", "weird")
        self.assertEqual(rc, 2)
        self.assertIn("invalid choice", stderr.lower())


class AgentModeTests(unittest.TestCase):
    def setUp(self):
        self.server = FixtureServer()
        self.base_url = self.server.start()
        self.repo = make_repo_from_diff(FIXTURE_01)

    def tearDown(self):
        self.server.stop()
        cleanup_repo(self.repo)

    def test_agent_mode_emits_ndjson(self):
        result = run_v2(
            "--agent", "--base", "main", "--no-static-analyzers",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="01-clean",
            timeout=120,
        )
        self.assertEqual(result.exit_code, 0)
        import json
        nonblank = [ln for ln in result.stdout.splitlines() if ln.strip()]
        self.assertTrue(nonblank, msg=f"agent mode produced no stdout: stderr={result.stderr}")
        parsed = json.loads(nonblank[-1])
        self.assertEqual(parsed.get("type"), "summary")


if __name__ == "__main__":
    unittest.main()
