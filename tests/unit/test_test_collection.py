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
import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"


def _scripts_tree_modules() -> set[str]:
    """Top-level importable names under `scripts/`, read from the tree.

    Named by hand as `{"review_plan_v2", "rpv2_entry"}` until this function
    replaced it, which is the defect the comment inside
    `test_every_guarded_module_bootstraps_the_path_in_SOURCE` describes and then
    committed: a checker that enumerates the importables itself goes blind to a
    new one exactly when it is new. It was not hypothetical — `propagate_gates`
    and `speckit_drift` both sit there and neither was in the pair, so a guarded
    module importing either would have been judged to need no bootstrap.

    A `.py` file is a module and a directory with `__init__.py` is a package;
    anything else in `scripts/` (shell entrypoints, data) is not importable and
    cannot appear in an import statement.
    """
    out: set[str] = set()
    for p in SCRIPTS_DIR.iterdir():
        if p.is_file() and p.suffix == ".py":
            out.add(p.stem)
        elif p.is_dir() and (p / "__init__.py").is_file():
            out.add(p.name)
    return out


def test_the_scripts_tree_has_importables_to_check():
    """Anti-vacuous control: an empty set makes `needs_scripts` always False, so
    every guarded module would be judged to need no bootstrap and the check
    below would pass by finding nothing — a scope that matches nothing looks
    exactly like a scope that passes, which is this file's recurring lesson.

    Also names the two the hand-written pair missed, so if `scripts/` is
    reorganised such that they stop being importable, that shows up here rather
    than as a bootstrap check quietly narrowing.

    SCOPE, since the first draft of this docstring overstated it: this pins the
    ENUMERATOR, not its use. Someone re-hardcoding the set at the call site while
    leaving this function in place would not fail here. Asserting that would mean
    text-matching the other test's source for a literal, which is the technique
    this file exists to reject.
    """
    found = _scripts_tree_modules()
    assert {"review_plan_v2", "rpv2_entry", "propagate_gates", "speckit_drift"} <= found, found


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
    repro = []
    scripts_modules = _scripts_tree_modules()
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
        # WHICH tree, not just "a tree". The two packages live in different
        # directories — `review_plan_v2` in `scripts`, `support` in `tests` — so
        # "this module bootstraps something" is not the property. Conflating them
        # is what hid a real bug in two files: test_cascade.py and
        # test_edge_cases.py inserted `parents[1]` (tests), which covers their
        # visible `support` imports, and ALSO imported `review_plan_v2` from an
        # INDENTED line inside a test method. Both spellings of this check —
        # matching the literal `parents[2] / "scripts"`, and the looser "an
        # insert plus a named tree" that replaced it — accepted both files.
        #
        # It stayed invisible for two compounding reasons: the package is
        # pip-installed into .venv, so a local direct run resolves it from
        # site-packages, and on a fresh clone the failure is a ModuleNotFoundError
        # raised only once execution is deep inside a test method. Verified with
        # `sys.path` reduced to `tests`: the import does raise.
        #
        # `^\s*` deliberately matches indented imports. A local import inside a
        # method needs the path exactly as much as a top-level one, and it is
        # harder to see.
        # `rpv2_entry` too, not only the package. The 2026-08-25 module-shadowing
        # fix added `scripts/rpv2_entry.py` as a second top-level importable in the
        # same tree, and a checker that names one of the two by hand goes blind to
        # the other exactly when the other is new. A test importing `rpv2_entry`
        # with no bootstrap would have merged: CI exports PYTHONPATH, so the
        # missing insert only bites on a fresh direct run — which is the failure
        # mode this whole check exists for. Latent today (nothing imports it; the
        # isolation tests drive it as a subprocess), and one alternation to close.
        # The module need not be FIRST in the import list, and a regex kept getting
        # that wrong. `(?:from|import)\s+NAME` inspected only the first module of a
        # comma-separated statement, so `import support, review_plan_v2` set
        # needs_tests and not needs_scripts — the file would be judged to need only
        # the tests bootstrap and its missing scripts insert would pass unnoticed.
        # Same half-blindness the `rpv2_entry` comment above describes, reached from
        # the other direction.
        #
        # So walk the AST instead of matching text. A widened regex was the first
        # fix and it came with a comment justifying itself as "a regex rather than
        # an ast walk, because this check reads files that may not parse" — which
        # was false about the very function it sat in: the insert detection below
        # already calls `ast.parse` on this same `text`, unconditionally, twelve
        # lines later. A rationale that its own file contradicts is the defect this
        # suite keeps finding, so the honest move is to use the tree that is being
        # built anyway. Parsed ONCE here and reused below.
        #
        # The tree is also strictly more accurate than any regex was: it sees every
        # name in a comma list and every `as` alias for free, and it cannot be
        # fooled by the word `import` inside a string or a comment — two false
        # positives the text match had to be probed against by hand.
        tree = ast.parse(text, filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # `import a.b.c` needs the top-level name only.
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                # `node.level` skips relative imports: `from . import x` resolves
                # inside the package and needs no sys.path bootstrap at all.
                imported.add(node.module.split(".")[0])
        # ast.walk descends into function bodies, so an import inside a test method
        # counts — it needs the path exactly as much as a top-level one and is
        # harder to see. That was the `^\s*` in the old regex.
        # Read from the tree, not named here. See _scripts_tree_modules: the
        # literal pair this replaced already missed two importables, which is the
        # blindness the `rpv2_entry` comment above warns about arriving on
        # schedule. Hoisted out of the loop so the directory is read once.
        needs_scripts = bool(imported & scripts_modules)
        needs_tests = "support" in imported
        if not (needs_scripts or needs_tests):
            continue
        # A `sys.path` mutation derived from `__file__`, not one SPELLING of it.
        # This read `'parents[2] / "scripts"' in text or 'parents[1]))' in text`,
        # which is the same mistake the comment above warns about, one line down:
        # it matches the idiom 16 files happen to use rather than the property.
        # test_python_floor.py bootstraps via a `SCRIPTS = REPO / "scripts"`
        # constant it also uses elsewhere, runs standalone with no PYTHONPATH
        # (verified), and was still reported as missing a bootstrap. The fix for
        # that false negative is not to duplicate the blessed literal into the
        # file to satisfy a text match — that would be cargo-culting the fix,
        # exactly what the `needs_path` comment above declines to do.
        #
        # Still source-text rather than runtime, for the reason in the docstring:
        # CI's PYTHONPATH makes the runtime check pass either way.
        # Read the insert CALLS, not the whole file: `"scripts"` appears in
        # prose and in unrelated path expressions all over these modules, so
        # substring-searching the file body would accept a module that mentions
        # the word and bootstraps nothing.
        #
        # The CALL as the AST bounds it, not `r"sys\.path\.insert\([^\n]*"`.
        # `[^\n]*` stops at the first newline, so a bootstrap that black or ruff
        # format wraps across lines —
        #
        #     sys.path.insert(
        #         0, str(Path(__file__).resolve().parents[2] / "scripts"))
        #
        # — yielded only `sys.path.insert(`, with `"scripts"` on the line the
        # regex never saw. That is a FALSE FAILURE: the file bootstraps
        # correctly and the check reports it as missing, so a formatter run
        # could turn this suite red with no behaviour change. Same lesson as the
        # two comments above, one layer out: match the structure, not the text.
        inserts = []
        for node in ast.walk(tree):  # the parse above, not a second one
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            # `sys.path.insert(...)` — attribute chain, not a name that merely
            # ends in "insert". `path.insert` on a local list is not a bootstrap.
            if (isinstance(fn, ast.Attribute) and fn.attr == "insert"
                    and isinstance(fn.value, ast.Attribute) and fn.value.attr == "path"
                    and isinstance(fn.value.value, ast.Name)
                    and fn.value.value.id == "sys"):
                segment = ast.get_source_segment(text, node)
                if segment:
                    inserts.append(segment)
        joined = "\n".join(inserts)
        # Not pinned to one expression. `parents[2] / "scripts"` is the common
        # idiom and a `SCRIPTS = REPO / "scripts"` constant is equally valid —
        # test_python_floor.py uses the latter, runs standalone (verified), and
        # was reported as missing a bootstrap by the literal-matching version of
        # this check. Duplicating the blessed literal to satisfy a text match
        # would be cargo-culting the fix, which the `needs_*` comment above
        # declines to do for the same reason.
        has_scripts = "scripts" in joined or "SCRIPTS" in joined
        has_tests = "parents[1]" in joined or "TESTS" in joined
        want = []
        if needs_scripts and not has_scripts:
            want.append("scripts")
        if needs_tests and not has_tests:
            want.append("tests")
        if not want:
            continue
        missing.append(f"{path.name} (needs {'+'.join(want)} on sys.path)")
        # The path alone, kept separately, because the entry above carries a
        # ` (needs ... on sys.path)` suffix and the message below pastes an
        # element into a shell command. Interpolating `missing[0]` there emitted
        # `python test_foo.py (needs scripts on sys.path)` — unbalanced parens
        # and unquoted spaces, so the one line meant to tell a reader how to
        # reproduce the failure was itself un-runnable. Relative to the repo
        # root, not `.name`, so the command works from where you would run it.
        repro.append(path.relative_to(TESTS_DIR.parent).as_posix())
    assert not missing, (
        f"guarded but no path bootstrap: {missing}. On a fresh clone, where the "
        f"package is not pip-installed, `python {repro[0] if repro else ''}` "
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
