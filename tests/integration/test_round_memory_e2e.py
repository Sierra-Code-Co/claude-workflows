"""Round memory across two real runs (T048, #20).

The unit tests prove `rounds.partition` decides correctly. They cannot prove the
orchestrator asks it, or that the state survives a process exit — and "the logic
is right but nothing calls it" is the shape that made T047 a four-times-a-session
false positive.

So these drive the real CLI twice against the same repository, with the state
file persisted between them, and assert on what the second run prints.

Both directions are covered, because they fail in opposite ways: a memory that
suppresses too eagerly hides a finding the developer ignored, and one that never
suppresses is a feature that does nothing while appearing to be implemented.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from support.fixture_server import FixtureServer
from support.runner import cleanup_repo, run_v2


FINDING_LINE = 3

#: The scenario fixture returns ONE stable actionable finding on src/sdk.ts:3 to
#: every reviewer on every run, so any difference between round 1 and round 2 is
#: the memory and not the model. Checked in at
#: tests/fixtures/responses/06-round-memory/.

BEFORE = "export function f(code: string) {\n\tif (code) {\n\t\treturn 'user-cancelled';\n\t}\n\treturn '';\n}\n"
AFTER = "export function f(code: string) {\n\tif (code) {\n\t\treturn 'UserCancelled';\n\t}\n\treturn '';\n}\n"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class RoundMemoryE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = FixtureServer()
        cls.base_url = cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="rpv2-round-repo-"))
        self.state = Path(tempfile.mkdtemp(prefix="rpv2-round-state-")) / "state.json"
        (self.repo / "src").mkdir()
        _git("init", "-q", "-b", "main", cwd=self.repo)
        _git("config", "user.email", "t@example.com", cwd=self.repo)
        _git("config", "user.name", "T", cwd=self.repo)
        (self.repo / "src" / "sdk.ts").write_text("// placeholder\n")
        _git("add", "-A", cwd=self.repo)
        _git("commit", "-q", "-m", "base", cwd=self.repo)
        _git("checkout", "-q", "-b", "feature", cwd=self.repo)
        (self.repo / "src" / "sdk.ts").write_text(BEFORE)
        _git("add", "-A", cwd=self.repo)
        _git("commit", "-q", "-m", "round 1", cwd=self.repo)

    def tearDown(self):
        cleanup_repo(self.repo)

    def _run(self, force_full: bool = False):
        # `--auto-pause-n 99` keeps auto-pause out of the way: these runs are
        # deliberately repetitive, which is exactly what auto-pause exists to
        # stop, and a paused run would print no findings for an unrelated reason.
        args = ["--plain", "--base", "main", "--no-static-analyzers", "--no-verify",
                "--auto-pause-n", "99"]
        if force_full:
            args.append("--force-full")
        return run_v2(
            *args,
            cwd=self.repo, fixture_base_url=self.base_url, fixture_name="06-round-memory",
            env_extra={"REVIEW_PLAN_V2_STATE_FILE": str(self.state)}, timeout=180,
        )

    def _amend_flagged_lines(self):
        (self.repo / "src" / "sdk.ts").write_text(AFTER)
        _git("add", "-A", cwd=self.repo)
        _git("commit", "-q", "-m", "round 2: address it", cwd=self.repo)

    def test_round_one_shows_the_finding(self):
        """Anti-vacuous control. Every assertion below is about round 2, and
        "the finding never appeared at all" satisfies a `not in` check."""
        out = self._run().stdout
        self.assertIn("kebab-case", out, msg=out)

    def test_round_two_suppresses_it_once_the_flagged_code_changed(self):
        first = self._run()
        self.assertIn("kebab-case", first.stdout)
        self._amend_flagged_lines()
        second = self._run()
        # The banner alone proves nothing: it renders from the summary, so it
        # prints even if the filtered list is never used. Mutating
        # `_render_and_print(visible, …)` back to `merged` left this test green
        # until the absence check below existed.
        #
        # The check is on the rendered FINDING form, not on the message text: the
        # banner deliberately quotes the message (named, not counted), so a bare
        # `assertNotIn("kebab-case")` asserts the opposite of the design and
        # fails against correct code. It did.
        self.assertNotIn("[ACTIONABLE]", second.stdout,
                         msg=f"the finding was still rendered as a finding:\n{second.stdout}")
        self.assertIn("No findings.", second.stdout)
        self.assertIn("[ROUND-MEMORY]", second.stdout, msg=second.stdout)
        self.assertIn("src/sdk.ts:3", second.stdout)
        self.assertIn("--force-full", second.stdout)

    def test_round_two_still_shows_it_when_the_code_was_NOT_touched(self):
        """The dangerous direction. A developer who ignores a finding must keep
        seeing it — otherwise running the tool twice is a way to make a real
        problem disappear."""
        self._run()
        # No edit to the flagged lines; a new file elsewhere so the diff differs.
        (self.repo / "src" / "unrelated.ts").write_text("export const x = 1;\n")
        _git("add", "-A", cwd=self.repo)
        _git("commit", "-q", "-m", "unrelated", cwd=self.repo)
        second = self._run()
        self.assertIn("kebab-case", second.stdout, msg=second.stdout)
        self.assertNotIn("[ROUND-MEMORY]", second.stdout)

    def test_force_full_recovers_a_suppressed_finding(self):
        """The escape hatch is what makes suppression honest.

        The intermediate run matters: without establishing that the finding IS
        suppressed first, this passes when suppression is broken entirely, since
        a never-suppressed finding is trivially "recovered". Reported by review.
        """
        self._run()
        self._amend_flagged_lines()
        suppressed_run = self._run()
        self.assertIn("[ROUND-MEMORY]", suppressed_run.stdout,
                      msg="nothing was suppressed, so recovery proves nothing")

        recovered = self._run(force_full=True)
        self.assertIn("[ACTIONABLE]", recovered.stdout, msg=recovered.stdout)
        self.assertIn("kebab-case", recovered.stdout)
        self.assertNotIn("[ROUND-MEMORY]", recovered.stdout)

    def test_a_force_full_run_does_not_break_later_suppression(self):
        """--force-full bypasses the filter for one run and nothing more.

        Review of this change predicted the opposite — that displaying a finding
        under --force-full overwrites its preserved anchor and un-suppresses it
        for good. Measured against the code: it does not. `partition` selects the
        record with the lowest `first_round`, so the original anchor governs even
        when a newer row exists.

        The test is kept as a REGRESSION guard rather than as evidence of a bug:
        the property it pins is real and load-bearing, but it is currently
        protected by the selection rule rather than by the dedup, so no mutation
        of the dedup can make it fail. That is recorded in the proof file instead
        of being papered over with a mutation that would falsely report
        "detected".
        """
        self._run()
        self._amend_flagged_lines()
        self._run()                      # suppressed
        self._run(force_full=True)       # displayed, history must be untouched
        after = self._run()
        self.assertIn("[ROUND-MEMORY]", after.stdout,
                      msg=f"--force-full rewrote the history:\n{after.stdout}")
        self.assertNotIn("[ACTIONABLE]", after.stdout)

    def test_the_state_file_records_no_message_text(self):
        """FR-015: the persisted file carries hashes, never finding bodies."""
        self._run()
        blob = self.state.read_text()
        self.assertNotIn("kebab-case", blob)
        self.assertIn("finding_history", blob)
