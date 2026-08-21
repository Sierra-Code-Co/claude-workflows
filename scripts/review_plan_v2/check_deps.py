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


def check() -> int:
    if sys.version_info < (3, 10):
        print(f"ERROR: python3 >= 3.10 required, found {sys.version_info.major}.{sys.version_info.minor}", file=sys.stderr)
        return 1

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
