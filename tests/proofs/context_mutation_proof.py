"""Failure proof for US5's reviewer context: every guard can be shown to fail.

Counting tests proves nothing (constitution Principle II, FR-008a). This removes
ONE behaviour at a time from the context code and asserts the named test goes
red. A test that still passes with its subject deleted is decorative, and this
file exists because writing it found FOUR of them in a suite I had just written
and watched pass:

  * a containment test that passed with the containment check DELETED, because
    its `../../../../etc/passwd` specifier had too many `..` and was rejected as
    unresolved before containment was ever consulted;
  * an empty-render test whose subject was a redundant early return, so deleting
    it changed nothing observable;
  * an end-to-end manifest test that read the WRONG PROMPT — `caller.ts` matched
    the prompt for `caller.test.ts`, whose context block cites that path;
  * a delivery test needling `errMessage`, which appears in the changed line
    itself and so was present whether or not any context was attached.

All four asserted true things. None of them was measuring what its name claimed.

Runs in ~15s: each mutation copies the tree and runs ONE selected test, so the
cost is a pytest startup per mutation rather than a suite per mutation.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import re
import tempfile

#: pytest's "tests ran and at least one failed". Every other non-zero code means
#: the suite could not be executed as asked (2 interrupted/collection error,
#: 3 internal error, 4 usage error, 5 no tests collected).
EXIT_TESTS_FAILED = 1
_BROKEN_RE = re.compile(r"SyntaxError|IndentationError|errors? during collection|INTERNALERROR")


def _first_error_line(out: str) -> str:
    for line in out.splitlines():
        if _BROKEN_RE.search(line):
            return line.strip()[:160]
    return out.strip().splitlines()[-1][:160] if out.strip() else "(no output)"

REPO = pathlib.Path(__file__).resolve().parents[2]

MUTATIONS = [
    # (label, file, old, new, test that MUST go red)
    ("same-file hop removed",
     "scripts/review_plan_v2/context/related.py",
     '        take(decl, "same-file", chunk.path)',
     '        pass',
     "test_a_declaration_referenced_by_the_hunk_but_above_it_is_included"),

    ("transitive within-file hop removed",
     "scripts/review_plan_v2/context/related.py",
     '                if nested is not None and nested.name != decl.name:\n                    take(nested, "imported", rel)',
     '                if False:\n                    take(nested, "imported", rel)',
     "test_a_type_referenced_only_by_another_definition_is_pulled_in"),

    ("already-visible dedup removed",
     "scripts/review_plan_v2/context/related.py",
     '        if decl.text.splitlines()[0].strip() in visible:\n            continue',
     '        pass',
     "test_a_declaration_already_visible_in_the_hunk_is_not_repeated"),

    ("wanted-name filter removed (attach everything)",
     "scripts/review_plan_v2/context/related.py",
     '    for name in sorted(wanted):\n        decl = own.get(name)\n        if decl is None:\n            continue',
     '    for name in sorted(own):\n        decl = own.get(name)\n        if decl is None:\n            continue',
     "test_an_unreferenced_declaration_is_not_included"),

    # The next three rows moved from the modules' own inlined containment code
    # to their CALL SITES when T005g/T005h consolidated five copies of the
    # predicate into `review_plan_v2.paths`. Mutating the shared function would
    # have collapsed all three into one mutation and lost per-site coverage;
    # neutering each call keeps each module's own test on the hook. The harness
    # is what caught the consolidation — all three reported "MUTATION DID NOT
    # APPLY (needle absent)" rather than passing quietly, which is the whole
    # reason the needle is checked before the result is trusted.
    ("related: containment check disabled at the call site",
     "scripts/review_plan_v2/context/related.py",
     '_contained = contained',
     '_contained = lambda candidate, repo_root: True  # noqa: E731',
     "test_a_relative_specifier_escaping_the_repo_is_refused or test_a_symlink_pointing_outside_the_repo_is_refused"),

    ("unresolved specifiers no longer reported",
     "scripts/review_plan_v2/context/related.py",
     '            report.unresolved.append(imp.specifier)\n            continue',
     '            continue',
     "test_a_local_looking_import_that_does_not_resolve_is_reported"),

    ("external treated as unresolved",
     "scripts/review_plan_v2/context/related.py",
     '        if disposition == "external":\n            report.external.append(imp.specifier)\n            continue',
     '        if disposition == "external":\n            report.external.append(imp.specifier)\n            report.unresolved.append(imp.specifier)\n            continue',
     "test_a_third_party_import_is_external_not_unresolved"),

    ("unreadable file raises instead of degrading",
     "scripts/review_plan_v2/context/related.py",
     '        report.unreadable.append(chunk.path)\n        return blocks, report',
     '        return blocks, report',
     "test_a_missing_source_file_is_not_an_exception"),

    ("empty-glob reporting removed",
     "scripts/review_plan_v2/context/standing.py",
     '        if matched == 0:',
     '        if False:',
     "test_a_standing_glob_matching_nothing_is_reported"),

    ("standing tier no longer outranks derived",
     "scripts/review_plan_v2/context/budget.py",
     '_TIER = {"standing": 0, "same-file": 1, "imported": 2}',
     '_TIER = {"standing": 9, "same-file": 1, "imported": 2}',
     "test_standing_context_outranks_derived_context"),

    ("oversized block truncated instead of dropped",
     "scripts/review_plan_v2/context/budget.py",
     '        if used + block.chars <= limit_chars:',
     '        if True:',
     "test_a_single_block_larger_than_the_whole_budget_is_dropped_not_truncated"),

    ("drops counted, not named",
     "scripts/review_plan_v2/context/__init__.py",
     '            lines.append(f"  - {block.path} :: {block.symbol} ({block.chars} chars)")',
     '            lines.append("  - (one definition omitted)")',
     "test_the_rendered_context_reports_its_drops"),

    ("context header emitted with nothing under it",
     "scripts/review_plan_v2/context/__init__.py",
     '    if kept:\n        lines.append("[Referenced definitions',
     '    if True:\n        lines.append("[Referenced definitions',
     "test_rendering_nothing_produces_nothing"),

    ("SC-005: same-file resolution off for the gold-set corpus",
     "scripts/review_plan_v2/context/related.py",
     '    own = symbols.declarations(source, chunk.language)',
     '    own = {}',
     "test_the_gold_set_corpus_delivers_the_declaration_that_refutes_g6"),

    # --- T047, in the same sweep ---
    ("test-file classification always false",
     "scripts/review_plan_v2/change_manifest.py",
     '    return bool(_TEST_FILENAME_RE.match(posixpath.basename(normalised)))',
     '    return False',
     "test_a_test_file_is_classified_as_one"),

    ("test-file classification by bare substring",
     "scripts/review_plan_v2/change_manifest.py",
     '    return bool(_TEST_FILENAME_RE.match(posixpath.basename(normalised)))',
     '    return "test" in normalised or "spec" in normalised',
     "test_a_non_test_file_is_not_classified_as_a_test"),

    ("tests reviewer stops receiving the manifest",
     "scripts/review_plan_v2/reviewers/tests.py",
     'needs_manifest=True',
     'needs_manifest=False',
     "test_the_tests_reviewer_receives_the_manifest"),
    # --- end-to-end delivery: the half unit tests structurally cannot prove ---
    ("context assembled but never attached to the prompt",
     "scripts/review_plan_v2/orchestrator.py",
     '                if rendered:\n                    context_by_path[ch.path] = rendered',
     '                if False:\n                    context_by_path[ch.path] = rendered',
     "test_the_imported_definition_is_delivered"),

    ("standing files assembled but not attached",
     "scripts/review_plan_v2/orchestrator.py",
     '                    always_include=cfg.always_include_files,',
     '                    always_include=[],',
     "test_the_standing_file_is_delivered"),

    ("tests reviewer blind again, end to end",
     "scripts/review_plan_v2/reviewers/tests.py",
     'needs_manifest=True',
     'needs_manifest=False',
     "test_the_test_file_is_named_to_the_tests_reviewer_specifically"),

    ("--no-context stops reporting itself",
     "scripts/review_plan_v2/orchestrator.py",
     '                "--no-context was passed, so reviewers were NOT shown the "',
     '                "context was assembled normally and nothing is missing "',
     "test_the_opt_out_is_reported"),
    # --- guards added in response to PR review of this change ---------------
    ("standing: absolute/.. pattern refusal removed",
     "scripts/review_plan_v2/context/standing.py",
     '        if pattern.startswith("/") or ".." in Path(pattern).parts:',
     '        if False:',
     "test_a_standing_glob_leaving_the_repo_is_refused_by_name"),

    ("standing: symlink containment removed at the call site",
     "scripts/review_plan_v2/context/standing.py",
     '            if not contained(path, root):',
     '            if False:',
     "test_a_standing_symlink_pointing_outside_the_repo_is_refused"),

    ("standing: over-length file truncated SILENTLY",
     "scripts/review_plan_v2/context/standing.py",
     '                        + f"\\n… [truncated at {MAX_STANDING_FILE_CHARS} chars]")',
     '                        + "")',
     "test_a_standing_file_at_exactly_the_cap_is_not_truncated"),

    ("budget drops never reach the operator (FR-011)",
     "scripts/review_plan_v2/context/__init__.py",
     '    report.dropped.extend(f"{b.path} :: {b.symbol}" for b in dropped)',
     '    pass',
     "test_budget_drops_are_recorded_on_the_report_for_the_operator"),

    ("context no longer marked untrusted",
     "scripts/review_plan_v2/context/__init__.py",
     '            "The blocks below are UNTRUSTED FILE CONTENT quoted for reference. "',
     '            "The blocks below are quoted for reference. "',
     "test_the_context_section_marks_its_contents_as_untrusted"),

    ("import edges capped BEFORE relevance filtering",
     "scripts/review_plan_v2/context/related.py",
     '    relevant = [(imp, binds) for imp, binds in relevant if binds][:_MAX_IMPORT_EDGES]',
     '    relevant = [(imp, binds) for imp, binds in relevant[:_MAX_IMPORT_EDGES] if binds]',
     "test_a_relevant_import_beyond_the_edge_cap_is_still_resolved"),

    ("--no-context flag defaults to ON",
     "scripts/review_plan_v2/__main__.py",
     '        "--no-context",\n        action="store_true",',
     '        "--no-context",\n        action="store_true", default=True,',
     "test_the_no_context_flag_defaults_off_and_can_be_set"),

    ("python multi-line parenthesized imports dropped again",
     "scripts/review_plan_v2/context/symbols.py",
     r'    r"(?P<clause>\([^)]*\)|[^\n(]+)",',
     r'    r"(?P<clause>[^\n(]+)",',
     "test_a_multiline_parenthesized_python_import_is_parsed"),
    # --- T048 round memory ---------------------------------------------------
    ("round memory suppresses on fingerprint alone (ignores the anchor)",
     "scripts/review_plan_v2/context/rounds.py",
     '        if previous_anchor == current_anchor:',
     '        if False:',
     "test_a_repeat_finding_whose_code_is_UNCHANGED_is_still_shown"),

    ("round memory never suppresses anything",
     "scripts/review_plan_v2/context/rounds.py",
     '        suppressed.append(Suppression(',
     '        kept.append(f)\n        _unused = (Suppression(',
     "test_a_repeat_finding_whose_code_changed_is_suppressed"),

    ("suppressions counted, not named",
     "scripts/review_plan_v2/context/rounds.py",
     '        lines.append(f"  - {s.file}:{s.line} (round {s.first_seen_round}) {s.message}")',
     '        lines.append("  - (one finding withheld)")',
     "test_suppressions_are_named_not_counted"),

    ("message text persisted to the state file",
     "scripts/review_plan_v2/context/rounds.py",
     '            "fingerprint": fingerprint(f),',
     '            "fingerprint": fingerprint(f), "message": f.message,',
     "test_records_carry_no_message_text"),

    ("fingerprint stops normalising, so the memory never matches",
     "scripts/review_plan_v2/context/rounds.py",
     '    body = _NUM_RE.sub("#", _WS_RE.sub(" ", finding.message.strip().lower()))[:160]',
     '    body = finding.message',
     "test_reworded_whitespace_and_line_numbers_do_not_change_identity"),

    ("orchestrator renders the unfiltered set (memory computed, never applied)",
     "scripts/review_plan_v2/orchestrator.py",
     '        _render_and_print(visible, summary, cfg)',
     '        _render_and_print(merged, summary, cfg)',
     "test_round_two_suppresses_it_once_the_flagged_code_changed"),

    ("suppressed records re-anchored to the CURRENT code instead of carried forward",
     "scripts/review_plan_v2/context/rounds.py",
     '            record = {**record, "round": round_number}',
     '            record = {**record, "round": round_number, "first_round": round_number}',
     "test_history_records_what_was_RAISED_not_what_survived_suppression"),

    ("carry_forward drops the record entirely, so it ages out",
     "scripts/review_plan_v2/context/rounds.py",
     '    if not suppressed:\n        return prior',
     '    return prior\n    if not suppressed:\n        return prior',
     "test_history_records_what_was_RAISED_not_what_survived_suppression"),

    ("--force-full no longer recovers suppressed findings",
     "scripts/review_plan_v2/orchestrator.py",
     '        if cfg.force_full:\n            visible = merged',
     '        if False:\n            visible = merged',
     "test_force_full_recovers_a_suppressed_finding"),
    # --- fixes from the T048 pre-push review ---------------------------------
    ("anchor_hash reads outside the repository",
     "scripts/review_plan_v2/context/rounds.py",
     '    if not contained(path, root):',
     '    if False:',
     "test_anchor_hash_refuses_a_path_outside_the_repo"),

    ("a malformed anchor suppresses the finding",
     "scripts/review_plan_v2/context/rounds.py",
     '        if (not isinstance(previous_anchor, str) or not previous_anchor\n                or current_anchor is None):',
     '        if previous_anchor is None or current_anchor is None:',
     "test_a_malformed_anchor_does_not_suppress"),

    ("trim crashes on a hand-edited row",
     "scripts/review_plan_v2/context/rounds.py",
     '        try:\n            round_of = int(r.get("round", 0))\n        except (TypeError, ValueError):\n            continue',
     '        round_of = int(r.get("round", 0))',
     "test_trim_tolerates_the_same_junk_rows_partition_does"),

    # NOT REGISTERED, deliberately: the --force-full fingerprint dedup in
    # orchestrator.py is history HYGIENE, not behaviour. Removing it changes no
    # observable outcome — `partition` selects by minimum `first_round`, so the
    # duplicate row it prevents would lose to the original anyway (measured, not
    # assumed). A mutation nothing can detect belongs in a comment saying why,
    # not in a list that would then report a false "detected".

    ("auto-pause counts a suppressed round as trivial",
     "scripts/review_plan_v2/orchestrator.py",
     '        was_trivial = not any(f.severity == "actionable" for f in merged)',
     '        was_trivial = not any(f.severity == "actionable" for f in visible)',
     "test_a_round_whose_findings_were_all_suppressed_is_not_trivial"),
    # --- T005e: ruff as the fifth analyzer -----------------------------------
    ("ruff marks pyflakes defects as style nits",
     "scripts/review_plan_v2/analyzers/ruff.py",
     '    if code.startswith("F"):\n        return "actionable", "correctness"',
     '    if False:\n        return "actionable", "correctness"',
     "test_severity_is_derived_from_the_rule_family"),

    ("ruff marks cosmetics as actionable",
     "scripts/review_plan_v2/analyzers/ruff.py",
     '    return "nit", "style"',
     '    return "actionable", "style"',
     "test_severity_is_derived_from_the_rule_family"),

    ("ruff drops the -- separator before paths",
     "scripts/review_plan_v2/analyzers/ruff.py",
     '            "--force-exclude", "--",',
     '            "--force-exclude",',
     "test_the_argv_separates_flags_from_paths"),

    # REMOVED 2026-08-16: this row guarded "malformed JSON degrades to empty",
    # which US8/F1 established was itself the defect — `[]` already means
    # "looked and found nothing", so unparseable output reported CLEAN. Both its
    # needle and its named test are gone with the fix. The two rows in the
    # US8/F1 block above replace it with the corrected properties: unparseable
    # output RAISES, and base.run() converts that to a SKIP so the wave survives.

    ("ruff analyzer removed from the wave entirely",
     "scripts/review_plan_v2/orchestrator.py",
     '                     RuffAnalyzer(), structural]',
     '                     structural]',
     "test_the_ruff_analyzer_runs_in_the_wave"),
    # --- from the T005e review ------------------------------------------------
    ("a crashed analyzer reads as clean again (base class, all five)",
     "scripts/review_plan_v2/analyzers/base.py",
     '        if out.returncode != 0 and not findings:',
     '        if False:',
     "test_a_crashed_analyzer_is_reported_skipped_not_clean"),

    ("non-zero exit treated as failure even WITH findings",
     "scripts/review_plan_v2/analyzers/base.py",
     '        if out.returncode != 0 and not findings:',
     '        if out.returncode != 0:',
     "test_a_nonzero_exit_WITH_findings_is_a_normal_result"),

    ("direct-execution bootstrap removed from an integration module",
     "tests/integration/test_happy_path.py",
     'sys.path.insert(0, str(Path(__file__).resolve().parents[1]))',
     'pass',
     "test_a_guarded_module_runs_directly"),

    ("--force-exclude moved after the -- separator",
     "scripts/review_plan_v2/analyzers/ruff.py",
     '            "--force-exclude", "--",',
     '            "--", "--force-exclude",',
     "test_the_argv_separates_flags_from_paths"),

    # --- path containment, T005g/T005h ---------------------------------------
    # The schema-pattern row below is why this block is worth reading. Written
    # first WITHOUT it, the whole containment suite passed with the pattern
    # deleted: `load_registry` runs the Python check on the same input, so
    # through that entrypoint the schema layer had no observable behaviour. It
    # earns its place only as the standalone published contract, and only a test
    # validating against the schema ALONE can see it. Found by running these
    # mutations, not by re-reading the tests.

    ("registry containment check removed",
     "scripts/review_plan_v2/gates/registry.py",
     '    _check_paths_are_contained(gates, repo_root)',
     '    pass',
     "test_a_symlinked_gate_path_is_refused_at_load"),

    ("schema path pattern removed",
     "scripts/review_plan_v2/gates/schemas/gate-registry.schema.json",
     '      "pattern": "^(?!/)(?![\\\\s\\\\S]*(?:^|/)\\\\.\\\\.(?:/|$))(?:[^/\\\\\\\\]+/)*[^/\\\\\\\\]+$",\n',
     '',
     "test_the_schema_alone_rejects_an_escaping_path"),

    ("structural target refusal removed",
     "scripts/review_plan_v2/gates/structural.py",
     '            if safe_join(workdir, f.path) is None:',
     '            if False:',
     "test_an_escaping_target_is_never_handed_to_ast_grep"),

    # Needle carries the FOLLOWING line, because after the review fix the same
    # two-line guard appears in both `had_nothing_to_cover` and
    # `coverage_is_complete`. The harness refused the ambiguous needle rather
    # than mutating whichever came first — "needle matched 2 times, expected 1".
    ("refused paths no longer make coverage incomplete",
     "scripts/review_plan_v2/gates/structural.py",
     '        if self.refused_paths:\n            return False\n        if self.had_nothing_to_cover:',
     '        if self.had_nothing_to_cover:',
     "test_a_refused_target_makes_coverage_incomplete"),

    ("refused paths dropped from the coverage gaps",
     "scripts/review_plan_v2/gates/structural.py",
     '        refused = [\n            f"refused to analyze (outside the working directory): {p}"\n'
     '            for p in self.refused_paths\n        ]',
     '        refused = []',
     "test_a_refused_target_is_named_in_the_coverage_gaps"),

    ("traversal matched as a substring instead of a segment",
     "scripts/review_plan_v2/paths.py",
     '    return _TRAVERSAL not in raw.split("/")',
     '    return _TRAVERSAL not in raw',
     "test_an_ordinary_relative_path_is_accepted"),

    ("containment judged lexically, so symlinks escape",
     "scripts/review_plan_v2/paths.py",
     '    return resolved == root_resolved or root_resolved in resolved.parents',
     '    return Path(candidate).absolute().is_relative_to(Path(root).absolute())',
     "test_a_symlink_pointing_outside_the_root_is_refused"),

    # --- the four review findings on T005g/T005h, each mutation-covered ------
    # All four were CONFIRMED by measurement before being fixed, and one was
    # worse than reported: a symlink loop does not raise RuntimeError on 3.14,
    # it resolves lexically, so the docstring's claim that loops return False
    # was simply untrue. The claim was removed rather than the behaviour faked.

    ("backslash no longer rejected, so Windows traversal passes",
     "scripts/review_plan_v2/paths.py",
     '    if not raw or raw.startswith("/") or _ALWAYS_REJECT in raw:',
     '    if not raw or raw.startswith("/"):',
     "test_an_escaping_string_is_refused_before_the_filesystem_is_touched"),

    ("resolve() failures propagate instead of returning False",
     "scripts/review_plan_v2/paths.py",
     '    except (OSError, ValueError, RuntimeError):',
     '    except OSError:',
     "test_an_embedded_nul_returns_None_rather_than_raising"),

    ("schema traversal lookahead cannot cross a line terminator",
     "scripts/review_plan_v2/gates/schemas/gate-registry.schema.json",
     '"pattern": "^(?!/)(?![\\\\s\\\\S]*(?:^|/)\\\\.\\\\.(?:/|$))(?:[^/\\\\\\\\]+/)*[^/\\\\\\\\]+$",',
     '"pattern": "^(?!/)(?!(?:.*/)?\\\\.\\\\.(?:/|$))(?:[^/]+/)*[^/]+$",',
     "test_the_schema_alone_rejects_an_escaping_path"),

    ("a refused file reads as nothing-to-cover again",
     "scripts/review_plan_v2/gates/structural.py",
     '        if self.refused_paths:\n            return False\n        return self.coverable_file_count == 0',
     '        return self.coverable_file_count == 0',
     "test_a_refusal_and_a_skip_reason_are_reported_TOGETHER"),

    ("standing context swallows an unreadable path silently again",
     "scripts/review_plan_v2/context/standing.py",
     '            if not contained(path, root):\n                report.refused.append(str(path))',
     '            if not contained(path, root):\n                continue',
     "test_standing_context_refuses_an_unreadable_path_by_NAME"),

    ("verify.py containment call removed",
     "scripts/review_plan_v2/verification/verify.py",
     '        if not contained(target, repo_root):',
     '        if False:',
     "test_verify_input_resolution_refuses_a_symlinked_path"),

    # --- supply chain, T005d/T005f -------------------------------------------
    # These mutate the Dockerfile and the CI workflow, which no test EXECUTES —
    # so the mutation is the only thing standing between "we pin digests" and a
    # comment claiming we do. Each was additionally proven against a real
    # `docker build` on 2026-08-16 (wrong digest → DIGEST MISMATCH exit 1; empty
    # digest → REFUSING exit 1; failing test → build exit 1).

    ("one release artifact downloaded but not verified",
     "Dockerfile",
     '    verify "$gl_sha" /tmp/gitleaks.tar.gz; \\\n',
     '',
     "test_every_release_download_is_digest_verified"),

    ("base image back on a mutable tag",
     "Dockerfile",
     'FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134',
     'FROM python:3.12-slim-bookworm',
     "test_the_base_images_are_digest_pinned"),

    ("build no longer runs the test suite",
     "Dockerfile",
     'RUN python -m pytest tests/ -q',
     'RUN true  # tests not run',
     "test_the_build_runs_the_test_suite"),

    ("CI and image digests allowed to diverge",
     ".github/workflows/tests.yml",
     '          AST_GREP_SHA256: 76fb6555be6734fb5057dba8d2fb756430f374bb9e1af694cf1ce00e13238d63',
     '          AST_GREP_SHA256: 0000000000000000000000000000000000000000000000000000000000000000',
     "test_ast_grep_pin_matches_between_ci_and_the_image"),

    # Review's sharpest T005d finding: both verify() failure branches had only a
    # MANUAL proof (three real docker builds). A measurement is not a gate — it
    # does not run tomorrow. `test_dockerfile_verify_fn.py` now EXTRACTS the
    # function from the Dockerfile and runs it in bash, so these three mutate
    # shell that a Python test executes.

    ("verify() no longer refuses an empty digest",
     "Dockerfile",
     '      test -n "$1" || { echo "REFUSING: empty sha256 for $2" >&2; exit 1; }; \\\n',
     '',
     "test_an_EMPTY_digest_is_refused_rather_than_skipped"),

    ("verify() ignores a digest mismatch",
     "Dockerfile",
     '      echo "$1  $2" | sha256sum -c - || { echo "DIGEST MISMATCH: $2" >&2; exit 1; }; \\',
     '      echo "$1  $2" | sha256sum -c - || true; \\',
     "test_a_wrong_digest_is_rejected"),

    ("an artifact is unpacked BEFORE it is verified",
     "Dockerfile",
     '    verify "$gl_sha" /tmp/gitleaks.tar.gz; \\\n'
     '    tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks; \\',
     '    tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks; \\\n'
     '    verify "$gl_sha" /tmp/gitleaks.tar.gz; \\',
     "test_verification_precedes_unpacking"),

    # --- the gate portfolio, T011/T012 ---------------------------------------

    ("registry load removed from startup",
     "scripts/review_plan_v2/orchestrator.py",
     '    if registry_path.is_file():',
     '    if False:',
     "test_an_invalid_registry_stops_the_run_before_the_diff"),

    ("an absent portfolio is passed over in silence",
     "scripts/review_plan_v2/orchestrator.py",
     '            f"gate portfolio: NONE DECLARED ({registry_path} absent) — gate "',
     '            f"" or f"gate portfolio: ({registry_path}) "',
     "test_an_absent_registry_is_reported_not_assumed_fine"),

    ("a reviewer promoted to blocking without acceptance",
     "gates.yml",
     '  - id: reviewer.security\n    tier: probabilistic\n    blocking: advisory',
     '  - id: reviewer.security\n    tier: probabilistic\n    blocking: blocks',
     "test_no_probabilistic_gate_blocks"),

    ("a gate that exists in code is dropped from the portfolio",
     "gates.yml",
     '  - id: markdownlint\n',
     '  - id: markdownlint-DISABLED\n',
     "test_every_analyzer_and_reviewer_in_the_code_is_declared"),

    ("the structural rule is left undeclared",
     "gates.yml",
     '    rule: rules/raw-caught-to-logger.yml\n',
     '    rule: rules/fixtures\n',
     "test_every_structural_rule_on_disk_is_declared"),

    # Both from review of T011/T012. The safe_load finding was factually WRONG
    # — the loader already used it — but the guard is kept, because the day
    # someone swaps it in to support a custom tag, reviewing an untrusted PR
    # becomes remote code execution and nothing else here would notice.

    ("the gate registry parsed with yaml.load",
     "scripts/review_plan_v2/gates/registry.py",
     'doc = yaml.safe_load(path.read_text())',
     'doc = yaml.load(path.read_text(), Loader=yaml.SafeLoader)',
     "test_the_registry_is_parsed_with_safe_load"),

    # --- Phase 6: ordering, short-circuit, advisory exit codes ---------------
    # The ruff row is the one worth reading. `invalid-syntax` is not a rule id,
    # so every prefix branch missed it and A FILE THAT DOES NOT PARSE was
    # classified as a style nit — shipped in T005e, found here only because it
    # failed to trigger the short-circuit it was supposed to demonstrate.

    ("a file that does not parse is downgraded to a nit again",
     "scripts/review_plan_v2/analyzers/ruff.py",
     '    if code in _NON_RULE_CODES:\n        return "actionable", "bug"\n',
     '',
     "test_severity_is_derived_from_the_rule_family"),

    ("an unattributable finding stops blocking",
     "scripts/review_plan_v2/gates/attribution.py",
     '    if gate is None:\n        # Unattributable. See the module docstring: this direction is loud, the\n        # other is silent.\n        return True',
     '    if gate is None:\n        return False',
     "test_an_UNATTRIBUTABLE_finding_blocks"),

    ("a repo with no portfolio silently stops blocking",
     "scripts/review_plan_v2/gates/attribution.py",
     '    if registry is None:\n        return True\n    gate = gate_for(finding, registry)',
     '    if registry is None:\n        return False\n    gate = gate_for(finding, registry)',
     "test_with_no_registry_everything_blocks"),

    ("deterministic gates stop blocking too",
     "scripts/review_plan_v2/output_format.py",
     '        if f.severity == "actionable" and blocks(f, registry):',
     '        if f.severity == "actionable" and not blocks(f, registry):',
     "test_a_DETERMINISTIC_finding_still_fails_the_run"),

    ("exit 0 with advisory findings stops explaining itself",
     "scripts/review_plan_v2/output_format.py",
     '    _, advisory = split([f for f in findings if f.severity == "actionable"], registry)\n    if not advisory:\n        return []',
     '    _, advisory = split([f for f in findings if f.severity == "actionable"], registry)\n    if advisory or not advisory:\n        return []',
     "test_exit_zero_with_advisory_findings_is_explained"),

    ("an advisory finding triggers the short-circuit",
     "scripts/review_plan_v2/gates/attribution.py",
     '        if gate is not None and gate.is_deterministic and gate.blocks:',
     '        if gate is not None and gate.blocks:',
     "test_a_BLOCKING_PROBABILISTIC_gate_still_does_not_short_circuit"),

    # A "baseline stays at zero" test cannot be proven by WEAKENING it —
    # with nothing to find, the original assertion passes too, and the harness
    # correctly called that decorative. It has to be proven by INTRODUCING a
    # violation, which is what this row does (an unlabelled fence, MD040).
    ("structural coverage gaps stop reaching the report",
     "scripts/review_plan_v2/output_format.py",
     '    for gap in (summary or {}).get("structural_coverage_gaps") or []:',
     '    for gap in []:',
     "test_absent_coverage_reaches_the_rendered_report"),

    # Narrowing the scope back to `markdownlint .` does NOT fail once the
    # vendored paths are excluded by .markdownlintignore — both scopes read
    # zero, and the harness said so. The glob earns its place for exactly one
    # file: `.claude/skills/review-plan-v2/SKILL.md`, which is OURS and lives
    # in a dot-directory `markdownlint .` never descends into. So the mutation
    # plants a violation THERE, which the wide scope catches and the narrow one
    # would not.
    ("a violation in our own dot-directory skill goes unseen",
     ".claude/skills/review-plan-v2/SKILL.md",
     "## When to invoke",
     "## When to invoke\n\n```\nan unlabelled fence: MD040\n```",
     "test_the_markdownlint_baseline_stays_at_zero"),

    ("a markdownlint violation creeps back in",
     "specs/003-gate-portfolio/audit/sc008.md",
     "## Method",
     "## Method\n\n```\nan unlabelled fence: MD040\n```",
     "test_the_markdownlint_baseline_stays_at_zero"),

    # --- T021b/T064 propagation ---------------------------------------------

    ("a non-zero baseline is propagated as BLOCKING",
     "scripts/propagate_gates.py",
     '        return "blocks" if self.baseline == 0 else "advisory"',
     '        return "blocks"',
     "test_any_nonzero_baseline_enters_advisory"),

    ("an unmeasured baseline is propagated as blocking",
     "scripts/propagate_gates.py",
     '        return "blocks" if self.baseline == 0 else "advisory"',
     '        return "blocks" if self.baseline != 1 else "advisory"',
     "test_an_UNMEASURED_baseline_enters_advisory_not_blocking"),

    ("a failed scan reports zero findings instead of unknown",
     "scripts/propagate_gates.py",
     '    if shutil.which("ast-grep") is None:\n        return None',
     '    if shutil.which("ast-grep") is None:\n        return 0',
     "test_a_failed_scan_returns_None_not_zero"),

    # The baseline decides the TIER, so a measurement that counts this tool's own
    # seeded fixtures downgrades a working gate. Observed for real: 10 and 14
    # against directly-measured 0 and 4.
    ("the baseline counts the tool's own seeded proof material",
     "scripts/propagate_gates.py",
     '             "--globs", _PROOF_MATERIAL_GLOB, "--json"],',
     '             "--json"],',
     "test_the_baseline_excludes_the_proof_material_this_tool_ships"),

    ("worktrees stop being skipped",
     "scripts/propagate_gates.py",
     '    return Path(git_dir).resolve() != Path(common).resolve()',
     '    return False',
     "test_a_worktree_is_detected_structurally"),

    # Repointed: the propagated proof is no longer a template string in the
    # propagator, it is DERIVED from the trunk proof. So the guard to break is
    # the trunk's — there is now exactly one place it can be lost from, which is
    # the reason for the consolidation. The harness reported this needle as
    # UNPROVEN rather than passing over it, which is the whole design.
    ("the shared proof loses its CDPATH guard",
     "tests/proofs/raw_caught_to_logger.sh",
     'set -euo pipefail\nunset CDPATH',
     'set -euo pipefail',
     "test_the_generated_proof_unsets_CDPATH"),

    ("the shared proof stops failing closed when ast-grep does not run",
     "tests/proofs/raw_caught_to_logger.sh",
     '    if (( status > 1 )); then',
     '    if false; then',
     "test_the_generated_proof_fails_closed_when_the_scanner_does_not_run"),

    # --- T061/T062 regression guards ----------------------------------------

    ("the dead-leg banner stops naming the provider",
     "scripts/review_plan_v2/output_format.py",
     "                f\"[DEAD-LEG] provider '{entry.get('provider')}' failed all {attempted} \"",
     '                "[DEAD-LEG] a provider leg failed all "',
     "test_a_dead_leg_is_named_in_the_report"),

    ("call telemetry stops filtering to the allowlist",
     "scripts/review_plan_v2/telemetry.py",
     "    safe = {k: v for k, v in record.items() if k in _ALLOWED_KEYS}",
     "    safe = dict(record)",
     "test_a_call_record_drops_every_disallowed_field"),

    ("a content-bearing field is added to the allowlist",
     "scripts/review_plan_v2/telemetry.py",
     '    "max_tokens", "near_budget",',
     '    "max_tokens", "near_budget", "prompt",',
     "test_the_allowlists_contain_no_content_bearing_field"),

    # --- US8/F1: unparseable analyzer output is not a clean file -------------

    ("unparseable analyzer output degrades to empty again",
     "scripts/review_plan_v2/analyzers/ruff.py",
     "            raise AnalyzerOutputError(f\"invalid JSON from 'ruff': {exc}\") from exc",
     "            return []",
     "test_malformed_json_is_an_ERROR_not_an_empty_result"),

    # Second row mutates the CONVERSION, not the raise: base.run() turning the
    # error into a SKIP is what keeps one broken analyzer from aborting the
    # wave, and it is a separate property from raising at all.
    #
    # My first attempt here spliced `except X as exc if False else ():`, which
    # is not valid Python. The harness rejected it — "the mutation broke the
    # module, so the test was never exercised" — which is the guard added after
    # an unterminated string literal was once recorded as "detected".
    ("base.run lets a parse error escape instead of skipping",
     "scripts/review_plan_v2/analyzers/base.py",
     '        except AnalyzerOutputError as exc:',
     '        except NotImplementedError as exc:',
     "test_a_parse_error_becomes_a_SKIP_not_a_crash"),

    # --- US7: vendored-file drift ------------------------------------------

    ("untracked vendored files stop counting against clean",
     "scripts/speckit_drift.py",
     '        return not (self.modified or self.missing or self.untracked)',
     '        return not (self.modified or self.missing)',
     "test_a_file_the_manifest_never_saw_is_UNTRACKED_and_not_clean"),

    ("a corrupt manifest reports clean",
     "scripts/speckit_drift.py",
     '    except (OSError, json.JSONDecodeError):',
     '    except (OSError, json.JSONDecodeError) if False else ():',
     "test_an_unreadable_manifest_classifies_NOTHING_as_clean"),

    ("provenance ignored, so our own skills read as vendored",
     "scripts/speckit_drift.py",
     '        return source_of(root / rel) is not None',
     '        return True',
     "test_a_skill_without_a_source_field_is_NOT_vendored"),

    ("declared local edits go unreported",
     "scripts/speckit_drift.py",
     '    if report.local_edits:\n        lines.append(\n            "[LOCAL EDIT]',
     '    if False:\n        lines.append(\n            "[LOCAL EDIT]',
     "test_a_declared_local_edit_is_surfaced_even_though_it_hashes_pristine"),

    # First version of this row added an unused JSON key and changed nothing
    # observable — the harness reported it decorative, correctly. A mutation has
    # to remove COVERAGE to test a coverage assertion.
    ("a vendored file drops out of the shipped manifest",
     ".specify/integrations/speckit.manifest.json",
     '    ".claude/skills/speckit-clarify/SKILL.md": "fbbf23d64b46b90f31c08c80fc1e51f85d5d3fc77761a083e4bbf448106d098a",\n',
     '',
     "test_the_shipped_manifest_covers_the_whole_vendored_surface"),

    ("the nothing-reviewed banner goes silent again",
     "scripts/review_plan_v2/orchestrator.py",
     '        print(note, file=sys.stderr)',
     '        pass',
     "test_but_it_SAYS_it_reviewed_nothing"),

    ("--require-changes stops failing the run",
     "scripts/review_plan_v2/orchestrator.py",
     '        if cfg.require_changes:\n            return 2',
     '        if False:\n            return 2',
     "test_require_changes_makes_it_a_failure"),

    ("--require-changes never reaches the config",
     "scripts/review_plan_v2/types.py",
     '    base.require_changes = bool(base.require_changes) or bool(getattr(args, "require_changes", False))',
     '    pass',
     "test_the_flag_reaches_the_run_config"),

    ("direct-run scope narrowed back to integration only",
     "tests/unit/test_test_collection.py",
     '_DIRECT_RUN_SCOPE = ("integration", "unit")',
     '_DIRECT_RUN_SCOPE = ("integration",)',
     "test_the_direct_run_scope_covers_both_test_directories"),

    # Repointed at the SOURCE check after CI proved the runtime one is
    # environment-dependent. Locally `review_plan_v2` is not importable, so
    # removing a bootstrap breaks the import and the mutation fires; in CI
    # `pip install -e ".[dev]"` puts the package on sys.path for every process,
    # so the import succeeds either way and the harness correctly reported
    # "STILL PASSED — the test is decorative". A mutation that fires in one
    # environment and not another is not evidence in either.
    ("a unit module loses its path bootstrap",
     "tests/unit/test_aggregator.py",
     'sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))',
     'pass',
     "test_every_guarded_module_bootstraps_the_path_in_SOURCE"),

    ("gitleaks silently skips a file with added lines again",
     "scripts/review_plan_v2/analyzers/gitleaks.py",
     '                    if f.added_lines:\n                        not_scanned.append((f.path, "not present in the working tree"))',
     '                    if False:\n                        not_scanned.append((f.path, "not present in the working tree"))',
     "test_a_file_with_added_lines_that_is_missing_is_reported_not_skipped"),

    ("every skipped file reported, including deletions",
     "scripts/review_plan_v2/analyzers/gitleaks.py",
     '                    if f.added_lines:\n',
     '                    if True:\n',
     "test_a_DELETED_file_is_not_reported_as_a_gap"),

    ("a cascade leg stops resolving to its base reviewer",
     "scripts/review_plan_v2/gates/attribution.py",
     '        base = source.split(_CASCADE_MARKER, 1)[0] if _CASCADE_MARKER in source else source',
     '        base = source',
     "test_a_cascade_leg_is_attributed_to_its_BASE_reviewer"),

    ("gate telemetry starts carrying finding content",
     "scripts/review_plan_v2/telemetry.py",
     '    safe = {k: v for k, v in record.items() if k in _ALLOWED_GATE_KEYS}',
     '    safe = dict(record)',
     "test_gate_outcomes_record_counts_and_never_content"),

    ("an absent portfolio becomes fatal",
     "scripts/review_plan_v2/orchestrator.py",
     '            "tiers are implicit in this run.",\n            file=sys.stderr,\n        )',
     '            "tiers are implicit in this run.",\n            file=sys.stderr,\n        )\n        return 2',
     "test_an_absent_registry_is_reported_not_assumed_fine"),
]


def run() -> int:
    if not MUTATIONS:
        # An empty mutation list would print "all 0 mutations detected" and
        # exit 0 — the exact shape this portfolio exists to close.
        print("FAIL: no mutations registered; this proof proves nothing")
        return 1
    failures = []
    for label, relpath, old, new, test in MUTATIONS:
        # The public mirror (ADR-0010) ships without .claude/ and .specify/.
        # A mutation whose whole SURFACE is absent skips loudly; a missing
        # file inside a present surface still fails below — internally, a
        # renamed target must break this proof, not silence it.
        surface = pathlib.Path(relpath).parts[0]
        if not (REPO / surface).exists():
            print(f"  skip {label}\n         -> surface {surface}/ absent "
                  f"(public mirror, ADR-0010)")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp) / "repo"
            shutil.copytree(REPO, work, symlinks=True,
                            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
            target = work / relpath
            text = target.read_text()
            if old not in text:
                failures.append(f"{label}: MUTATION DID NOT APPLY (needle absent in {relpath})")
                continue
            if text.count(old) != 1:
                failures.append(f"{label}: needle matched {text.count(old)} times, expected 1")
                continue
            target.write_text(text.replace(old, new))
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-k", test, "-x", "--no-header"],
                cwd=work, capture_output=True, text=True, timeout=300,
            )
            out = proc.stdout
            if proc.returncode == 0:
                failures.append(f"{label}: {test} STILL PASSED — the test is decorative")
            elif "no tests ran" in out:
                failures.append(f"{label}: {test} selected NOTHING — the -k filter is wrong")
            elif proc.returncode != EXIT_TESTS_FAILED or _BROKEN_RE.search(out):
                # A mutation that breaks the FILE rather than the BEHAVIOUR proves
                # nothing: pytest exits non-zero for collection errors, internal
                # errors and usage errors as well as for failing assertions, and
                # they are indistinguishable at the exit code alone. One mutation
                # here really did this — it spliced an unterminated string literal
                # and was recorded as "detected" while the test never ran.
                failures.append(
                    f"{label}: pytest exited {proc.returncode} without a test "
                    f"FAILURE — the mutation broke the module, so the test was "
                    f"never exercised: {_first_error_line(out)}"
                )
            else:
                print(f"  ok   {label}\n         -> {test} goes red")

    print()
    if failures:
        print("UNPROVEN MUTATIONS:")
        for f in failures:
            print(f"  FAIL {f}")
        return 1
    print(f"ok: all {len(MUTATIONS)} mutations detected by their named tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
