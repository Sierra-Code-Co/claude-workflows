"""Main run loop. argv parse → diff → config → ChangeManifest → analyzers → reviewers → aggregate → render → exit."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import (
    aggregator, change_manifest, config as config_mod, diff_capture, output_format,
    telemetry,
)
from .context import rounds
from .auto_pause import current_branch, repo_key, state_session
from .concurrency import TaskNeverStarted, run_with_cap
from .types import Diff, Finding, RunConfig, merge_cli_into_config


# Wall-clock budget for the whole reviewer phase.
#
# This was a flat 180s, which silently starved large runs: a 12-file diff is
# 48 reviewer tasks (12 x 4 reviewers) and at max_concurrency=4 that is 12
# sequential waves. Measured provider latency on a *tiny* hunk is 14-19s
# (deepseek-v4-pro 19.3s, gemini-3.1-pro-preview 51.2s), so 180s could never
# cover it. Tasks are submitted in reviewer order, so the deadline starved
# them in order — security completed, consistency never ran at all — while
# the run still exited 0 with "No findings" (mtg-cube-ai PR #1877).
#
# The per-wave figure must also stay above the provider's own per-call budget,
# or the run deadline fires before a legitimately slow wave can finish and the
# coverage banner blames a provider fault that is really a budgeting mistake.
# Measured 2026-08-13 on one real diff: reviewer calls take 10-19s on easy
# chunks and 65-125s on reasoning-heavy ones, so 45s truncated the hard half of
# every wave — the half worth reviewing.
PER_WAVE_BUDGET_SEC = 200.0
# Floor must exceed one slow call (180s) or a single hard chunk exhausts the
# whole budget on a tiny diff.
MIN_WALL_CLOCK_SEC = 300.0
# Ceiling stays at 30 minutes. It is a backstop, not a target: a pre-push gate
# that runs longer than this is not one anyone waits for, and since #27 an
# exhausted budget is reported loudly ([INCOMPLETE] + exit 2) rather than
# passing for a clean review, so a strict ceiling now costs honesty nothing.
MAX_WALL_CLOCK_SEC = 1800.0


def wall_clock_budget_sec(n_tasks: int, max_workers: int) -> float:
    """Scale the reviewer-phase deadline with the actual work queued.

    One "wave" is a full set of concurrent slots; a run needs
    ceil(n_tasks / max_workers) of them. Budgeting per wave rather than per
    run keeps small diffs fast to fail and stops large diffs from reporting
    a clean gate they never earned.
    """
    workers = max(1, max_workers)
    waves = -(-max(0, n_tasks) // workers)  # ceil division
    return min(MAX_WALL_CLOCK_SEC, max(MIN_WALL_CLOCK_SEC, waves * PER_WAVE_BUDGET_SEC))



def all_failed_message(entry: dict) -> str:
    """The stderr twin of the [DEAD-LEG] banner.

    Extracted so it can be asserted. Its previous version reported `calls` while
    the condition that fires it uses `attempted`, so a leg with 5 calls, 3
    starved and 2 real failures was described as having failed all 5 — and I
    claimed that fixed in a commit message before the edit applied, because the
    replacement targeted "WARNING:" where the code says "ERROR:" and silently
    no-op'd. A message built inline in a print() is a claim nothing can check.
    """
    attempted = entry.get("attempted")
    if attempted is None:
        attempted = int(entry.get("calls") or 0) - int(entry.get("starved") or 0)
    return (
        f"ERROR: the '{entry.get('provider')}' leg failed ALL {attempted} call(s) "
        "it actually made — it contributed NOTHING to this review. Treat any "
        "clean verdict on its paths as unproven until the cause above is fixed."
    )


def _printable(s: str) -> str:
    """Neutralise control characters in repo-derived text before it hits stderr.

    File names come from the repository under review, which on a pull request is
    attacker-influenceable (FR-022). CR alone rewrites the line in a terminal and
    ESC opens cursor, colour and title sequences — so a crafted filename could
    forge or erase the very NOTE lines that report what was filtered.
    """
    import unicodedata
    out = []
    for c in s:
        o = ord(c)
        # C0 + DEL, C1 (U+0080-U+009F), and every Unicode format control —
        # which is where the bidi overrides live. U+202E RIGHT-TO-LEFT OVERRIDE
        # in a filename visually reverses everything after it, so a path can be
        # made to render as a different path entirely. ASCII-only scrubbing
        # reads as thorough and stops exactly short of the spoofing case.
        if o < 0x20 or o == 0x7F or 0x80 <= o <= 0x9F or unicodedata.category(c) == "Cf":
            out.append(" ")
        else:
            out.append(c)
    return "".join(out)


def run(args) -> int:
    repo_root = os.getcwd()

    # 1. Load config
    cfg = config_mod.load_config(repo_root, cli_config_override=args.config)
    cfg = merge_cli_into_config(args, cfg)

    # Strict-config gate
    if cfg.strict_config and config_mod.has_config_error(cfg):
        print("ERROR: --strict-config: config error, ran with defaults aborted (exit 5)", file=sys.stderr)
        return 5

    # 1b. Load the gate portfolio (T012). Validated at STARTUP — before the diff
    # is captured and long before a provider is paid — so a malformed registry
    # costs nothing and is impossible to miss.
    #
    # A load failure is fatal, never a warning. The registry's whole job is to
    # make FR-007/FR-012/FR-014 mechanical, and a portfolio that "ran with
    # defaults" after failing validation would assert those invariants hold
    # while nothing checked them: the exact silent degradation the path_filters
    # block below was written to stop.
    #
    # A MISSING gates.yml is tolerated, and the asymmetry is deliberate — this
    # tool runs in downstream repos that have not adopted a portfolio yet, and
    # refusing to review them would be a regression. Absent is REPORTED, not
    # assumed: "no portfolio declared" and "portfolio says everything is fine"
    # must never print the same thing.
    registry = None
    registry_path = Path(repo_root) / "gates.yml"
    if registry_path.is_file():
        from .gates.registry import RegistryError, load_registry_file
        try:
            registry = load_registry_file(registry_path, repo_root=repo_root)
        except RegistryError as e:
            print(
                f"ERROR: {registry_path} is not a valid gate portfolio:\n{e}\n"
                "Refusing to run — the registry declares which gates may block "
                "and which failure proofs back them, so an unvalidated one "
                "cannot be reported as satisfied.",
                file=sys.stderr,
            )
            return 2
        blocking = sum(1 for g in registry.gates if g.blocks)
        print(
            f"gate portfolio: {len(registry.gates)} gate(s) declared "
            f"({blocking} blocking, {len(registry.gates) - blocking} advisory)",
            file=sys.stderr,
        )
    else:
        print(
            f"gate portfolio: NONE DECLARED ({registry_path} absent) — gate "
            "tiers are implicit in this run.",
            file=sys.stderr,
        )

    # 2. Capture diff
    try:
        diff = diff_capture.capture_diff(cfg.base, scope=cfg.scope, cwd=repo_root)
    except diff_capture.DiffCaptureError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    # Apply path_filters. CodeRabbit semantics: a bare pattern INCLUDES, a
    # `!`-prefixed one EXCLUDES. The previous implementation did neither — it
    # never stripped the `!` (so every declared exclusion was inert) and it
    # treated bare patterns as exclusions (so the include form did the opposite
    # of what it says). See path_filter.py for the measurements.
    filter_decision = None
    if cfg.path_filters:
        from .path_filter import FilterError, apply_filters
        try:
            filter_decision = apply_filters([f.path for f in diff.files], cfg.path_filters)
        except FilterError as e:
            # FAIL CLOSED. Leaving the diff unfiltered on a malformed pattern
            # silently disables every exclusion beside it — and this repo's own
            # config excludes `.claude/projects/**`, which is conversation logs.
            # One typo would have shipped them to four LLM providers. A filter
            # that may exist for confidentiality must never degrade into "review
            # everything"; the run stops and names the bad pattern.
            print(
                f"ERROR: path_filters is malformed ({_printable(str(e))}). Refusing to run "
                "unfiltered — a broken exclusion would send paths you meant to "
                "withhold to external providers. Fix the pattern and re-run.",
                file=sys.stderr,
            )
            return 2
        else:
            keep = set(filter_decision.kept)
            diff = Diff(
                base_ref=diff.base_ref, head_ref=diff.head_ref,
                files=tuple(f for f in diff.files if f.path in keep),
            )
            # Printed on EVERY run, not only on dry-run. A filter that reports a
            # magnitude and not a direction is unfalsifiable in the way that
            # matters: "17 files" reads the same whether it kept 17 or dropped 17,
            # and that ambiguity is what let an inverted filter survive.
            #
            # Paths and patterns are sanitised: filenames come from the repo
            # under review, so a name containing CR or ESC would rewrite this
            # very line. Same class as the verdict-marker fix.
            print(f"NOTE: {_printable(filter_decision.summary())}", file=sys.stderr)
            # COUNTS per named pattern, not the paths. Naming the pattern and
            # its tally already resolves the direction ambiguity that let an
            # inverted filter survive — "dropped by !references/**: 3" cannot be
            # confused with "kept 3". Listing the paths themselves would print
            # the names of files someone excluded deliberately, and an exclusion
            # is sometimes there for confidentiality. `--dry-run` still lists
            # everything, because that command exists to be inspected.
            for pattern, paths in filter_decision.dropped_by_pattern().items():
                print(f"NOTE:   dropped by {_printable(pattern)}: "
                      f"{len(paths)} file(s)", file=sys.stderr)

    if not diff.files:
        # T005k. Exit 0 here IS the documented contract ("0 = ... clean diff"),
        # and the danger is that the exit code alone cannot distinguish "I
        # reviewed everything and it was clean" from "I reviewed NOTHING". I hit
        # the second live: changes were staged but not committed, so the branch
        # tip equalled the base, and `review-plan-v2 && git push` would have
        # pushed unreviewed code while reporting success.
        #
        # Two reasons this is a banner plus an opt-in flag rather than a new
        # default exit code. An empty diff is genuinely nothing to do, and there
        # is nothing to push either; and `|| exit 1` pre-push hooks are a
        # documented use, so making the common case fail by default would break
        # them for a case that is usually harmless. `--require-changes` gives
        # scripts the strict reading without imposing it.
        reason = (
            "every changed file was excluded by path_filters"
            if filter_decision is not None and filter_decision.dropped
            else "there are no changes vs the base ref"
        )
        note = (
            f"[NOTHING REVIEWED] 0 files were examined — {reason}. This is NOT "
            f"a clean review: no gate ran, so nothing here was checked. If you "
            f"expected files, check that your changes are COMMITTED and that "
            f"--base is right."
        )
        if cfg.agent:
            print(output_format.render_agent_ndjson([], {
                "empty_diff": True, "nothing_reviewed": True,
                "nothing_reviewed_reason": reason,
                "config_warnings": cfg.config_warnings,
            }))
        else:
            print("No changes vs base. Nothing to review.")
        print(note, file=sys.stderr)
        if cfg.require_changes:
            return 2
        return 0

    # 3. ChangeManifest
    manifest = change_manifest.build(diff)

    # 4. Sequential gitleaks (security: never transmit secrets to LLMs)
    secret_findings: list[Finding] = []
    secret_coverage_gaps: list[str] = []
    analyzers_skipped: list[str] = []
    if not cfg.no_static_analyzers:
        from .analyzers.gitleaks import GitleaksAnalyzer
        gl = GitleaksAnalyzer().run(diff.files, workdir=repo_root)
        if gl.skipped:
            analyzers_skipped.append(f"{gl.name} ({gl.skip_reason})")
        else:
            secret_findings.extend(gl.findings)
        # T005j. A file gitleaks never staged produced no secret finding, which
        # is byte-identical to a file it read and cleared. Routed into the same
        # coverage-gap channel the structural enumerator uses, because it is
        # the same defect and the operator reads one place for it.
        secret_coverage_gaps.extend(getattr(gl, "coverage_gaps", list)())

    halt_due_to_secret = bool(secret_findings)

    # 5. Other analyzers (markdownlint, actionlint, shellcheck, structural) —
    # parallel; run even if gitleaks halted. The structural enumerator joins
    # this wave rather than getting a stage of its own: it is free and it must
    # run before any reviewer (FR-012), and this wave is already both.
    other_analyzer_findings: list[Finding] = []
    structural_gaps: list[str] = list(secret_coverage_gaps)
    structural_coverage: dict | None = None
    # rule_id -> rule file, for claims that verify by running a REGISTERED rule.
    # Built from rules the enumerator actually loaded, so a claim can only name
    # a rule that exists; the reviewer's string is matched against these keys and
    # never itself becomes a path (FR-023).
    structural_rule_paths: dict[str, Path] = {}
    if not cfg.no_static_analyzers:
        from .analyzers.markdownlint import MarkdownlintAnalyzer
        from .analyzers.actionlint import ActionlintAnalyzer
        from .analyzers.shellcheck import ShellcheckAnalyzer
        from .analyzers.ruff import RuffAnalyzer
        from .gates.structural import StructuralAnalyzer
        structural = StructuralAnalyzer(rules_dir=Path(repo_root) / "rules")
        analyzers = [MarkdownlintAnalyzer(), ActionlintAnalyzer(), ShellcheckAnalyzer(),
                     RuffAnalyzer(), structural]
        callables = [(a.name, lambda a=a: a.run(diff.files, workdir=repo_root)) for a in analyzers]
        results = run_with_cap(callables, max_workers=cfg.max_concurrency)
        for r in results:
            if r.exception is not None:
                analyzers_skipped.append(f"{r.name} (error: {r.exception})")
                if r.name == structural.name:
                    # An enumerator that crashed answered no completeness
                    # question. Recording it only in `analyzers_skipped` would
                    # bury it in a comma-joined footer line.
                    structural_gaps.append(f"structural analyzer crashed: {r.exception}")
                continue
            ar = r.value
            if ar.skipped:
                analyzers_skipped.append(f"{ar.name} ({ar.skip_reason})")
            else:
                other_analyzer_findings.extend(ar.findings)
            if r.name == structural.name:
                structural_gaps.extend(ar.coverage_gaps())
                structural_rule_paths = {
                    ro.rule_id: Path(ro.path) for ro in ar.rules if ro.ran
                }
                # `covered` gates the supersede step in the aggregator. It must
                # be the enumerator's own verdict, not "did it produce zero
                # findings" — those are the two states this whole gate exists
                # to keep apart.
                structural_coverage = {
                    "covered": ar.coverage_is_complete,
                    "finding_count": len(ar.findings),
                    "file_count": len({f.file for f in ar.findings}),
                    "rule_ids": [ro.rule_id for ro in ar.rules if ro.ran],
                }
    else:
        # --no-static-analyzers turns the enumerator off with everything else.
        # Opting out is allowed; opting out SILENTLY is not, so the run still
        # says that completeness went unanswered. Without this the flag buys a
        # clean-looking report, which is the cheapest possible way to defeat
        # the gate (Principle I).
        structural_gaps.append(
            "--no-static-analyzers was passed, so the structural enumerator did "
            "not run"
        )

    # FR-012 / T041. A blocking DETERMINISTIC failure short-circuits before any
    # provider is called, and SC-006 measures that as literally zero LLM calls.
    #
    # Generalised from the secret-only halt above, which was FR-012 implemented
    # for exactly one gate. The trigger is now read off the portfolio, so
    # registering a new deterministic gate as `blocks` gets the short-circuit
    # for free instead of needing another hand-written branch here — and no
    # branch can be forgotten, which is how the rule stayed true for gitleaks
    # and silently false for the other four.
    #
    # `--force-full` is deliberately NOT an escape hatch: the point is to avoid
    # paying for reviewers when a deterministic gate has already failed the run,
    # and no flag makes that spend worthwhile.
    halting_gate = None
    if not halt_due_to_secret and registry is not None:
        from .gates.attribution import deterministic_failure
        halting_gate = deterministic_failure(other_analyzer_findings, registry)

    if halt_due_to_secret or halting_gate is not None:
        if halting_gate is not None:
            print(
                f"SHORT-CIRCUIT: gate '{halting_gate.id}' is deterministic and "
                f"declared blocking, and it found an actionable issue. Stopping "
                f"before any reviewer runs — zero LLM calls made (FR-012). Fix "
                f"it and re-run; the reviewers had nothing to add until then.",
                file=sys.stderr,
            )
        merged = aggregator.aggregate(
            [secret_findings, other_analyzer_findings],
            path_instructions=cfg.path_instructions,
            dedup_window=cfg.dedup_window,
        )
        summary = {
            "auto_paused": False,
            "halted_on_secret": halt_due_to_secret,
            # Named, not just flagged. "short_circuited: true" would leave the
            # operator guessing which of six deterministic gates stopped the run.
            "short_circuited_by": halting_gate.id if halting_gate else (
                "gitleaks" if halt_due_to_secret else None
            ),
            "config_warnings": cfg.config_warnings,
            "analyzers_skipped": analyzers_skipped,
            "structural_coverage_gaps": structural_gaps,
            "providers_called": [],
        }
        _render_and_print(merged, summary, cfg)
        return 1

    # 6. Dry-run: report planned scope and exit before acquiring any state lock.
    if cfg.dry_run:
        # The PATHS, not just the count. A count cannot express direction, and
        # this line is exactly where an inverted filter went unnoticed: "would
        # review 17 files" was true both of the config I wrote and of its
        # opposite, so I read it as confirmation and published a wrong claim.
        print(f"DRY RUN: would review {len(diff.files)} files vs {diff.base_ref}", file=sys.stderr)
        for f in sorted(x.path for x in diff.files):
            print(f"DRY RUN:   {_printable(f)}", file=sys.stderr)
        return 0

    # 7. Auto-pause check + reviewer dispatch (lock spans full review)
    import subprocess as _subprocess
    try:
        rkey = repo_key(cwd=repo_root)
        branch = current_branch(cwd=repo_root)
    except (_subprocess.SubprocessError, OSError):
        rkey, branch = repo_root, "HEAD"

    with state_session(rkey, branch) as session:
        should_pause = session.should_pause(cfg.auto_pause_n) and not cfg.force_full
        reviewer_findings: list[Finding] = []
        providers_called: list[dict] = []

        if should_pause:
            summary = {
                "auto_paused": True,
                "config_warnings": cfg.config_warnings,
                "analyzers_skipped": analyzers_skipped,
                "structural_coverage_gaps": structural_gaps,
                "providers_called": providers_called,
            }
            merged = aggregator.aggregate(
                [secret_findings, other_analyzer_findings],
                path_instructions=cfg.path_instructions,
                dedup_window=cfg.dedup_window,
            )
            _render_and_print(merged, summary, cfg)
            print("=== Auto-paused (last N runs trivial) — pass --force-full to override", file=sys.stderr)
            return 0

        # Cost cap (FR-021) — naive estimator: chars/4 → tokens × $/M
        if cfg.max_cost_usd is not None:
            est = _estimate_cost_usd(diff, cfg)
            if est > cfg.max_cost_usd:
                print(f"ERROR: estimated cost ${est:.4f} exceeds --max-cost-usd ${cfg.max_cost_usd:.4f}", file=sys.stderr)
                return 3

        # Build reviewer × chunk callables
        from .providers import openai as openai_provider
        from .providers import google as google_provider
        from .reviewers import security, correctness, tests, consistency
        from .reviewers.base import Reviewer as ReviewerBase
        reviewers = [security.make(), correctness.make(), tests.make(), consistency.make()]
        # Cascade reviewers for high-risk paths. Two non-Claude frontier providers
        # run in parallel: OpenAI gpt-5.5 + Google gemini-2.5-pro. Anthropic was
        # dropped from the cascade because the operator works with Claude Code as
        # the implementation model — a Claude judge on Claude-written code is the
        # same anti-self-grading violation that spec 130's `routeJudgeForCandidate`
        # exists to prevent. Cascade providers now: deepseek (broad) + openai (cascade)
        # + google (cascade) = 3 independent non-Claude perspectives on high-risk paths.
        cascade_eligible = {"security", "correctness"}
        cascade_reviewers: list[tuple[ReviewerBase, str]] = []  # (reviewer, provider_tag)
        # A cascade leg with no API key is dropped here, silently. spec.md:180
        # names that exact shape as creating false confidence: the high-risk
        # paths get one reviewer instead of three and nothing in the output
        # says so. Track the omissions so they can be reported.
        cascade_skipped: list[str] = []
        if not cfg.no_cascade and cfg.high_risk_paths:
            if not os.environ.get("OPENAI_API_KEY"):
                cascade_skipped.append("openai (no OPENAI_API_KEY)")
            if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
                cascade_skipped.append("google (no GEMINI_API_KEY/GOOGLE_API_KEY)")
            for name in cascade_skipped:
                print(
                    f"WARNING: cascade leg skipped — {name}. High-risk paths are "
                    "being reviewed by fewer independent models than configured.",
                    file=sys.stderr,
                )
            for rv in reviewers:
                if rv.name not in cascade_eligible:
                    continue
                if os.environ.get("OPENAI_API_KEY"):
                    cascade_reviewers.append((ReviewerBase(
                        name=f"{rv.name}-cascade-openai",
                        prompt_filename=rv.prompt_filename,
                        provider_call=openai_provider.call,
                        model=openai_provider.DEFAULT_MODEL,
                        needs_manifest=rv.needs_manifest,
                    ), "openai"))
                if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
                    cascade_reviewers.append((ReviewerBase(
                        name=f"{rv.name}-cascade-google",
                        prompt_filename=rv.prompt_filename,
                        provider_call=google_provider.call,
                        model=google_provider.DEFAULT_MODEL,
                        needs_manifest=rv.needs_manifest,
                    ), "google"))

        chunks = list(diff_capture.chunked_files(diff))

        # US5: assemble referenced definitions + standing files ONCE per chunk.
        # Four reviewers see the same file, so computing this per (reviewer,
        # chunk) would repeat the same filesystem work four times and produce
        # four identical payloads.
        context_by_path: dict[str, str] = {}
        context_gaps: list[str] = []
        if cfg.no_context:
            # Opting out is allowed; opting out SILENTLY is not. Without this
            # line a run with the flag set is indistinguishable from one where
            # every referenced symbol happened to resolve.
            context_gaps.append(
                "--no-context was passed, so reviewers were NOT shown the "
                "definitions of symbols this diff references"
            )
        else:
            from . import context as context_mod
            merged_report = None
            for ch in chunks:
                if ch.is_binary:
                    continue
                kept, dropped_blocks, creport = context_mod.assemble(
                    ch, repo_root,
                    always_include=cfg.always_include_files,
                    aliases=cfg.import_aliases,
                    limit_chars=cfg.context_budget_chars,
                )
                rendered = context_mod.render_for_prompt(kept, dropped_blocks)
                if rendered:
                    context_by_path[ch.path] = rendered
                merged_report = creport if merged_report is None else merged_report.merge(creport)
            if merged_report is not None:
                context_gaps.extend(_context_gap_lines(merged_report))

        callables = []
        # Explicit provider mapping by task name (avoids fragile substring inspection downstream).
        task_provider: dict[str, str] = {}
        for rv in reviewers:
            for ch in chunks:
                if ch.is_binary:
                    continue
                task_name = f"{rv.name}:{ch.path}"
                task_provider[task_name] = "deepseek"
                callables.append((task_name, lambda rv=rv, ch=ch: rv.run(
                    ch, manifest=manifest,
                    context_text=context_by_path.get(ch.path, ""))))
        # Cascade only on chunks matching a high_risk_paths glob
        if cascade_reviewers:
            import fnmatch as _fnm
            high_risk_globs = [hr.path_glob for hr in cfg.high_risk_paths]
            for rv, provider_tag in cascade_reviewers:
                for ch in chunks:
                    if ch.is_binary:
                        continue
                    if any(_fnm.fnmatch(ch.path, g) for g in high_risk_globs):
                        task_name = f"{rv.name}:{ch.path}"
                        task_provider[task_name] = provider_tag
                        callables.append((task_name, lambda rv=rv, ch=ch: rv.run(
                    ch, manifest=manifest,
                    context_text=context_by_path.get(ch.path, ""))))

        budget_sec = wall_clock_budget_sec(len(callables), cfg.max_concurrency)
        results = run_with_cap(callables, max_workers=cfg.max_concurrency, deadline_sec=budget_sec)
        provider_call_counts: dict[str, int] = {"deepseek": 0, "openai": 0, "google": 0}
        provider_fail_counts: dict[str, int] = {"deepseek": 0, "openai": 0, "google": 0}
        provider_starved_counts: dict[str, int] = {"deepseek": 0, "openai": 0, "google": 0}
        failed_task_count = 0
        for r in results:
            provider_of_task = task_provider.get(r.name, "deepseek")
            provider_call_counts[provider_of_task] += 1
            if r.exception is not None:
                # STARVATION IS NOT FAILURE. A concurrency-level TimeoutError
                # means the task never got a worker slot, so it never reached
                # the provider at all — counting it against the provider is how
                # the openai and google legs were both branded "a configuration
                # failure, not a flaky run" on 2026-08-14 when their real
                # problem was 92 tasks queued behind a 1800s budget. Re-running
                # the identical branch at concurrency 12 produced zero such
                # banners with nothing about either provider changed.
                #
                # A fail-visible mechanism that cries wolf gets ignored, and
                # then the real 136-for-0 dead leg goes unnoticed again — which
                # is this portfolio's own thesis turned on its own alerting.
                if isinstance(r.exception, TaskNeverStarted):
                    provider_starved_counts[provider_of_task] += 1
                else:
                    provider_fail_counts[provider_of_task] += 1
                failed_task_count += 1
                # TimeoutError stringifies to '', which produced the useless
                # `failed: ` lines in the #1877 run. Name the failure mode and
                # the budget so the operator can act on it.
                exc = r.exception
                detail = str(exc) or type(exc).__name__
                if isinstance(exc, TaskNeverStarted):
                    detail = (
                        f"timed out — run budget {budget_sec:.0f}s exhausted "
                        f"({len(callables)} tasks at concurrency {cfg.max_concurrency})"
                    )
                print(f"WARNING: reviewer task {r.name} failed: {detail}", file=sys.stderr)
                continue
            reviewer_findings.extend(r.value or [])
        if failed_task_count:
            print(
                f"ERROR: {failed_task_count}/{len(callables)} reviewer tasks did not "
                "run — review coverage is INCOMPLETE and its verdict is unproven.",
                file=sys.stderr,
            )
        # `calls` alone is an attempt count, and an attempt count reads as
        # participation. The OpenAI leg reported `{"provider": "openai",
        # "calls": N}` on every run for three months while answering HTTP 400
        # to all N — and `test_cascade.py` asserted against exactly this field,
        # so it stayed green throughout. Report what SUCCEEDED.
        providers_called = [
            {
                "provider": p,
                "calls": n,
                # `attempted` is the honest denominator for "did this leg work?":
                # a starved task never reached the provider, so it can neither
                # succeed nor fail there.
                "starved": provider_starved_counts[p],
                "attempted": n - provider_starved_counts[p],
                "succeeded": n - provider_fail_counts[p] - provider_starved_counts[p],
                "failed": provider_fail_counts[p],
            }
            for p, n in provider_call_counts.items()
            if n > 0
        ]
        # A leg that fails every single call is not a flaky run, it is a
        # misconfiguration — a stale model id, a rejected parameter, a revoked
        # key. It is also the one shape that survives indefinitely, because
        # nothing else in the pipeline distinguishes it from "reviewed clean".
        for entry in providers_called:
            if entry["starved"]:
                print(
                    f"WARNING: the '{entry['provider']}' leg had "
                    f"{entry['starved']} of {entry['calls']} task(s) never start — "
                    "they ran out of run budget while queued, which is QUEUE "
                    "PRESSURE, not a broken provider. Re-run with a narrower diff "
                    "or a higher --max-concurrency.",
                    file=sys.stderr,
                )
            if entry["attempted"] > 0 and entry["failed"] == entry["attempted"]:
                print(
                    all_failed_message(entry),
                    file=sys.stderr,
                )

        # Refuted findings are removed inside aggregate(), so exit codes and
        # printed output cannot disagree about what the review found. They come
        # back out here because the COUNT is reported (FR-003): a silent drop is
        # indistinguishable from never having generated the finding.
        refuted: list[Finding] = []
        merged = aggregator.aggregate(
            [secret_findings, other_analyzer_findings, reviewer_findings],
            path_instructions=cfg.path_instructions,
            dedup_window=cfg.dedup_window,
            # Only passed here. The two earlier aggregate() calls (secret halt,
            # auto-pause) carry no reviewer findings, so there is no
            # speculation to supersede on those paths.
            structural_coverage=structural_coverage,
            # None disables verification and leaves every verdict at None — the
            # honest encoding of "the stage did not run", distinct from "ran and
            # could not check".
            repo_root=None if cfg.no_verify else Path(repo_root),
            rule_paths=structural_rule_paths,
            refuted_out=refuted,
        )

        # Round-N finding memory (T048, #20). Suppress only what was raised in
        # an earlier round AND whose flagged code has since changed — see
        # context/rounds.py for why the second condition is the whole feature.
        # --force-full shows everything, so a suppressed finding is recoverable.
        round_suppressed: list[rounds.Suppression] = []
        if cfg.force_full:
            visible = merged
        else:
            visible, round_suppressed = rounds.partition(
                repo_root, merged, session.finding_history
            )

        # History records what the reviewers SAID, not what survived
        # suppression: recording only the visible set would make a suppressed
        # finding eligible to reappear on the next round as though it were new.
        # Records for findings suppressed THIS round keep their original anchor
        # and only have their recency refreshed; newly-visible findings are
        # recorded fresh. Re-recording a suppressed finding with the CURRENT
        # anchor would make it read as unaddressed one round later and come
        # back — the feature undoing itself on run three.
        # History hygiene, NOT a correctness fix — and the difference was worth
        # checking. Review of this change claimed that recording every displayed
        # finding under --force-full "overwrites the preserved old anchor",
        # permanently un-suppressing it. Measured: it does not. Nothing is
        # overwritten; a duplicate row is appended, and `partition` selects by
        # the minimum `first_round`, so the ORIGINAL anchor still governs and
        # suppression survives.
        #
        # What is left is real but small: repeated --force-full runs would
        # accumulate duplicate rows inside the retention window. Skipping
        # already-known fingerprints keeps the history one row per finding.
        if cfg.force_full:
            already = {r.get("fingerprint") for r in session.finding_history
                       if isinstance(r, dict)}
            fresh = [f for f in visible if rounds.fingerprint(f) not in already]
        else:
            fresh = visible
        session.finding_history = rounds.trim(
            rounds.carry_forward(session.finding_history, round_suppressed, session.round_number)
            + rounds.record_for(repo_root, fresh, session.round_number),
            session.round_number,
        )

        # Computed from what the REVIEWERS found, not from what survived
        # suppression. Auto-pause exists to stop re-reviewing when nothing is
        # happening; a round where findings were suppressed because the developer
        # fixed them is a round where work happened, and counting it as trivial
        # would pause reviews precisely when the branch is moving.
        was_trivial = not any(f.severity == "actionable" for f in merged)
        session.record(was_trivial=was_trivial, head_commit=diff_capture.head_sha(cwd=repo_root))

        summary = {
            "auto_paused": False,
            "config_warnings": cfg.config_warnings,
            "analyzers_skipped": analyzers_skipped,
            "structural_coverage_gaps": structural_gaps,
            "cascade_skipped": cascade_skipped,
            # FR-011: context the harness failed to assemble, or dropped to fit
            # the budget. A reviewer given less than the operator configured is
            # a reviewer whose clean verdict covers less than it appears to.
            "context_gaps": context_gaps,
            # Named, not counted — a developer must be able to see exactly what
            # was withheld (the same rule the budget drops follow).
            "round_memory": rounds.render_suppressions(round_suppressed),
            # Per-leg succeeded/failed, not just an attempt count — see the
            # comment at the construction site.
            "providers_called": providers_called,
            # Coverage travels with the result so --agent consumers can gate on
            # it too, not just humans reading the plain renderer.
            "failed_task_count": failed_task_count,
            "total_task_count": len(callables),
            # 0 is a real number here, not a placeholder: verification ran and
            # refuted nothing. It differs from the flag being off, which shows
            # up as every verdict staying None.
            "refuted_dropped": len(refuted),
            "verification_ran": not cfg.no_verify,
            # FR-013. Findings from advisory gates no longer fail the run, so
            # the run has to SAY so — otherwise "20 findings, exit 0" becomes
            # indistinguishable from "0 findings, exit 0" and the advisory tier
            # costs exactly the signal it was meant to preserve.
            "advisory_notice": output_format.render_advisory_notice(visible, registry),
        }
        # FR-014 acceptance material (T043). Counts only — gate id, tier, and
        # two integers. `addressed` comes from round-memory suppression, which
        # fires only when the flagged code CHANGED since the finding was
        # raised: the closest thing to "the developer agreed" this tool can
        # observe. Without it, promoting a reviewer out of advisory would rest
        # on a feeling, which is what FR-014 exists to forbid.
        if registry is not None:
            from .gates.attribution import gate_for
            addressed_fp = {s.fingerprint for s in round_suppressed}
            per_gate: dict[str, dict[str, int]] = {}
            for f in visible:
                g = gate_for(f, registry)
                if g is None:
                    continue
                slot = per_gate.setdefault(g.id, {"raised": 0, "addressed": 0})
                slot["raised"] += 1
                if rounds.fingerprint(f) in addressed_fp:
                    slot["addressed"] += 1
            for gate_id, counts in per_gate.items():
                gate = registry.by_id(gate_id)
                telemetry.log_gate_outcome({
                    "gate": gate_id, "tier": gate.tier, "blocking": gate.blocking,
                    "raised": counts["raised"], "addressed": counts["addressed"],
                })
        _render_and_print(visible, summary, cfg)
        return output_format.exit_code_for(
            visible, failed_task_count=failed_task_count, registry=registry,
        )


def _render_and_print(findings: list[Finding], summary: dict, cfg: RunConfig) -> None:
    if cfg.agent:
        sys.stdout.write(output_format.render_agent_ndjson(findings, summary))
    else:
        sys.stdout.write(output_format.render_plain(findings, summary))
    sys.stdout.flush()


# Per-million-token pricing (rough; sufficient for cost cap heuristic).
# Format: (input_$_per_M, output_$_per_M). Anthropic dropped from cascade
# (anti-self-grading on Claude-written code); kept here for any historical
# replay tooling that still needs to compute Anthropic cost.
_PRICING = {
    # deepseek-v4-pro. Was (0.55, 2.19) — deepseek-reasoner/R1 pricing, stale
    # once the alias collapsed onto the v4 family. The cap gates on this, so a
    # wrong rate here mis-sizes --max-cost-usd.
    "deepseek": (0.28, 0.42),
    "openai": (5.0, 30.0),       # gpt-5.5
    "google": (1.25, 10.0),      # gemini-3.1-pro-preview (same rate as 2.5-pro)
    "anthropic": (3.0, 15.0),    # legacy / replay only
}
_NUM_REVIEWERS = 4
_CASCADE_REVIEWERS = 2  # security + correctness



def _context_gap_lines(report) -> list[str]:
    """Turn a ContextReport into operator-facing lines (FR-011).

    Only genuine gaps. `external` specifiers are owned by a package manager and
    were never going to resolve; listing them would bury the two entries that
    mean a reviewer is reasoning without a definition it should have had.
    """
    lines: list[str] = []
    if report.empty_globs:
        lines.append(
            "always_include_files matched NO files: "
            + ", ".join(sorted(set(report.empty_globs)))
            + " — the standing context you configured was not attached"
        )
    if report.unresolved:
        lines.append(
            f"{len(set(report.unresolved))} local import(s) did not resolve, so the "
            "definitions behind them were not shown: "
            + ", ".join(sorted(set(report.unresolved))[:8])
        )
    if report.refused:
        lines.append(
            "refused to read outside the repository: "
            + ", ".join(sorted(set(report.refused))[:8])
        )
    if report.unreadable:
        lines.append(
            "could not read: " + ", ".join(sorted(set(report.unreadable))[:8])
        )
    if report.dropped:
        # FR-011. The reviewer is already told these are missing; this line is
        # for the operator, who is the only one who can raise the budget.
        unique = sorted(set(report.dropped))
        lines.append(
            f"{len(unique)} definition(s) did not fit context_budget_chars and "
            "were NOT shown: " + ", ".join(unique[:8])
            + (" …" if len(unique) > 8 else "")
        )
    return lines

def _estimate_cost_usd(diff: Diff, cfg: RunConfig | None = None) -> float:
    """Heuristic cost estimate. Accounts for cascade spend (OpenAI + Gemini)
    on the high-risk subset for cascade-eligible reviewers."""
    import fnmatch as _fnm
    chars = sum(len(f.diff_text) for f in diff.files)
    in_tok = chars // 4
    out_tok = max(500, in_tok // 10)

    ds_in, ds_out = _PRICING["deepseek"]
    ds_cost = _NUM_REVIEWERS * (in_tok * ds_in + out_tok * ds_out) / 1_000_000

    # Cascade: OpenAI + Gemini run on the high-risk subset for cascade-eligible
    # reviewers. Both providers gated on env var presence — only providers with
    # keys contribute to the projection (matches actual run behavior).
    cascade_chars = 0
    if cfg and not cfg.no_cascade and cfg.high_risk_paths:
        globs = [hr.path_glob for hr in cfg.high_risk_paths]
        for f in diff.files:
            if any(_fnm.fnmatch(f.path, g) for g in globs):
                cascade_chars += len(f.diff_text)
    cascade_in_tok = cascade_chars // 4
    cascade_out_tok = max(500, cascade_in_tok // 10) if cascade_chars else 0

    cascade_cost = 0.0
    if os.environ.get("OPENAI_API_KEY"):
        oi_in, oi_out = _PRICING["openai"]
        cascade_cost += _CASCADE_REVIEWERS * (cascade_in_tok * oi_in + cascade_out_tok * oi_out) / 1_000_000
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        gg_in, gg_out = _PRICING["google"]
        cascade_cost += _CASCADE_REVIEWERS * (cascade_in_tok * gg_in + cascade_out_tok * gg_out) / 1_000_000

    return ds_cost + cascade_cost
