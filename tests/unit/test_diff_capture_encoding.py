"""A diff that is not valid UTF-8 must be reviewable, not a traceback.

git decides what is "text" by looking for NUL bytes, so a latin-1 file, or a
partially-binary one that happens to contain no NUL, gets a normal textual diff
that cannot be decoded as UTF-8. `_git` ran `subprocess.run(..., text=True)`
with the default strict decode, so that diff raised UnicodeDecodeError from
inside `subprocess.communicate` — before any reviewer ran.

Two things made that worse than a crash, and they are what these tests pin:

  1. It escaped as an unhandled exception, so the process exited 1 — the SAME
     code as "reviewed the diff and found actionable findings". A total failure
     to look was indistinguishable from a substantive result, which is this
     repo's recurring defect shape rather than a new one.
  2. The message named a byte offset in a decoded stream, so nothing in the
     output said which path caused it.

Found by running the tool on a repo whose only change was a partial PNG. The fix
(`errors="replace"`) shipped without a test, which a review then flagged: a fix
whose regression is invisible is the same category of problem as the bug.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from review_plan_v2 import diff_capture

#: 0x89 is the first byte of a PNG signature and is not a valid UTF-8 start
#: byte. Chosen because a partial PNG is exactly how this was found, and because
#: the file must contain NO NUL byte or git would call it binary and never
#: produce the textual diff that triggers the bug.
INVALID_UTF8 = b"header\x89\xfe\xffmore text after the bad bytes\n"


def _repo_with_an_undecodable_change(tmp: Path) -> None:
    """A two-commit repo whose second commit adds non-UTF-8 text content."""
    run = lambda *a: subprocess.run(  # noqa: E731
        a, cwd=tmp, check=True, capture_output=True)
    run("git", "init", "-q", ".")
    run("git", "config", "user.email", "t@example.invalid")
    run("git", "config", "user.name", "T")
    (tmp / "clean.txt").write_text("baseline\n", encoding="utf-8")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "base")
    (tmp / "odd.dat").write_bytes(INVALID_UTF8)
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "add undecodable content")


class TheHarnessReproducesTheCondition(unittest.TestCase):
    """Anti-vacuity: if git calls the file binary, every test below is a no-op.

    Written first because the whole scenario depends on a fact about git that
    this suite does not control. A future git that treats these bytes as binary
    would make the tests below pass while exercising nothing, which is the
    failure mode this file exists to talk about.
    """

    def test_git_produces_a_textual_diff_with_undecodable_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _repo_with_an_undecodable_change(tmp)
            raw = subprocess.run(
                ["git", "diff", "--no-ext-diff", "-M", "HEAD~1...HEAD", "--", "odd.dat"],
                cwd=tmp, check=True, capture_output=True,
            ).stdout
        self.assertNotIn(b"Binary files", raw,
                         msg="git called it binary, so this scenario no longer reproduces")
        self.assertIn(b"\x89", raw, msg="the undecodable byte did not survive into the diff")
        with self.assertRaises(UnicodeDecodeError):
            raw.decode("utf-8")


class AnUndecodableDiffIsCapturedNotRaised(unittest.TestCase):
    def test_capture_diff_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _repo_with_an_undecodable_change(tmp)
            # The assertion is that this does not raise. Stated explicitly
            # because a bare call reads as setup rather than as the check.
            try:
                diff = diff_capture.capture_diff("HEAD~1", cwd=str(tmp))
            except UnicodeDecodeError as e:
                self.fail(f"capture_diff raised on a non-UTF-8 diff: {e}")
        paths = {f.path for f in diff.files}
        self.assertIn("odd.dat", paths, msg=f"the offending file was dropped: {paths}")

    def test_the_undecodable_bytes_become_replacement_characters(self):
        """Replacement, not omission. A reviewer reading U+FFFD where a bad byte
        was still reviews the rest of the file; silently dropping the line would
        hand it a diff that differs from the one on disk."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _repo_with_an_undecodable_change(tmp)
            diff = diff_capture.capture_diff("HEAD~1", cwd=str(tmp))
        odd = next(f for f in diff.files if f.path == "odd.dat")
        self.assertIn("�", odd.diff_text)
        # The decodable text around the bad bytes must survive, or "replace"
        # would be no better than discarding the file.
        self.assertIn("more text after the bad bytes", odd.diff_text)

    def test_a_clean_file_in_the_same_diff_is_unaffected(self):
        """The blast radius is one file, not the run. `errors="replace"` applies
        to the whole subprocess stream, so this pins that ordinary files are not
        quietly mangled by the setting that rescues the odd one."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _repo_with_an_undecodable_change(tmp)
            (tmp / "clean.txt").write_text("baseline\nplus a line\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=tmp, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-q", "-m", "touch clean"],
                           cwd=tmp, check=True, capture_output=True)
            diff = diff_capture.capture_diff("HEAD~2", cwd=str(tmp))
        clean = next(f for f in diff.files if f.path == "clean.txt")
        self.assertNotIn("�", clean.diff_text)
        self.assertIn("plus a line", clean.diff_text)


class TheExitCodeDistinguishesFailureFromFindings(unittest.TestCase):
    """The half that made this worth fixing rather than logging.

    Asserted at the process level, not by inspecting `_git`: the defect was that
    an exception escaped all the way out and the SHELL saw 1, which no
    unit-level assertion about decoding can express. 1 means "found actionable
    findings" in this tool's contract, so a crash exiting 1 is a crash wearing a
    review's clothes.
    """

    def test_the_module_does_not_exit_1_on_an_undecodable_diff(self):
        scripts = Path(__file__).resolve().parents[2] / "scripts"
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _repo_with_an_undecodable_change(tmp)
            proc = subprocess.run(
                [sys.executable, "-m", "review_plan_v2", "--plain", "--base", "HEAD~1"],
                cwd=tmp, capture_output=True, text=True, timeout=180,
                # No provider keys: the run must refuse for THAT reason (2), and
                # the point is that it reaches the refusal at all instead of
                # dying in diff capture. Keys are stripped rather than trusted to
                # be absent, so the test does not depend on the operator's shell.
                env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(scripts),
                     "HOME": str(tmp), "REVIEW_PLAN_V2_LOG_DIR": str(tmp / "logs")},
            )
        self.assertNotIn("UnicodeDecodeError", proc.stderr,
                         msg=f"stderr={proc.stderr[-1500:]}")
        self.assertNotIn("Traceback", proc.stderr, msg=f"stderr={proc.stderr[-1500:]}")
        # Assert the exit code the docstring above actually claims — 2, the
        # no-provider-key refusal — not merely "not 1". `assertNotEqual(rc, 1)`
        # passed on 0 as well, and 0 means the run finished cleanly without ever
        # reaching the refusal, which would leave this test green on a build where
        # diff capture silently produced nothing to review. It also passed on any
        # unrelated 2, so it proved neither that capture completed nor that the
        # refusal was the reason. Both halves are named below.
        self.assertEqual(
            proc.returncode, 2,
            msg="expected the no-provider-key refusal (2): 1 would mean a "
                "diff-capture crash wearing a review's clothes, and 0 would mean "
                f"the run never reached the refusal. stderr={proc.stderr[-1500:]}",
        )
        # And that it refused for THAT reason. Without this, any other exit-2 tool
        # error satisfies the check above while diff capture stayed broken.
        self.assertIn(
            "DEAD-LEG", proc.stderr,
            msg=f"exit 2 must be the missing-key refusal. stderr={proc.stderr[-1500:]}",
        )


if __name__ == "__main__":
    unittest.main()
