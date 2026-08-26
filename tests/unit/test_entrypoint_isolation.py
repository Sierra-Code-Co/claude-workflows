"""The working directory of a review is untrusted, and it must not be importable.

`python -m review_plan_v2` inserts the CURRENT WORKING DIRECTORY at `sys.path[0]`,
ahead of every PYTHONPATH entry. `scripts/review-plan-v2.sh` exec'd exactly that
until 2026-08-25, and it does not `cd` anywhere, so cwd is normally the root of
the repository being reviewed. Reviewing a repository is the definition of not
trusting its contents, and the wrapper exports every provider API key into the
environment about forty lines before the exec. A branch carrying
`review_plan_v2/__init__.py` at its root therefore got arbitrary code execution
with the credentials already loaded, triggered by someone running a review on it.

The fix is to exec a FILE by absolute path (`scripts/rpv2_entry.py`), which is
the one invocation mode that makes `sys.path[0]` the script's own directory
instead of cwd. `-P` / `PYTHONSAFEPATH` would also close it, but only from 3.11,
and `check_deps.MIN_PYTHON` is 3.10 — a guard absent on the floor version itself.

Across the two classes below, the load-bearing test is the one showing the
shadowing is REAL against the old invocation: without it, "the wrapper printed its
version" is just a wrapper that works. The hostile package here is inert (it writes a marker
file and exits 0) because a test that proves exfiltration is possible does not
need to perform it.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
WRAPPER = SCRIPTS / "review-plan-v2.sh"

#: What the hostile package writes if it is ever imported. A file rather than
#: stdout: stdout can be swallowed by a parser, and the point is that code RAN.
MARKER = "hijacked.txt"

_HOSTILE = (
    "import os, pathlib, sys\n"
    "pathlib.Path(os.environ.get('SHADOW_MARKER', 'hijacked.txt')).write_text(\n"
    "    'imported with %d env vars in scope' % len(os.environ), encoding='utf-8')\n"
    "print('HIJACKED', file=sys.stderr)\n"
    "raise SystemExit(0)\n"
)


def _hostile_cwd(td: str) -> Path:
    """A directory that shadows the real package if cwd is on sys.path."""
    cwd = Path(td) / "untrusted-repo"
    (cwd / "review_plan_v2").mkdir(parents=True)
    (cwd / "review_plan_v2" / "__init__.py").write_text(_HOSTILE, encoding="utf-8")
    return cwd


def _env(cwd: Path) -> dict:
    env = dict(os.environ)
    env["SHADOW_MARKER"] = str(cwd / MARKER)
    # A developer's ambient PYTHONPATH would make the outcome depend on their
    # shell rather than on the invocation being tested.
    env.pop("PYTHONPATH", None)
    # PYTHONSAFEPATH for the same reason, and it matters most for the ANTI-VACUITY
    # control below. That test proves the old `-m` invocation really was
    # exploitable, and it works by relying on `-m` putting cwd at sys.path[0].
    # PYTHONSAFEPATH=1 is precisely what turns that off, so on the machine of
    # anyone who exports it — someone being careful — the control would fail and
    # report a defect that is not there, while the fix it guards is fine. A check
    # whose result depends on the checker's shell proves nothing either way.
    env.pop("PYTHONSAFEPATH", None)
    return env


class TheWrapperDoesNotImportFromTheReviewedRepo(unittest.TestCase):
    def test_a_package_named_like_ours_in_the_cwd_is_not_imported(self):
        with tempfile.TemporaryDirectory() as td:
            cwd = _hostile_cwd(td)
            proc = subprocess.run(
                ["bash", str(WRAPPER), "--version"],
                capture_output=True, text=True, timeout=120,
                env=_env(cwd), cwd=str(cwd),
            )
            hijacked = (cwd / MARKER).exists()

        self.assertFalse(
            hijacked,
            msg="the reviewed repository's review_plan_v2/__init__.py executed — "
                "cwd is on sys.path and every provider key is already exported",
        )
        self.assertNotIn("HIJACKED", proc.stderr)
        # The real tool answered, so the isolation is not "nothing ran".
        self.assertEqual(proc.returncode, 0, msg=f"stderr={proc.stderr}")
        self.assertIn("review-plan-v2", proc.stdout)

    def test_the_old_invocation_really_was_shadowed(self):
        """Anti-vacuity control, and the reason this file is not just a
        restatement of `--version` working.

        Same hostile directory, invoked the way the wrapper used to invoke it. If
        this does NOT get hijacked then `-m` never put cwd first on this
        interpreter, the finding was theoretical, and the test above is asserting
        nothing about the change that was made.
        """
        with tempfile.TemporaryDirectory() as td:
            cwd = _hostile_cwd(td)
            env = _env(cwd)
            env["PYTHONPATH"] = str(SCRIPTS)
            proc = subprocess.run(
                [sys.executable, "-m", "review_plan_v2", "--version"],
                capture_output=True, text=True, timeout=120, env=env, cwd=str(cwd),
            )
            hijacked = (cwd / MARKER).exists()

        self.assertTrue(
            hijacked,
            msg=f"`-m` did not import the cwd package, so the test above proves "
                f"nothing about the fix: stdout={proc.stdout} stderr={proc.stderr}",
        )
        self.assertIn("HIJACKED", proc.stderr)
        self.assertNotIn("review-plan-v2", proc.stdout)

    def test_the_wrapper_does_not_exec_dash_m(self):
        """Source-text backstop, narrow on purpose.

        The behavioural test above can only fail once someone plants a package;
        this catches the revert itself, in the diff that makes it. The two
        together are the pattern `test_the_wrapper_no_longer_execs_an_unchecked_python`
        already uses for the interpreter floor, for the same reason: a behavioural
        assertion about an attack and a textual assertion about the invocation
        fail on different mistakes.
        """
        text = WRAPPER.read_text(encoding="utf-8")
        offenders = [
            line for line in text.splitlines()
            if line.strip().startswith("exec ") and " -m " in line
        ]
        self.assertEqual(
            offenders, [],
            msg=f"the wrapper execs `-m`, which puts the reviewed repository's "
                f"root first on sys.path: {offenders}",
        )
        self.assertIn('rpv2_entry.py', text)
        self.assertTrue((SCRIPTS / "rpv2_entry.py").exists())


class TheWrapperNeverPutsAnEmptyEntryOnPythonpath(unittest.TestCase):
    """An empty PYTHONPATH entry means the CURRENT WORKING DIRECTORY.

    A review round argued the entrypoint was still exploitable because the
    wrapper "prepends to an empty PYTHONPATH, leaving a trailing `:`". It does
    not — it writes `${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}`, and the `:+`
    is the whole reason the claim is false. That is a one-character load-bearing
    detail defended by nothing but a comment, and `a:b` is the obvious
    simplification for anyone who has not been bitten. So the invariant is
    asserted rather than reasoned about, and if someone does simplify it, this
    fails instead of the finding becoming true.

    The same defect has already shipped once in this repo, in the test harness
    rather than the wrapper: `run_v2` built PYTHONPATH by concatenation, and with
    the var unset every test subprocess got the FIXTURE REPO on its sys.path.
    tests/support/runner.py carries the fix and the note.

    The BEHAVIOURAL half of this is already covered, which is worth saying because
    it is why the finding was refusable rather than merely unproven:
    `test_a_package_named_like_ours_in_the_cwd_is_not_imported` runs with
    PYTHONPATH popped, which is exactly the empty-value case the claim was about,
    and the hostile package is not imported. What was missing is a test that fails
    if the `:+` is simplified away, plus the ambient-value case below.
    """

    def test_the_wrapper_source_uses_the_conditional_prefix(self):
        """Asserted on the SOURCE, not on a resolved value.

        The wrapper `exec`s, so there is no clean way to read the value it
        exported without either shimming the interpreter it picks (an absolute
        path into the repo's own venv, so not shimmable from PATH) or truncating a
        copy of the script. A value read under whatever PYTHONPATH the test host
        happens to export would also only prove the case that host is in. The
        spelling is the invariant, and it is the thing a well-meaning
        simplification would break.
        """
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("${PYTHONPATH:+:${PYTHONPATH}}", text,
                      msg="the wrapper no longer guards against an empty PYTHONPATH "
                          "entry; an empty entry means cwd, which is the untrusted "
                          "repository under review")
        offenders = [
            (i, ln) for i, ln in enumerate(text.splitlines(), 1)
            if "PYTHONPATH" in ln and ":${PYTHONPATH}" in ln
            and "${PYTHONPATH:+" not in ln
        ]
        self.assertEqual(offenders, [], msg=f"unguarded PYTHONPATH join: {offenders}")

    def test_a_hostile_cwd_is_not_imported_even_with_an_ambient_pythonpath(self):
        """The case the sibling test cannot reach, since it pops the var.

        A non-empty ambient PYTHONPATH is the normal state for anyone running this
        tool from a shell that sets one, and it is the branch where the wrapper
        actually performs the join. The reviewed repo must still not be importable.
        """
        with tempfile.TemporaryDirectory() as td:
            cwd = _hostile_cwd(td)
            env = _env(cwd)
            env["PYTHONPATH"] = str(Path(td) / "ambient-entry")
            proc = subprocess.run(
                ["bash", str(WRAPPER), "--version"],
                capture_output=True, text=True, timeout=120, env=env, cwd=str(cwd),
            )
            self.assertFalse(
                (cwd / MARKER).exists(),
                msg=f"the reviewed repo's package was imported: stderr={proc.stderr[-800:]}",
            )
            self.assertNotIn("HIJACKED", proc.stderr)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
