"""Cross-file context for the reviewers: what else is in this diff.

Each reviewer is shown ONE file at a time, which is the right unit for reading
code and the wrong unit for answering "was a test added for this?". That
mismatch produced the most-repeated false finding this tool has made — "no test
coverage was added" raised four times in one session against diffs whose test
files were in the same diff (FR-010, gold-set entries G2/G4/G8/G9/G10).

So the manifest names the test files explicitly rather than leaving the reviewer
to infer them, and it says so out loud when there are none: an absent line reads
to a model exactly like a line saying zero, and "no tests were added" is
sometimes a TRUE finding that must stay available.
"""
from __future__ import annotations

import posixpath
import re

from .types import ChangeManifest, Diff


# Path shapes that mean "this file is a test", by convention across the
# ecosystems this tool reviews. Anchored on path SEGMENTS and extensions, never
# on a bare substring: `src/latest.ts`, `src/protest.py` and `src/contest/x.ts`
# all contain "test" and none of them is a test.
_TEST_FILENAME_RE = re.compile(
    r"""
    ^(?:
        test_[^/]+\.py                      # pytest:      test_thing.py
      | [^/]+_test\.(?:py|go|rb|ts|js)      # go/pytest:   thing_test.go
      | [^/]+_spec\.(?:rb|js|ts)            # rspec:       thing_spec.rb
      | [^/]+\.(?:test|spec)\.[jt]sx?       # vitest/jest: thing.test.ts
      | [^/]+Test\.(?:java|kt)              # junit:       ThingTest.java
      | conftest\.py                        # pytest fixtures are test code
    )$
    """,
    re.VERBOSE,
)

# Directory names that make everything beneath them test code.
_TEST_DIR_SEGMENTS = frozenset({"tests", "test", "__tests__", "spec", "e2e"})


def is_test_file(path: str) -> bool:
    """True if `path` is test code, by directory segment or filename shape."""
    normalised = path.replace("\\", "/")
    segments = normalised.split("/")
    if any(seg in _TEST_DIR_SEGMENTS for seg in segments[:-1]):
        return True
    return bool(_TEST_FILENAME_RE.match(posixpath.basename(normalised)))


def build(diff: Diff) -> ChangeManifest:
    added: list[str] = []
    removed: list[str] = []
    renamed: list[dict[str, str]] = []
    tests_in_diff: list[str] = []
    for f in diff.files:
        if f.is_renamed_from:
            renamed.append({"from": f.is_renamed_from, "to": f.path})
        elif f.diff_text.startswith("diff --git"):
            # Distinguish add vs delete via the diff content
            if "new file mode" in f.diff_text[:300]:
                added.append(f.path)
            elif "deleted file mode" in f.diff_text[:300]:
                removed.append(f.path)
        # Deliberately not restricted to `files_added`: a developer who extends
        # an existing suite HAS added test coverage, and scoping this to new
        # files would leave the false positive firing on every change to a file
        # that already had tests.
        if f.path not in removed and is_test_file(f.path):
            tests_in_diff.append(f.path)
    return ChangeManifest(
        files_added=added,
        files_removed=removed,
        files_renamed=renamed,
        tests_in_diff=tests_in_diff,
    )


def render_for_prompt(manifest: ChangeManifest) -> str:
    lines = ["[Cross-file change manifest]"]
    lines.append(f"- files_added: {manifest.files_added}")
    lines.append(f"- files_removed: {manifest.files_removed}")
    lines.append(f"- files_renamed: {manifest.files_renamed}")
    lines.append(f"- tests_in_diff: {manifest.tests_in_diff}")
    if manifest.tests_in_diff:
        lines.append(
            "  ^ These ARE test files and they ARE part of this change, even "
            "though you were shown only one file. Do not report that tests are "
            "absent for behaviour these files cover; ask whether the coverage "
            "is ADEQUATE instead."
        )
    else:
        # Stated, not omitted. The one case where "no tests were added" is a
        # TRUE finding is exactly the case with no line to read.
        lines.append(
            "  ^ This change contains no test files at all. A missing-coverage "
            "finding here is not contradicted by the manifest."
        )
    return "\n".join(lines)
