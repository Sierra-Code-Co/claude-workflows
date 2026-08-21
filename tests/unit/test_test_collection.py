"""No test may be defined after its module's `__main__` guard (repo-wide).

THIS IS THE THIRD INSTANCE IN ONE SESSION. Twice the fix was "move those
classes"; a defect that recurs after being fixed twice is not a mistake, it is a
missing check — and it is invisible by construction, because the file still
imports, still passes, and simply runs fewer tests than it contains.

pytest imports the module, so it collects classes wherever they sit and the
suite stays green. Running the file directly executes `unittest.main()` at the
guard and never reaches what follows.

Measured rather than assumed, because the first draft of this docstring
overstated it: 17 test modules carry a `__main__` guard and 9 of them
self-bootstrap `sys.path`, so the guard is a live promise for those 9. The other
8 rely on pytest's `pythonpath` setting and already fail with
ModuleNotFoundError when run directly — their guard is vestigial, and that is a
smaller separate problem this check does not solve.

The check still applies to all of them: a test sitting after the guard is
invisible to any runner that honours it, and "present in the tree, absent from
the run" is the same shape as T005i and as every gate in this portfolio that
reported clean because it never executed.

Appending with `cat >>` reproduces it every time, which is exactly how all three
instances happened.
"""
from __future__ import annotations

import ast
import re
import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]


def _test_modules() -> list[Path]:
    return sorted(TESTS_DIR.rglob("test_*.py"))


def test_there_are_modules_to_check():
    """Anti-vacuous control: an empty glob makes every check below a no-op."""
    assert len(_test_modules()) >= 10, _test_modules()


