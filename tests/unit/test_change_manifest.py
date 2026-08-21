"""The tests reviewer must be able to see that tests were added (T047, FR-010).

This is the most-repeated false finding this tool has produced. "No test
coverage was added" was raised four times in one session against diffs whose
test files were in the SAME diff, and the mechanism is not subtle: the tests
reviewer was constructed with `needs_manifest=False`, so it received one file's
diff and no indication that any sibling file existed. It was not wrong about
what it could see. It was answering a question about the diff while being shown
a file.

Two properties are asserted separately, because they fail separately:

  * the manifest CLASSIFIES test files, which is a pure function of paths; and
  * the tests reviewer RECEIVES the manifest, which is one flag on a
    constructor and was the actual defect.

A test covering only the first would have passed for the entire period the
false positive was firing.
"""
from __future__ import annotations

import pytest

from review_plan_v2 import change_manifest
from review_plan_v2.reviewers import consistency, correctness, security, tests as tests_reviewer
from review_plan_v2.types import Diff, FileChange


def _fc(path: str, diff_text: str = "") -> FileChange:
    return FileChange(
        path=path,
        is_binary=False,
        is_renamed_from=None,
        added_lines=(),
        diff_text=diff_text or f"diff --git a/{path} b/{path}\n@@ -1 +1 @@\n+x\n",
        language=None,
    )


def _added(path: str) -> FileChange:
    return _fc(path, f"diff --git a/{path} b/{path}\nnew file mode 100644\n@@ -0,0 +1 @@\n+x\n")


def _diff(*files: FileChange) -> Diff:
    return Diff(base_ref="main", head_ref="HEAD", files=tuple(files))


# --- test-file classification -------------------------------------------------

TEST_PATHS = [
    "web/src/lib/server/deck-dedup.test.ts",       # the actual G2 file
    "web/src/lib/server/console-guard.test.ts",    # the actual G4 file
    "src/components/Button.spec.tsx",
    "src/__tests__/router.js",
    "tests/unit/test_change_manifest.py",
    "tests/integration/test_happy_path.py",
    "pkg/thing_test.go",
    "app/models/user_spec.rb",
    "tests/conftest.py",
    "web/tests/e2e/login.spec.ts",
]

NON_TEST_PATHS = [
    "web/src/lib/server/deck-dedup.ts",
    "web/src/lib/server/describe-thrown.ts",
    "scripts/review_plan_v2/change_manifest.py",
    "docs/testing.md",              # documents testing; is not a test
    "src/latest.ts",                # ends in "test" — substring matching fails here
    "src/protest.py",               # ditto, Python flavour
    "src/contest/handler.ts",       # a DIRECTORY whose name ends in "test"
]


@pytest.mark.parametrize("path", TEST_PATHS)
def test_a_test_file_is_classified_as_one(path):
    manifest = change_manifest.build(_diff(_fc(path)))
    assert path in manifest.tests_in_diff, f"{path} was not recognised as a test file"


@pytest.mark.parametrize("path", NON_TEST_PATHS)
def test_a_non_test_file_is_not_classified_as_a_test(path):
    """The anti-vacuous half. Without it, "everything is a test" passes above.

    `src/latest.ts` and `src/contest/handler.ts` are the shapes that break the
    obvious implementation — a substring search for "test" — and neither would
    occur to anyone writing the positives from recall.
    """
    manifest = change_manifest.build(_diff(_fc(path)))
    assert path not in manifest.tests_in_diff, f"{path} was wrongly called a test file"


def test_a_modified_test_file_counts_not_only_an_added_one():
    """The finding is "no tests were added for this change", and a developer
    extending an existing suite has done exactly that. Restricting the signal to
    `files_added` would leave the false positive firing on every change to a
    file that already had a test."""
    manifest = change_manifest.build(_diff(_fc("web/src/lib/server/deck-dedup.test.ts")))
    assert manifest.tests_in_diff == ["web/src/lib/server/deck-dedup.test.ts"]
    assert manifest.files_added == []


def test_added_files_still_distinguish_added_from_modified():
    manifest = change_manifest.build(
        _diff(_added("web/src/lib/server/deck-dedup.test.ts"), _fc("web/src/lib/server/deck-dedup.ts"))
    )
    assert manifest.files_added == ["web/src/lib/server/deck-dedup.test.ts"]
    assert manifest.tests_in_diff == ["web/src/lib/server/deck-dedup.test.ts"]


# --- the rendered payload -----------------------------------------------------


def test_the_rendered_manifest_names_the_test_files():
    manifest = change_manifest.build(
        _diff(_added("web/src/lib/server/deck-dedup.test.ts"), _fc("web/src/lib/server/deck-dedup.ts"))
    )
    rendered = change_manifest.render_for_prompt(manifest)
    assert "deck-dedup.test.ts" in rendered
    assert "tests_in_diff" in rendered


def test_the_rendered_manifest_says_so_explicitly_when_there_are_no_tests():
    """Silence is the failure mode. An absent line reads to a model exactly like
    a line saying zero, so the one case where "no tests were added" is a TRUE
    finding must be stated rather than left to inference."""
    manifest = change_manifest.build(_diff(_fc("web/src/lib/server/deck-dedup.ts")))
    rendered = change_manifest.render_for_prompt(manifest)
    assert "no test files" in rendered.lower()


# --- delivery: the half that was actually broken ------------------------------


def test_the_tests_reviewer_receives_the_manifest():
    """The defect itself. Classification is worthless if the reviewer that
    raises the finding is not shown it."""
    assert tests_reviewer.make().needs_manifest is True


def test_every_reviewer_that_can_raise_a_cross_file_finding_receives_the_manifest():
    """Derived from what the reviewers are asked to do, not from the one that
    was caught. `correctness` raised the describeThrown false positive about a
    symbol defined in an untouched file; `security` reasons about call sites it
    cannot see. Both answer questions the manifest bears on."""
    for make in (tests_reviewer.make, correctness.make, consistency.make, security.make):
        reviewer = make()
        assert reviewer.needs_manifest is True, (
            f"reviewer {reviewer.name} answers cross-file questions without "
            "being told what else is in the diff"
        )


def test_the_manifest_reaches_the_user_prompt():
    """End of the chain: the flag is set AND the text arrives."""
    reviewer = tests_reviewer.make()
    manifest = change_manifest.build(
        _diff(_added("web/src/lib/server/deck-dedup.test.ts"), _fc("web/src/lib/server/deck-dedup.ts"))
    )
    prompt = reviewer.build_user_prompt(_fc("web/src/lib/server/deck-dedup.ts"), manifest)
    assert "deck-dedup.test.ts" in prompt


# --- the CLI flag, pinned at the parser (reported by review) -------------------


def test_the_no_context_flag_defaults_off_and_can_be_set():
    """A misspelled option or an accidental `default=True` would disable US5's
    context for every run while every integration test still passed — they
    exercise the default path."""
    from review_plan_v2.__main__ import build_parser

    assert build_parser().parse_args([]).no_context is False
    assert build_parser().parse_args(["--no-context"]).no_context is True
