"""CLI entrypoint. Parses argv per contracts/cli-flags.md and dispatches to orchestrator.run."""
from __future__ import annotations

import argparse
import sys

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="review-plan-v2",
        description="Parallel multi-agent local code review",
    )
    out = p.add_mutually_exclusive_group()
    out.add_argument("--plain", action="store_true", default=True, help="Plain-text output (default)")
    out.add_argument("--agent", action="store_true", help="Structured NDJSON output for agent workflows")

    p.add_argument("--base", default=None, help="Base branch for diff (default: origin/HEAD → main → master → develop → staging)")
    p.add_argument("--type", choices=["all", "committed", "uncommitted"], default="all", help="Diff scope")
    p.add_argument("-c", "--config", default=None, help="Override .coderabbit.yaml location")
    p.add_argument("--no-color", action="store_true", help="Disable color in plain output")
    p.add_argument("-v", "--version", action="version", version=f"review-plan-v2 {__version__}")

    p.add_argument("--force-full", action="store_true", help="Bypass auto-pause (run all reviewers regardless)")
    p.add_argument("--auto-pause-n", type=int, default=None, help="Override auto-pause threshold (default 3)")
    p.add_argument("--max-concurrency", type=int, default=None, help="Cap on parallel reviewer x chunk x provider calls (default 4)")
    p.add_argument("--dedup-window", type=int, default=None, help="Line-overlap window for aggregator dedup (default 5)")
    p.add_argument("--no-static-analyzers", action="store_true", help="Skip gitleaks/markdownlint/etc")
    p.add_argument("--no-cascade", action="store_true", help="Disable Claude cascade on high-risk paths")
    p.add_argument("--max-cost-usd", type=float, default=None, help="Hard cost cap; abort if estimate exceeds (FR-021)")
    p.add_argument("--dry-run", action="store_true", help="Print what would be reviewed without invoking LLMs")
    p.add_argument(
        "--require-changes",
        action="store_true",
        help="Exit 2 if 0 files were reviewed (empty diff, or all files excluded "
             "by path_filters). Exit 0 otherwise cannot distinguish 'reviewed "
             "everything, clean' from 'reviewed nothing' (T005k)",
    )
    p.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip claim verification; show findings whose checkable claims are false (FR-002)",
    )
    p.add_argument(
        "--no-context",
        action="store_true",
        help="Do not attach referenced definitions or standing files to reviewer prompts (US5)",
    )
    p.add_argument(
        "--strict-config",
        action="store_true",
        help="Treat malformed config or missing yq as exit 5 (default: warning + exit follows findings)",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    # Before argparse, and before the orchestrator import below. The shell
    # entrypoint now resolves an interpreter that meets the floor, but
    # `python3 -m review_plan_v2` bypasses the shell entirely — CI, the
    # Dockerfile, and anyone reading the module path out of the README all
    # invoke it that way. A guard that only covers the wrapper leaves the
    # documented invocation unguarded, which is how the original one ended up
    # dead: it existed, in a module nothing called.
    #
    # Exit 2 (tool error), not 1: 1 means "reviewed the diff, found actionable
    # findings". Reporting an unusable interpreter as a review result would be
    # the same category confusion this guard exists to prevent.
    from .check_deps import python_version_error
    version_error = python_version_error()
    if version_error is not None:
        print(version_error, file=sys.stderr)
        return 2

    parser = build_parser()
    args = parser.parse_args(argv)
    # Defer import so --version/--help don't pay orchestrator import cost
    from .orchestrator import run

    return run(args)


if __name__ == "__main__":
    sys.exit(main())