@pytest.mark.parametrize("path", _test_modules(), ids=lambda p: p.name)
def test_no_test_is_defined_after_the_main_guard(path: Path):
    tree = ast.parse(path.read_text())

    guard_line = None
    for node in tree.body:
        if (isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"):
            guard_line = node.lineno
            break
    if guard_line is None:
        return  # no guard, nothing can hide behind it

    stranded = [
        n.name for n in tree.body
        if n.lineno > guard_line
        and isinstance(n, (ast.ClassDef, ast.FunctionDef))
        and (n.name.startswith("test_") or n.name.endswith("Tests")
             or n.name.endswith("TestCase"))
    ]
    assert not stranded, (
        f"{path.name} defines {stranded} AFTER `if __name__ == '__main__'`. "
        f"pytest still collects them, so the suite stays green — but running "
        f"this file directly stops at the guard and silently runs fewer tests "
        f"than the file contains. Move the guard to the end of the file."
    )


#: SCOPE, STATED RATHER THAN IMPLIED. This covers tests/integration only.
#:
#: RESOLVED 2026-08-16 (T005i-b), and the SCOPE was the bug. This constant read
#: "integration", so the check could not see the very modules the comment here
#: admitted were broken — a scope that matches nothing looks exactly like a
#: scope that passes, which is this repo's own `scope-config-test` lesson
#: appearing inside the guard written to apply it.
#:
#: Measured before the fix: 8 guarded modules under tests/unit (the note said 9;
#: it was stale), 7 of them unable to import standalone. Six were bootstrapped.
#: The seventh, test_telemetry_isolation.py, had its guard DELETED instead: its
#: tests assert REVIEW_PLAN_V2_LOG_DIR is set, which only conftest.py does, so
#: standalone they fail — correctly. A module that exists to verify the harness
#: cannot be run without it, and a guard made to "pass" by asserting less would
#: be worse than none, because it would look like coverage.
#:
#: Both directories are in scope now. The promise is live in each.
_DIRECT_RUN_SCOPE = ("integration", "unit")


def _guarded_modules() -> list[Path]:
    """Modules in scope whose `__main__` guard calls unittest.main()."""
    out = []
    for path in _test_modules():
        if path.parent.name not in _DIRECT_RUN_SCOPE:
            continue
        text = path.read_text()
        if 'if __name__ == "__main__":' in text and "unittest.main()" in text:
            out.append(path)
    return out


def test_there_are_guarded_modules_to_check():
    """Anti-vacuous control: an empty list makes the check below a no-op, and a
    scope that matches nothing looks exactly like a scope that passes."""
    assert len(_guarded_modules()) >= 5, _guarded_modules()


@pytest.mark.parametrize("path", _guarded_modules(), ids=lambda p: p.name)
def test_a_guarded_module_runs_directly(path: Path):
    """`if __name__ == "__main__": unittest.main()` is a PROMISE that the file
    can be run on its own. Nothing checked it.

    Eight integration modules bootstrapped `sys.path` to keep that promise, and
    clearing their E402s removed the bootstrap — breaking direct execution in
    all eight at once, silently, because pytest supplies the path itself and the
    suite stayed green. Found by review, not by any gate.

    Only the IMPORT is exercised (`--collect-only` semantics via a subprocess
    that stops before running tests): the point is that the module loads
    standalone, and actually running these would start fixture servers and take
    minutes.
    """
    proc = subprocess.run(
        # The path is captured BEFORE sys.argv is reassigned. Writing
        # `sys.argv = [sys.argv[1], ...]` and then reading `sys.argv[1]` again
        # reads the value just written — which is how the first version of this
        # tried to run a file called "--help".
        #
        # run_name is deliberately NOT "__main__": the guard must not fire, or
        # this would start fixture servers and run the whole integration suite.
        # Importing is the property under test.
        [sys.executable, "-c",
         "import runpy, sys; path = sys.argv[1]; sys.argv = [path]; "
         "runpy.run_path(path, run_name='not_main')",
         str(path)],
        capture_output=True, text=True, timeout=120,
        cwd=TESTS_DIR.parent,
        env={**os.environ, "PYTHONPATH": ""},
    )
    assert proc.returncode == 0, (
        f"{path.name} cannot be imported standalone, so its `__main__` guard "
        f"promises something that does not work:\n{proc.stderr[-800:]}"
    )



def test_the_direct_run_scope_covers_both_test_directories():
    """The scope WAS the bug (T005i-b), so it gets its own assertion.

    `_DIRECT_RUN_SCOPE` read `"integration"`, so this file's guard could not see
    the eight guarded modules under `tests/unit` — including the seven that
    could not import standalone. The comment above the constant said so out
    loud and the check still reported green, because a scope that matches
    nothing is indistinguishable from a scope that passes.

    Asserting the directory names rather than a count: a count is satisfied by
    any two directories, and the failure being guarded against is one of these
    two silently dropping out.
    """
    assert set(_DIRECT_RUN_SCOPE) == {"integration", "unit"}, _DIRECT_RUN_SCOPE
    covered = {p.parent.name for p in _guarded_modules()}
    assert covered == {"integration", "unit"}, (
        f"the scope names both directories but only matched {covered} — the "
        f"guarded-module glob is not finding what the scope claims"
    )


#: Modules whose `__main__` guard is deliberately absent, with the reason.
#: Exemptions are NAMED, never implied by absence — an unexplained gap in a
#: guard list is indistinguishable from an oversight.
_NO_GUARD_EXPECTED = {
    "test_telemetry_isolation.py":
        "its tests assert REVIEW_PLAN_V2_LOG_DIR is set, which only conftest.py "
        "does, so standalone they fail correctly; a module that verifies the "
        "harness cannot run without it",
}


def test_every_guarded_module_bootstraps_the_path_in_SOURCE():
    """The environment-independent half, and the reason it exists.

    `test_a_guarded_module_runs_directly` runs the module and checks it imports.
    That check is only DISCRIMINATING where `review_plan_v2` is not already
    importable — which is true on a fresh clone (the case the guard exists to
    serve) and false in CI, where `pip install -e ".[dev]"` puts the package on
    `sys.path` for every process. So in CI the runtime check passes whether or
    not the bootstrap is there.

    Measured, not assumed: a mutation removing `test_aggregator.py`'s bootstrap
    went red locally and STILL PASSED in CI, which is exactly how the harness
    reports "this test is decorative" — correctly, for that environment.

    This assertion reads the SOURCE, so it means the same thing everywhere.
    """
    missing = []
    for path in _guarded_modules():
        text = path.read_text()
        # A bootstrap is only REQUIRED if the module imports something that
        # needs the path. `test_env_sourcing.py` is stdlib-only and runs
        # standalone with no help — demanding a bootstrap there would be
        # cargo-culting the fix rather than stating the property. Caught by
        # this assertion on its first run, which is the point of writing it.
        # IMPORT STATEMENTS, not a substring search. The first version matched
        # the bare name "review_plan_v2" and flagged test_env_sourcing.py,
        # whose only mention is a FUNCTION NAME
        # (`test_review_plan_v2_prefix_allowed`). Matching text where the
        # structure is what matters is the same mistake as searching for ".."
        # instead of the path segment — third time in this session.
        needs_path = bool(re.search(
            r"^\s*(?:from|import)\s+(?:review_plan_v2|support)\b", text, re.M))
        if not needs_path:
            continue
        if 'parents[2] / "scripts"' in text or 'parents[1]))' in text:
            continue
        missing.append(path.name)
    assert not missing, (
        f"guarded but no path bootstrap: {missing}. On a fresh clone, where the "
        f"package is not pip-installed, `python {missing[0] if missing else ''}` "
        f"raises ModuleNotFoundError and the `__main__` guard is a false promise."
    )


def test_a_module_without_a_guard_is_exempt_for_a_STATED_reason():
    """Anti-vacuous companion: the exemption list must describe reality.

    A stale name here would silently excuse a module that has since grown a
    guard, and an unexplained one would be indistinguishable from an oversight.
    """
    for name, reason in _NO_GUARD_EXPECTED.items():
        path = TESTS_DIR / "unit" / name
        assert path.is_file(), f"{name} is exempted but does not exist"
        assert 'if __name__ == "__main__":' not in path.read_text(), (
            f"{name} is listed as guard-exempt but now HAS a guard — either "
            f"remove the exemption or remove the guard"
        )
        assert len(reason) > 40, f"{name}'s exemption gives no real reason"
