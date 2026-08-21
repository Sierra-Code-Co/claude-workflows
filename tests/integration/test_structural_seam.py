"""The seam between StructuralAnalyzer and the report (T021a, US3).

Direct execution needs `tests/` on the path; pytest supplies it and nothing
else does. Without this the `__main__` guard below is a promise the file
cannot keep (T005i-b).
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from support.runner import run_v2  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

# A file that violates `raw-caught-to-logger` AND sits inside the rule's
# `files:` scope. Both halves matter: the rule's first real-world hit was
# correct code, and a violation at an out-of-scope path proves nothing — that
# is the exact mistake that left this rule's own fixture unmatched for a month.
VIOLATION_PATH = "src/lib/server/handler.ts"
# `console.error`, NOT `logger.error`. My first draft used logger and the rule
# does not match it — deliberately, since `\.(error|warn|log)$` alone would flag
# every logger in a repo, so the rule anchors on `^console\.`. Verified against
# ast-grep directly (1 match) BEFORE relying on it here, because the integration
# test cannot tell "the seam is broken" from "my fixture was never a violation".
VIOLATION = """\
export async function handler() {
  try {
    await doWork();
  } catch (e) {
    console.error("work failed", e);
  }
}
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


def _repo_with_violation(tmp: Path, *, with_rules: bool) -> Path:
    """A real git repo whose HEAD commit adds an in-scope violating file."""
    repo = tmp / "repo"
    (repo / Path(VIOLATION_PATH).parent).mkdir(parents=True)
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("# base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "-M", "main")
    _git(repo, "checkout", "-qb", "feature")

    if with_rules:
        # The REAL rule, so the test cannot pass against a weakened copy.
        (repo / "rules").mkdir()
        (repo / "rules" / "raw-caught-to-logger.yml").write_text(
            (REPO / "rules" / "raw-caught-to-logger.yml").read_text())

    (repo / VIOLATION_PATH).write_text(VIOLATION)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add a violating handler")
    return repo


class StructuralSeamTests(unittest.TestCase):
    """`coverage_is_complete` becoming a rendered line is the untested seam.

    The unit tests cover `StructuralAnalyzer` branch by branch and SC-003 runs
    the rule against a real checkout, but nothing exercised the join: whether
    an enumerator that could not run actually SAYS so in the report a human
    reads, or whether the gap is computed and then dropped on the floor.

    Both runs use `--dry-run`-free, provider-free invocations: the structural
    wave is free and runs before any reviewer, so no fixture server is needed.
    Reviewers are disabled by pointing the providers at nothing and asserting
    only on the structural lines.
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_absent_coverage_reaches_the_rendered_report(self):
        """No rules configured -> the run must SAY completeness went unanswered.

        This is the whole US3 thesis at the seam. `coverage_is_complete` being
        False in a dataclass helps nobody if the renderer never prints it: the
        operator would see a clean report from a run where the completeness
        question was never asked.
        """
        repo = _repo_with_violation(self.tmp, with_rules=False)
        result = run_v2("--plain", "--base", "main", "--dry-run",
                        cwd=repo, timeout=120)
        # --dry-run stops before reviewers but after the analyzer wave decision,
        # so re-run without it for the full path.
        result = run_v2("--plain", "--base", "main",
                        cwd=repo, timeout=180,
                        env_extra={"DEEPSEEK_API_KEY": "", "ANTHROPIC_API_KEY": "",
                                   "OPENAI_API_KEY": "", "GOOGLE_API_KEY": ""})
        out = result.stdout + result.stderr
        self.assertIn("NO-STRUCTURAL-COVERAGE", out,
                      msg=f"absent coverage never reached the report:\n{out[:2000]}")
        self.assertIn("no structural rules configured", out)

    def test_a_structural_finding_reaches_the_rendered_report(self):
        """Anti-vacuous control, and the half that proves the seam carries
        SIGNAL as well as gaps. A wiring that emitted the banner unconditionally
        would satisfy the test above while never reporting a real violation."""
        repo = _repo_with_violation(self.tmp, with_rules=True)
        result = run_v2("--plain", "--base", "main",
                        cwd=repo, timeout=180,
                        env_extra={"DEEPSEEK_API_KEY": "", "ANTHROPIC_API_KEY": "",
                                   "OPENAI_API_KEY": "", "GOOGLE_API_KEY": ""})
        # Anchored on the FINDING LINE, not on the rule id anywhere in the
        # output. The first version searched stdout+stderr for
        # "raw-caught-to-logger" and passed against a run that found NOTHING —
        # the string matched a stderr warning naming the rule FILE PATH
        # (`reviewer task security:rules/raw-caught-to-logger.yml failed`).
        # A selector that can match a record you did not mean is the third
        # instance of that trap in this repo.
        finding_lines = [ln for ln in result.stdout.splitlines()
                         if VIOLATION_PATH in ln and "[raw-caught-to-logger]" in ln]
        self.assertTrue(
            finding_lines,
            msg=("the structural finding never reached stdout as a finding.\n"
                 f"stdout:\n{result.stdout[:1500]}"))
        self.assertNotIn("No findings.", result.stdout,
                         msg="the report claimed a clean run while a rule matched")


if __name__ == "__main__":
    unittest.main()
