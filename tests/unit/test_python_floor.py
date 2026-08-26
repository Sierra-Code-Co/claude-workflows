"""The declared Python floor is enforced on both invocation paths, and is one number.

`pyproject.toml` has declared `requires-python = ">=3.10"` since the package was
created. Nothing enforced it. `scripts/review-plan-v2.sh` exec'd bare `python3`,
which on macOS is /usr/bin/python3 = 3.9.6, so every run of the tool on a Mac was
one minor version below its own floor. `check_deps.py` did carry a version guard,
but `grep -rn check_deps scripts/review_plan_v2/*.py` matched only check_deps
itself — nothing imported it, so the guard ran only when a human typed
`python3 -m review_plan_v2.check_deps` by hand.

The reason this mattered before anything visibly broke: `tests/conftest.py`
refuses to COLLECT below 3.10, so 3.9 was the one interpreter the suite never
exercised, and it was the interpreter actually shipping. A 3.10-ism reaches a
user before it reaches a test. One already had — concurrency.py's
`_TIMEOUT_ERRORS`, where `concurrent.futures.TimeoutError` is not the builtin
below 3.11, silently disabled a deadline branch and surfaced as four
"concurrency flakes".

So there are three claims here, and each is tested against behaviour rather than
against source text:

  1. The floor is ONE number. check_deps.MIN_PYTHON is parsed against
     pyproject's `requires-python`, so raising one and forgetting the other
     fails here instead of making the guard quietly weaker than the declaration.
  2. The shell wrapper refuses when no interpreter meets the floor, and finds
     one when it can. Exercised by running the real script under a PATH that
     offers only 3.9.
  3. `python3 -m review_plan_v2` refuses too. That is the documented invocation
     for CI and the Dockerfile, and a guard that covered only the wrapper would
     leave it open — which is the shape of the original dead guard.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
WRAPPER = SCRIPTS / "review-plan-v2.sh"
PYPROJECT = REPO / "pyproject.toml"

sys.path.insert(0, str(SCRIPTS))

from review_plan_v2 import check_deps  # noqa: E402

#: A PATH offering exactly one python3, below the floor. /usr/bin/python3 is
#: 3.9.6 on macOS and no python3.1x lives there, so this needs no fake shim —
#: the refusal is proven against a real too-old interpreter. /bin is included
#: for the externals the wrapper calls before it ever looks for python.
OLD_ONLY_PATH = "/usr/bin:/bin"

#: Every version string below is DERIVED from check_deps.MIN_PYTHON, never typed.
#: The first draft hardcoded "3.9.6" and `>= (3, 10)`, which makes this file a
#: second declaration of the floor — the exact duplication `TheFloorIsOneNumber`
#: exists to forbid between check_deps and pyproject. Raising the floor to 3.11
#: would leave a test asserting the 3.9 message and a probe still admitting 3.10,
#: and both would keep passing while checking the wrong number.
FLOOR = ".".join(str(p) for p in check_deps.MIN_PYTHON)
#: A concrete below-floor version: one minor below the floor, with a patch so the
#: rendered string exercises the three-component path in the refusal message.
BELOW_FLOOR = (check_deps.MIN_PYTHON[0], check_deps.MIN_PYTHON[1] - 1, 6)
BELOW_FLOOR_STR = ".".join(str(p) for p in BELOW_FLOOR)
#: `python3.<floor>` upward. Ten minors ahead is arbitrary but generous; the
#: point is that the list moves with the floor instead of naming today's releases.
ABOVE_FLOOR_BINARIES = tuple(
    f"python{check_deps.MIN_PYTHON[0]}.{minor}"
    for minor in range(check_deps.MIN_PYTHON[1], check_deps.MIN_PYTHON[1] + 10)
)


def _only_old_python_available() -> bool:
    """True if OLD_ONLY_PATH really offers a python3 below the floor and nothing above.

    Without this the two wrapper tests would be vacuous on any machine whose
    /usr/bin holds a modern python3 (a Linux CI image, most obviously): the
    "refuses" test would fail for the right reason but the wrong cause, and
    skipping is the honest answer rather than asserting on a premise that does
    not hold.
    """
    for cand in ABOVE_FLOOR_BINARIES:
        if shutil.which(cand, path=OLD_ONLY_PATH):
            return False
    found = shutil.which("python3", path=OLD_ONLY_PATH)
    if not found:
        return False
    probe = subprocess.run(
        [found, "-c",
         f"import sys; raise SystemExit(0 if sys.version_info >= "
         f"{check_deps.MIN_PYTHON!r} else 1)"],
        capture_output=True,
    )
    return probe.returncode == 1


HAVE_OLD_ONLY = _only_old_python_available()


def _runnable_wrapper_copy(td: str) -> Path:
    """A copy of the wrapper outside the repo that can still succeed.

    Copied for the reason the older test documents: `$SCRIPT_DIR/../.venv/bin/python`
    is an ABSOLUTE candidate, so PATH cannot mask it, and running the in-repo script
    would find the repo's own 3.13 venv no matter what PATH offers.

    Runnable, though, which the older test's bare copy is not: the wrapper now execs
    `$SCRIPT_DIR/rpv2_entry.py` (an absolute file path, so cwd is never on sys.path),
    and it exports `PYTHONPATH=$SCRIPT_DIR`. A directory holding only the .sh
    therefore fails for want of an entrypoint and a package — which is fine for a test
    that only wants the refusal, and fatal for its anti-vacuity twin, where the run
    has to be able to SUCCEED for the exit-2 case to mean anything.
    """
    fake_scripts = Path(td) / "scripts"
    fake_scripts.mkdir()
    copy = fake_scripts / WRAPPER.name
    copy.write_text(WRAPPER.read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copy2(SCRIPTS / "rpv2_entry.py", fake_scripts / "rpv2_entry.py")
    # Symlinked, not copied: a copy of the package would be a second one for
    # __pycache__ to fight over and would double the cost of every run of this file.
    (fake_scripts / "review_plan_v2").symlink_to(SCRIPTS / "review_plan_v2")
    return copy


def _shim_dir(td: str, body: str) -> Path:
    """A PATH directory shadowing every interpreter name the wrapper probes.

    Every name, not just `python3`: the wrapper tries explicit minors first, so
    leaving `python3.13` unshimmed lets a host's real interpreter satisfy the loop
    and the test asserts nothing about the shims.

    The probe is `"$_res" -c '...sys.version_info >= (3, 10)...'`, so a shim only has
    to be an executable with the right exit status. It does not have to be a Python,
    which is what makes this work on a host that has no below-floor interpreter at
    all — the case both `skipUnless(HAVE_OLD_ONLY)` tests below cannot cover.
    """
    d = Path(td) / "bin"
    d.mkdir()
    for name in ("python3",) + ABOVE_FLOOR_BINARIES:
        shim = d / name
        shim.write_text(body, encoding="utf-8")
        shim.chmod(0o755)
    return d


def _run_wrapper(script: Path, path: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = path
    # PYTHONPATH is set by the wrapper itself; clearing it here keeps a
    # developer's ambient value from making the module importable by accident.
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        ["bash", str(script), "--version"],
        capture_output=True, text=True, timeout=120, env=env, cwd=str(REPO),
    )


class TheFloorIsOneNumber(unittest.TestCase):
    def test_min_python_matches_pyproject_requires_python(self):
        """Parsed, not restated. `requires-python` is the declaration a user reads
        and what pip enforces at install time; MIN_PYTHON is what the runtime
        guard enforces. If they can disagree, the guard is either weaker than the
        promise (a too-old interpreter runs) or stricter (a supported one is
        refused), and neither announces itself."""
        text = PYPROJECT.read_text(encoding="utf-8")
        m = re.search(r'^requires-python\s*=\s*"(?:>=)\s*(\d+)\.(\d+)"', text, re.M)
        self.assertIsNotNone(
            m,
            msg="could not find a `requires-python = \">=X.Y\"` line in "
                "pyproject.toml. If the spelling changed, this test stops "
                "comparing anything — fix the pattern, do not delete the test.",
        )
        declared = (int(m.group(1)), int(m.group(2)))
        self.assertEqual(
            check_deps.MIN_PYTHON, declared,
            msg=f"check_deps.MIN_PYTHON is {check_deps.MIN_PYTHON} but "
                f"pyproject declares >={declared[0]}.{declared[1]}",
        )


class TheGuardFunctionIsNotVacuous(unittest.TestCase):
    def test_the_running_interpreter_passes(self):
        # conftest refuses to collect below the floor, so this must hold — and if
        # it ever does not, every other test in this file is meaningless.
        self.assertIsNone(check_deps.python_version_error())

    def test_exactly_the_floor_is_accepted(self):
        """`>=` and `>` differ on exactly one version, and it is the declared one.

        `test_the_running_interpreter_passes` above runs on whatever the developer
        has — 3.13 here — so it passes under either comparison. A `>` typo would
        reject every user sitting on the floor version the project advertises as
        supported, and nothing in this file would have gone red.

        Derived from MIN_PYTHON, not typed: the point is the boundary, not 3.10.
        """
        at_floor = (check_deps.MIN_PYTHON[0], check_deps.MIN_PYTHON[1], 0)
        with mock.patch.object(sys, "version_info", at_floor):
            self.assertIsNone(
                check_deps.python_version_error(),
                msg=f"{at_floor} is the declared floor and must be accepted; the "
                    f"guard is comparing with > rather than >=",
            )
        # Not `check() == 0` as the companion assertion: check() also inspects
        # jq/yq/git, so on a machine missing one of those this would fail for a
        # reason that has nothing to do with the version boundary.

    def test_a_below_floor_interpreter_is_refused(self):
        with mock.patch.object(sys, "version_info", BELOW_FLOOR):
            err = check_deps.python_version_error()
        self.assertIsNotNone(err, msg=f"{BELOW_FLOOR} was not refused")
        self.assertIn(BELOW_FLOOR_STR, err)
        self.assertIn(FLOOR, err)

    def test_the_message_says_untested_rather_than_merely_unsupported(self):
        """The whole reason the below-floor version was worth refusing is that the
        suite never ran on it, so a clean verdict from it was unproven rather than
        clean. A message that only says "unsupported" invites the reader to
        override it."""
        with mock.patch.object(sys, "version_info", BELOW_FLOOR):
            err = check_deps.python_version_error()
        self.assertIn("untested", err)

    def test_check_now_reaches_the_guard_it_used_to_hide(self):
        """2 (tool error), not 1.

        This asserted 1 and passed, because `check()` returned 1 — and the very
        next test in this file asserts that the `python3 -m review_plan_v2` path
        exits 2 on the same interpreter, for the reason spelled out there: 1 is
        this tool's code for "reviewed the diff, found actionable findings", so a
        broken interpreter reported as a review result is a category confusion.
        Both claims lived here at once, so the file pinned the disagreement rather
        than catching it. `check_deps.check()` now returns 2 and the assertion
        below pins the two entrypoints to ONE answer, which is the part that
        stops this drifting apart again.
        """
        with mock.patch.object(sys, "version_info", BELOW_FLOOR):
            self.assertEqual(check_deps.check(), 2)

    def test_both_entrypoints_report_the_same_interpreter_the_same_way(self):
        """One interpreter, one verdict, checked by CALLING both.

        A source grep for `return 2` was the first draft and is not worth having:
        it matches any `return 2` anywhere in the module. `main()` is cheap to
        call here because the guard runs before argparse and before the
        orchestrator import, which is the property that made the guard coverable
        in the first place.
        """
        import io

        from review_plan_v2.__main__ import main

        err = io.StringIO()
        with mock.patch.object(sys, "version_info", BELOW_FLOOR):
            with mock.patch.object(sys, "stderr", err):
                module_code = main(["--version"])
            check_code = check_deps.check()
        self.assertEqual(
            module_code, check_code,
            msg=f"`python3 -m review_plan_v2` exits {module_code} on a below-floor "
                f"interpreter and check_deps.check() returns {check_code}; the two "
                f"documented entrypoints report the same unusable interpreter as two "
                f"different kinds of outcome",
        )
        self.assertEqual(module_code, 2, msg="2 is tool error; 1 means findings")
        self.assertIn("requires Python >=", err.getvalue())


class TheModulePathIsGuarded(unittest.TestCase):
    """`python3 -m review_plan_v2` is what CI and the Dockerfile run."""

    @unittest.skipUnless(HAVE_OLD_ONLY, "no below-floor python3 in /usr/bin to test against")
    def test_running_the_module_on_an_old_interpreter_exits_2(self):
        old = shutil.which("python3", path=OLD_ONLY_PATH)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SCRIPTS)
        proc = subprocess.run(
            [old, "-m", "review_plan_v2", "--version"],
            capture_output=True, text=True, timeout=120, env=env, cwd=str(REPO),
        )
        # 2 = tool error. Not 1, which means "found actionable findings" — a
        # broken interpreter reported as a review result is the category
        # confusion the guard exists to prevent.
        self.assertEqual(proc.returncode, 2, msg=f"stdout={proc.stdout} stderr={proc.stderr}")
        self.assertIn("requires Python >=", proc.stderr)

    def test_the_module_runs_on_this_interpreter(self):
        """Anti-vacuity control: proves exit 2 above came from the version guard
        and not from the module being unrunnable however it is invoked."""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SCRIPTS)
        proc = subprocess.run(
            [sys.executable, "-m", "review_plan_v2", "--version"],
            capture_output=True, text=True, timeout=120, env=env, cwd=str(REPO),
        )
        self.assertEqual(proc.returncode, 0, msg=f"stderr={proc.stderr}")
        self.assertIn("review-plan-v2", proc.stdout)


class TheWrapperResolvesAnInterpreter(unittest.TestCase):
    @unittest.skipUnless(HAVE_OLD_ONLY, "no below-floor python3 in /usr/bin to test against")
    def test_it_refuses_when_only_an_old_python_exists(self):
        """The wrapper is COPIED to a temp tree first, so `../.venv/bin/python`
        does not resolve. That path is an absolute candidate, independent of
        PATH, so running the in-repo script would find the 3.13 venv and this
        test would pass while proving nothing about the refusal.
        """
        with tempfile.TemporaryDirectory() as td:
            fake_scripts = Path(td) / "scripts"
            fake_scripts.mkdir()
            copy = fake_scripts / WRAPPER.name
            copy.write_text(WRAPPER.read_text(encoding="utf-8"), encoding="utf-8")
            proc = _run_wrapper(copy, OLD_ONLY_PATH)
        self.assertEqual(proc.returncode, 2, msg=f"stdout={proc.stdout} stderr={proc.stderr}")
        self.assertIn(f"no Python >= {FLOOR}", proc.stderr)
        # Exit 2 rather than 0 is the point: a run that never happened must not
        # look like a clean review.
        self.assertNotEqual(proc.returncode, 0)

    @unittest.skipUnless(
        (REPO / ".venv" / "bin" / "python").exists(),
        "no in-repo .venv to prove the venv candidate is load-bearing",
    )
    @unittest.skipUnless(HAVE_OLD_ONLY, "no below-floor python3 in /usr/bin to test against")
    def test_it_finds_the_in_repo_venv_when_path_offers_nothing(self):
        """Same PATH as the test above, real script this time. Proves the
        refusal is caused by the absence of a good interpreter, not by the
        restricted PATH breaking the wrapper for some unrelated reason."""
        proc = _run_wrapper(WRAPPER, OLD_ONLY_PATH)
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout} stderr={proc.stderr}")
        self.assertIn("review-plan-v2", proc.stdout)

    def test_it_refuses_against_planted_shims_on_any_host(self):
        """The same refusal as above, with no premise about the host's /usr/bin.

        The two tests above are `skipUnless(HAVE_OLD_ONLY)`, and that skip is
        honest but it is also the whole coverage of the exit-2 path. On a Linux CI
        image whose /usr/bin/python3 is modern — the normal case now — the fail-
        closed behaviour this repo added is asserted by nothing, and a skip in a
        summary line reads exactly like a pass.

        So the interpreters are planted rather than discovered: a shim for every
        name the wrapper probes, each answering the version check with exit 1.
        /usr/bin and /bin stay on PATH for git and the other externals the wrapper
        calls before it looks for python; the shim directory goes in front, so
        `command -v python3` finds the shim rather than the host's.
        """
        with tempfile.TemporaryDirectory() as td:
            copy = _runnable_wrapper_copy(td)
            shim_dir = _shim_dir(td, "#!/bin/sh\nexit 1\n")
            proc = _run_wrapper(copy, f"{shim_dir}:/usr/bin:/bin")

        self.assertEqual(
            proc.returncode, 2,
            msg=f"stdout={proc.stdout} stderr={proc.stderr}",
        )
        self.assertIn(f"no Python >= {FLOOR}", proc.stderr)

    def test_the_planted_shims_are_what_caused_the_refusal(self):
        """Anti-vacuity control for the test above.

        A wrapper broken in any unrelated way also exits 2, so the refusal on its
        own does not prove the version loop was consulted. Same temp copy, same
        PATH shape, one difference: the shim answers the version probe with exit
        0 and then execs a real interpreter. If exit 2 above came from the copy
        being unrunnable outside the repo, this exits 2 as well and the pair is
        meaningless.
        """
        with tempfile.TemporaryDirectory() as td:
            copy = _runnable_wrapper_copy(td)
            shim_dir = _shim_dir(
                td, f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
            proc = _run_wrapper(copy, f"{shim_dir}:/usr/bin:/bin")

        self.assertEqual(
            proc.returncode, 0,
            msg=f"the shimmed interpreter passes the probe, so the wrapper must "
                f"run: stdout={proc.stdout} stderr={proc.stderr}",
        )
        self.assertIn("review-plan-v2", proc.stdout)

    def test_it_still_works_on_a_normal_path(self):
        proc = _run_wrapper(WRAPPER, os.environ.get("PATH", ""))
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout} stderr={proc.stderr}")
        self.assertIn("review-plan-v2", proc.stdout)

    def test_the_wrapper_no_longer_execs_an_unchecked_python(self):
        """A source-text assertion, deliberately narrow: the behavioural tests
        above cannot distinguish "resolved a good interpreter" from "happened to
        get one from PATH" on a machine where every python3 is modern. This
        catches a future edit that reverts to `exec python3` on such a machine,
        where nothing else here would go red.
        """
        text = WRAPPER.read_text(encoding="utf-8")
        offenders = [
            line for line in text.splitlines()
            if re.match(r'^\s*exec\s+python3?(\.\d+)?\s', line)
        ]
        self.assertEqual(
            offenders, [],
            msg="the wrapper execs a bare interpreter without a version check: "
                f"{offenders}",
        )
        self.assertIn('exec "$RPV2_PY"', text)

    def test_the_wrappers_own_floor_matches_MIN_PYTHON(self):
        """The third declaration of the floor, and the one that cannot import it.

        The wrapper probes candidates in shell, so its `sys.version_info >= (3,
        10)` is a literal by necessity. `TheFloorIsOneNumber` pins check_deps
        against pyproject and this pins the wrapper against check_deps; without
        it, raising the floor to 3.11 leaves the wrapper happily exec'ing a 3.10
        interpreter that the module then refuses, and the user sees a refusal from
        a version the wrapper just selected on purpose.
        """
        text = WRAPPER.read_text(encoding="utf-8")
        found = re.findall(r"sys\.version_info\s*>=\s*\((\d+)\s*,\s*(\d+)\)", text)
        self.assertTrue(
            found,
            msg="no `sys.version_info >= (X, Y)` probe in the wrapper. If the "
                "interpreter check moved, this stops comparing anything — fix "
                "the pattern, do not delete the test.",
        )
        for major, minor in found:
            self.assertEqual(
                (int(major), int(minor)), check_deps.MIN_PYTHON,
                msg=f"{WRAPPER.name} probes for >= {major}.{minor} but "
                    f"check_deps.MIN_PYTHON is {check_deps.MIN_PYTHON}",
            )
        # Named in the refusal message too, so the two cannot drift silently.
        self.assertIn(f"no Python >= {FLOOR}", text)


if __name__ == "__main__":
    unittest.main()
