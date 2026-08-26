"""Verify required system tools are present. Run via `python3 -m review_plan_v2.check_deps`."""
from __future__ import annotations

import shutil
import subprocess
import sys

REQUIRED = ["jq", "yq", "git"]
# ast-grep is the structural enumerator behind every deterministic completeness
# gate. RECOMMENDED rather than REQUIRED on purpose: without it a run must
# report "no deterministic coverage for this policy" and continue, never render
# clean. A missing enumerator that silently passes is the exact shape of the
# three silent degradations this portfolio exists to close.
RECOMMENDED = ["gitleaks", "markdownlint", "actionlint", "shellcheck", "ast-grep"]

#: Kept in sync with `requires-python` in pyproject.toml by
#: tests/unit/test_python_floor.py, which parses both rather than trusting a
#: comment to stay true.
MIN_PYTHON = (3, 10)


def python_version_error() -> str | None:
    """The refusal message if this interpreter is below MIN_PYTHON, else None.

    Split out of `check()` because the guard inside it was DEAD from the day it
    was written. Nothing imported check_deps: `grep -rn check_deps
    scripts/review_plan_v2/*.py` matched only the file itself, so the guard ran
    only when a human typed `python3 -m review_plan_v2.check_deps` by hand. The
    normal path is `scripts/review-plan-v2.sh`, which exec'd bare `python3` —
    on macOS that is /usr/bin/python3, 3.9.6. So the tool ran, every day, one
    minor version below the floor its own pyproject declares.

    It did not visibly break, and that is the finding rather than a mitigation:
    tests/conftest.py refuses to COLLECT below 3.10, so 3.9 is the one version
    the suite has never once exercised, and it was the version actually
    shipping. A latent 3.10-ism reaches a user before it reaches a test. One
    already did — see concurrency.py's `_TIMEOUT_ERRORS`, where
    `concurrent.futures.TimeoutError` not being the builtin below 3.11 silently
    disabled a deadline branch on exactly the interpreters CI never ran.
    """
    if sys.version_info < MIN_PYTHON:
        want = ".".join(str(p) for p in MIN_PYTHON)
        # Indexed, not `.major`/`.minor`: the comparison above is a tuple
        # comparison, so anything tuple-shaped satisfies the guard, and the
        # message must not then raise AttributeError on the same input. That is
        # not hypothetical — the first draft used the attributes and
        # test_python_floor's patched version_info made it an AttributeError
        # inside the refusal path, which is the "a refusal path that crashes is
        # not a refusal path" defect one more time.
        have = ".".join(str(p) for p in sys.version_info[:3])
        return (
            f"ERROR: review-plan-v2 requires Python >= {want}; this is {have} "
            f"({sys.executable}).\n"
            f"  pyproject.toml declares requires-python = \">={want}\" and the "
            f"test suite refuses to run below it, so {have} is untested — a "
            f"clean verdict from it would be unproven, not clean.\n"
            f"  Install one (brew install python@3.13) or run inside a venv."
        )
    return None


def check() -> int:
    err = python_version_error()
    if err is not None:
        print(err, file=sys.stderr)
        # Exit 2 (tool error), matching __main__'s guard on the same condition.
        # This returned 1, and 1 is this tool's code for "reviewed the diff, found
        # actionable findings" — so the two entrypoints reported the same
        # unusable interpreter as two different kinds of outcome, and the one that
        # `check_deps` chose was the one a caller reads as a substantive result.
        # Found while disproving a review finding that claimed this guard crashed
        # before it could print: it prints, on a real 3.9.6, with the wrong code.
        return 2

    missing_required: list[str] = []
    missing_recommended: list[str] = []

    for tool in REQUIRED:
        if shutil.which(tool) is None:
            missing_required.append(tool)

    for tool in RECOMMENDED:
        if shutil.which(tool) is None:
            missing_recommended.append(tool)

    # yq variant check (mikefarah's go binary, not the python yq)
    if shutil.which("yq") is not None:
        try:
            out = subprocess.run(["yq", "--version"], capture_output=True, text=True, timeout=5)
            version_text = (out.stdout + out.stderr).lower()
            if "mikefarah" not in version_text and "version v4" not in version_text and "version 4" not in version_text:
                print(
                    "WARNING: `yq` on PATH may not be mikefarah's go binary (review-plan-v2 expects v4+).\n"
                    f"  yq --version output: {(out.stdout + out.stderr).strip()}\n"
                    "  Install with: brew install yq",
                    file=sys.stderr,
                )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    if missing_required:
        print(f"ERROR: missing required tools: {', '.join(missing_required)}", file=sys.stderr)
        print("  brew install " + " ".join(missing_required), file=sys.stderr)
    if missing_recommended:
        print(f"NOTE: missing recommended analyzers: {', '.join(missing_recommended)}", file=sys.stderr)
        print("  brew install " + " ".join(missing_recommended), file=sys.stderr)

    if not missing_required:
        print("ok", file=sys.stderr)
    return 1 if missing_required else 0


if __name__ == "__main__":
    sys.exit(check())
