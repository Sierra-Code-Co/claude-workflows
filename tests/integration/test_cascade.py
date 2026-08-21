"""Cascade dispatch — DeepSeek (broad) + OpenAI/Google (cascade) on high-risk paths.

Anthropic was dropped from the default cascade — anti-self-grading on Claude-written
code (operator works in Claude Code as the implementation model). See orchestrator.py:
cascade is now { openai, google } gated on per-provider env vars.
"""
from __future__ import annotations

import json
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


class CascadeTests(unittest.TestCase):
    """OpenAI is detected by `model: gpt-*` in the request body (collides with
    DeepSeek on the /v1/chat/completions URL — disambiguated by body inspection).
    Google is detected by /v1beta/models/{model}:generateContent path. The
    fixture server re-wraps fixture content into the requesting provider's
    response shape, so a single fixture file authored in (e.g.) DeepSeek's
    shape serves all four providers."""

    def setUp(self):
        self.server = FixtureServer()
        self.base_url = self.server.start()
        self.repo = make_repo_from_diff(FIXTURES / "05-cascade-trigger.diff")
        # Configure high-risk path matching the auth file in the diff
        (self.repo / ".review-plan-v2.yaml").write_text(
            "high_risk_paths:\n  - path: 'src/lib/auth/**'\n    reason: 'auth code'\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.server.stop()
        cleanup_repo(self.repo)

    def test_cascade_invokes_openai_and_google_on_high_risk(self):
        result = run_v2(
            "--agent", "--base", "main", "--no-static-analyzers",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="05-cascade-trigger",
            env_extra={
                "OPENAI_API_KEY": "test-key",
                "OPENAI_API_BASE": self.base_url,
                "GEMINI_API_KEY": "test-key",
                "GOOGLE_API_BASE": self.base_url,
            },
            timeout=120,
        )
        self.assertIn(result.exit_code, (0, 1), msg=f"stderr={result.stderr}\nstdout={result.stdout}")
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        self.assertTrue(lines, msg=f"agent mode produced no stdout: stderr={result.stderr}")
        summary = json.loads(lines[-1])
        called = {p["provider"]: p for p in summary.get("providers_called", [])}
        self.assertIn("openai", called, msg=f"providers_called: {summary.get('providers_called')}")
        self.assertIn("google", called, msg=f"providers_called: {summary.get('providers_called')}")
        self.assertIn("deepseek", called)
        # Anthropic is intentionally NOT in the default cascade anymore.
        self.assertNotIn("anthropic", called)

        # Dialing is not answering. Until 2026-08-13 this test asserted only
        # membership in `providers_called` — an ATTEMPT counter — so it passed
        # every day from 2026-05-09 while the OpenAI leg returned HTTP 400 to
        # all 136 calls it ever made. A cascade that contributes nothing is the
        # failure this test exists to catch, so assert on `succeeded`.
        for provider, entry in called.items():
            self.assertEqual(
                entry["failed"], 0,
                msg=f"'{provider}' leg reported failures: {entry}; stderr={result.stderr}",
            )
            self.assertGreater(
                entry["succeeded"], 0,
                msg=f"'{provider}' leg was called but never answered: {entry}; stderr={result.stderr}",
            )

    def test_no_cascade_flag_disables_frontier_cascade(self):
        result = run_v2(
            "--agent", "--base", "main", "--no-static-analyzers", "--no-cascade",
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="05-cascade-trigger",
            env_extra={
                "OPENAI_API_KEY": "test-key",
                "OPENAI_API_BASE": self.base_url,
                "GEMINI_API_KEY": "test-key",
                "GOOGLE_API_BASE": self.base_url,
            },
            timeout=120,
        )
        self.assertIn(result.exit_code, (0, 1), msg=f"stderr={result.stderr}\nstdout={result.stdout}")
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        self.assertTrue(lines, msg=f"agent mode produced no stdout: stderr={result.stderr}")
        summary = json.loads(lines[-1])
        providers = {p["provider"] for p in summary.get("providers_called", [])}
        self.assertNotIn("openai", providers)
        self.assertNotIn("google", providers)


if __name__ == "__main__":
    unittest.main()
