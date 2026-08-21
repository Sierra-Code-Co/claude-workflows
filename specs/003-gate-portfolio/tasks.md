# Tasks: The Gate Portfolio

**Feature**: `003-gate-portfolio` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

**TDD is required** (constitution, Testing Philosophy). Additionally: *a test MUST be
shown to fail against the unfixed code before it is trusted.* Every task below that
writes a test carries an explicit RED step. A test that passes both before and after is
vacuous and must be rewritten, not kept for coverage.

**Telemetry isolation**: `tests/conftest.py` already redirects `REVIEW_PLAN_V2_LOG_DIR`
session-wide. Do not add per-test cleanup — that is the exact `finally: os.environ.pop()`
pattern that disarmed the redirect and leaked 63 records into production telemetry.

---

## Phase 1: Setup

- [x] T001 Add `ast-grep` to `RECOMMENDED` in `scripts/review_plan_v2/check_deps.py`, guarded by `tests/unit/test_toolchain_declared.py`. **Corrected on contact with the code**: `scripts/new-machine.sh` is a dotfiles bootstrap (67 lines, symlinks CLAUDE.md and copies settings.json) and has never carried a system-dependency list — the original task named a file that could not satisfy it. `RECOMMENDED`, not `REQUIRED`, because a missing `ast-grep` must degrade to "no deterministic coverage for this policy" (T018), never to a silent pass. All 3 guard tests RED-proven by seeding each violation separately.
- [x] T002 [P] Create package skeletons `scripts/review_plan_v2/gates/__init__.py`, `scripts/review_plan_v2/verification/__init__.py`, `scripts/review_plan_v2/context/__init__.py`
- [x] T003 [P] Create `rules/` at repo root for the shared base rule set, with a `rules/README.md` pointing at `specs/003-gate-portfolio/quickstart.md`
- [x] T004 [P] Create `tests/proofs/` for executable failure proofs, with a `run-all.sh` runner that executes every proof and exits non-zero if any fails to go red. **An empty proof directory exits 1**, not 0 — "no proofs registered" must not read as "all proofs passed". Verified across all three states (empty / one passing / one failing); shellcheck clean.

---

## Phase 2: Foundational (blocks every user story)

The gate registry is the spine — US3, US2, US4, and US6 all attach to it.

- [x] T005 Create `pyproject.toml` declaring `PyYAML` + `jsonschema` (runtime) and `pytest` (dev extra), and switch CI to `pip install -e ".[dev]"`. **Corrected twice**: the original named a `pyproject.toml` that did not exist; the first correction tried to preserve the repo's stdlib-only stance by hand-rolling validation, which was contorting around a constraint rather than revisiting it. The portfolio genuinely needs to *parse* YAML (rules, registry) and JSON Schema (contracts) — shelling to `yq` for config this package owns trades a declared dependency for an undeclared one. Also sets `[tool.pytest.ini_options] pythonpath`, which retires the `sys.path.insert` hack in 16 of 17 test files. Verified by installing into a clean venv: 142 passed.
- [x] T005a **Resolved by design, not by writing the test it describes.** The task assumed the loader would re-implement the schema's invariants in Python, creating two encodings that could drift. Once `pyproject.toml` made `jsonschema` a declared dependency, `registry.py` validates *through* the schema instead — there is one encoding, so there is nothing to hold in agreement. What DID need a drift guard is the schema file itself, which now exists in two places for a real reason (`.dockerignore` excludes `specs/`, so a runtime read from there raises inside the image). That guard is `tests/unit/test_schema_copies_match.py`, byte-comparing the packaged copy against the authoritative contract; RED-proven with a one-byte change. Marked done because the risk is closed, not because the named file exists — it does not.
- [x] T005b Remove the now-redundant `sys.path.insert(0, .../scripts)` line from the test files that carry it. **9 files, not the 16 estimated** — the other inserts point at `tests/` for the `support.*` package, which `pythonpath = ["scripts"]` does NOT cover, so removing them would have broken collection. Verified file-by-file rather than trusting the regex (repo guardrail on bulk replacement); `ruff --select F401` then caught 4 imports left dangling, 3 of them pre-existing. 214 tests still green.
- [x] T005i **RESOLVED — and the skip was hiding a FALSE property, not just an unrun test.** CI's pytest job now installs gitleaks pinned to the Dockerfile's `GITLEAKS_VERSION` (both-side-anchored check, same form as ast-grep), and `test_static_analyzers.py` HARD FAILS rather than skipping when the binary is absent (**correction 2026-08-16: a note here briefly claimed this file did not exist. It does — `tests/integration/test_static_analyzers.py`. I searched only `tests/unit/`, created an empty file at the wrong path with `cat >>`, and published the wrong claim in #43 before checking the other directory. The T005j unit tests still belong in `tests/unit/test_gitleaks_overlap.py`; only the claim was wrong**). The decisive measurement, 2026-08-15, with gitleaks as the ONLY missing tool (every other binary symlinked into a shim PATH so the variable is isolated): the run **exits 0 instead of halting, and the secret-bearing diff reaches the LLM endpoint FOUR times**. So `skipIf` was not reporting "unverified" — it was reporting silence about a configuration in which the guarantee is off. That settles the question the task posed: for a security assertion, skip is never the right construct. Two new guards keep it fixed: a pin-drift test (gitleaks rules change between releases, so a CI runner on an older build would pass while detecting less than the image) and a CO-LOCATION test asserting the install lives in the same job as the suite — the repo already had a green `gitleaks` job, and its existence is exactly what made this invisible, since jobs share no filesystem. All three RED-proven. CI, host and container test counts should now agree at 430 with zero skips; that agreement is the standing signal.
- [x] T005e Add `ruff` as a fifth deterministic analyzer. Discovered during T005b: this is a Python project whose gate portfolio has **no Python linter at all** — `ruff --select F401` finds 3 live unused imports in `scripts/` (`auto_pause.time`, `config.os`, `orchestrator.FileChange`) that nothing in the repo would ever report. The four existing analyzers cover shell, YAML/Actions, markdown, and secrets; the language the tool is written in is the one gap. Measure its full-repo baseline first (FR-014) — markdownlint's 2541 is the cautionary case.
- [x] T005i-b **DONE 2026-08-16, and the SCOPE was the bug.** `_DIRECT_RUN_SCOPE` read `"integration"`, so the guard could not see the very modules its own comment admitted were broken — a scope matching nothing looks exactly like a scope that passes, which is this repo's `scope-config-test` lesson appearing inside the guard written to apply it. Now `("integration", "unit")`, and 16 modules are checked where 8 were. Measured before fixing: **8** guarded modules under `tests/unit` (the note said 9 — stale), **7** unable to import standalone. Six were bootstrapped. The seventh, `test_telemetry_isolation.py`, had its guard DELETED: its tests assert `REVIEW_PLAN_V2_LOG_DIR` is set, which only `conftest.py` does, so standalone they fail — CORRECTLY. A module that exists to verify the harness cannot run without it, and a guard made to pass by asserting less would be worse than none, because it would look like coverage.
- [x] T005c Build and verify `Dockerfile`. **BUILT AND VERIFIED 2026-08-14** on linux/aarch64: build exit 0, all six version pins asserted at build time, 174 tests pass inside the image with no bind mount. Building it found three defects that no host run could:
  - **shellcheck was 0.9.0 in the image vs 0.11.0 on the host** — it came from `apt`, not a pin. shellcheck gained checks between those versions, so the 180-finding baseline recorded for T063b would not have reproduced inside the image built to make runs reproducible. Now pinned to the release binary like the other analyzers.
  - **The build-time check was narrower than its own claim.** `check_deps` returns 0 whenever the three REQUIRED tools are present, so it printed "ok" over that drifted shellcheck. Replaced with explicit per-tool version assertions; RED-proven by asserting a deliberately wrong pin and confirming the build exits 1.
  - **`test_contract_file_is_valid_json_schema` could only ever pass on a dev laptop** — it reads `specs/`, which `.dockerignore` excluded. Fixed by shipping the contracts, not by skipping the test when absent: a drift check that silently does not run reports clean.
- [x] T005d **DONE 2026-08-16.** All ten artifact digests (5 tools × 2 arches) plus both `FROM` base images, pinned to the multi-arch INDEX digest so one pin still serves amd64 and arm64. Verification happens BEFORE unpacking — `tar -x` on an unverified archive has already written to the filesystem by the time a later check could object — and the same ordering was applied to the CI workflow's ast-grep download. **Provenance is not uniform and the Dockerfile says so**: 6 of 10 were cross-verified against the vendor's own published checksums file (yq via `checksums` + `checksums_hashes_order`, gitleaks and actionlint via `*_checksums.txt`) and matched exactly; shellcheck and ast-grep publish no checksums for these releases (asset lists checked, not assumed), so those 4 are trust-on-first-use — real protection against a re-tagged release, but not independent confirmation of upstream intent. Three build-level proofs, run rather than reasoned about: correct digests → build exit 0 with five `OK` lines; a wrong digest → `DIGEST MISMATCH` exit 1; an EMPTY digest → `REFUSING` exit 1. That last case needed its own guard: `sha256sum -c` on an empty hash is a *format* error, so `--build-arg YQ_SHA256_AMD64=` would otherwise have switched verification off while the build log looked unchanged. Guarded by `test_every_release_download_is_digest_verified` (counts downloads vs verifications, derived from the Dockerfile's structure rather than a remembered list), `test_the_base_images_are_digest_pinned`, and a digest half added to the ast-grep pin-drift test — pinning the version in two files while pinning the digest in one reopens the hole one file over. Original text: pin sha256 digests for every downloaded artifact. Version tags stop drift but not a re-tagged release. Scope grew after the 2026-08-14 self-review: the four release tarballs in `Dockerfile` (yq, gitleaks, actionlint, ast-grep) **plus** shellcheck, **plus** the ast-grep download added to `.github/workflows/tests.yml`, **plus** digest-pinning both `FROM` base images (`node:22-bookworm-slim`, `python:3.12-slim-bookworm`) — mutable tags today. Digests are omitted rather than invented; a wrong digest nobody checks is worse than a documented absent one.
- [x] T005f **DONE 2026-08-16.** `RUN python -m pytest tests/ -q` now runs in the build. **884 tests inside the image, matching host and CI exactly** — that three-way agreement is the standing signal, and it is now produced by the build rather than by someone remembering to check. Failure proof run for real: a deliberately failing test made the build exit 1 (`did not complete successfully: exit code: 1`) instead of producing an image; the temp test was removed and `git status` confirmed clean. Cost measured at ~26s on a ~4-minute build. Both prior container-only defects (`test_contract_file_is_valid_json_schema` reading `.dockerignore`-excluded `specs/`, and the pin-drift test's `FileNotFoundError: /work/Dockerfile`) would have been build failures under this. Guarded by `test_the_build_runs_the_test_suite`. Original text: run the test suite at image build time. Currently `tests/` ships but nothing executes it during the build, so container parity is only ever checked by hand. Both container-only defects so far (`test_contract_file_is_valid_json_schema`, then the pin-drift test's `FileNotFoundError: /work/Dockerfile`) would have been build failures instead of manual discoveries. Weigh against build time — the suite is ~18s, which is affordable.
- [x] T005g **DONE 2026-08-15.** Both layers as asked — a `repoRelativePath` `$def` in the schema and `_check_paths_are_contained` in `registry.py`, ordered before the existence check so an escaping path that happens to exist is refused for escaping rather than accepted for existing. The absolute case was the live one: `repo_root / "/tmp/x.sh"` IS `/tmp/x.sh`, so a proof outside the tree satisfied `.is_file()` and FR-007, and SC-004 would then have executed it. **The schema layer was decorative when first written** — the entire suite passed with the pattern deleted, because `load_registry` runs the Python check on the same input, so nothing reaching through that entrypoint could observe it. It earns its place only as the standalone published contract (editors, CI YAML validation, another repo adopting the portfolio), and only a test validating against the schema ALONE proves it. Found by mutation, not by re-reading. Original text: constrain `failure_proof` and `rule` paths at registry load; both are resolved and one is executed.
- [x] T005h **DONE 2026-08-15.** `_partition_contained` runs before every other branch in `run()`, so no later path can hand an escaping target to the subprocess. The refusal is NAMED, not silent: `refused_paths` rides on `StructuralResult`, is populated on both early returns as well as the main path, and surfaces through `coverage_gaps()` into the report. The ordering inside `coverage_is_complete` is the subtle part — a run whose only coverable file was refused has `coverable_file_count == 0`, so without the refused check placed BEFORE `had_nothing_to_cover`, declining to look at a file would have reported identically to "there was nothing to look at". This module's own thesis turned on itself; mutation-proven.
- [x] T005j **DONE 2026-08-16.** `GitleaksResult.not_scanned` carries WHICH files were never staged, and `coverage_gaps()` routes them into the same channel the structural enumerator uses, so the operator reads one place for absent coverage. The classification is what keeps it readable: a file with NO added lines is a deletion, and gitleaks only reports secrets on ADDED lines, so that skip is correct and silent — reporting it would fire on most diffs and the banner would be ignored by the third week. A file WITH added lines that is missing from the working tree is the dangerous case and is named. Containment refusals and staging errors are named too. Found while doing T005h; fixed here.
- [x] T005k **DONE 2026-08-16 — and HALF THE ORIGINAL CLAIM WAS WRONG.** I filed this as "rpv2 exits 0 when it reviews nothing" as though the exit code were the bug. `specs/001-review-plan-v2/contracts/cli-flags.md` explicitly documents exit 0 for a clean diff, and `|| exit 1` pre-push hooks are a documented use — so failing by default would break them for a case that is usually harmless (an empty diff has nothing to push either). The real gap is narrower: **nothing DISTINGUISHED "reviewed everything, clean" from "reviewed nothing"**. Fixed with a `[NOTHING REVIEWED]` stderr banner on every such run, naming WHICH emptiness (no changes vs base / all N excluded by path_filters — different causes, different fixes) and naming the remedy I actually needed ("check that your changes are COMMITTED"). `--require-changes` gives CI the strict reading (exit 2). The banner is the part that matters: a flag nobody passes changes nothing. Verified against the real CLI by reproducing the original incident. Contract table and `dotfiles/claude/CLAUDE.md` updated in the same change, since the propagated guidance quoted the old exit semantics verbatim.
- [x] T006 Write failing tests for registry load invariants in `tests/unit/test_gate_registry.py` — port the 6 registry cases already validated in Phase 1 (valid structural gate; probabilistic+blocking without acceptance rejected; with acceptance allowed; deterministic+cost=llm rejected; structural without rule ref rejected; missing failure_proof rejected). Add `additionalProperties: false` negatives at the gate and acceptance levels. **RED step**: run before `registry.py` exists; all must error on import, not pass.
- [x] T006a Write failing tests for `GateHealth` clean-run semantics in `tests/unit/test_gate_health.py` — `skipped_reason` non-null iff `ran` is false; `ran=false` without a reason is not a clean run; non-empty `dead_legs` forces non-zero exit; a gate with unset `health` is refused by the renderer rather than shown as clean (data-model invariant 4)
- [x] T007 Implement `Gate`, `GateHealth`, `Acceptance` dataclasses in `scripts/review_plan_v2/gates/registry.py` per `data-model.md`
- [x] T008 Implement registry load + schema validation in `scripts/review_plan_v2/gates/registry.py`, validating against `specs/003-gate-portfolio/contracts/gate-registry.schema.json`
- [x] T009 Enforce the dangling-`failure_proof` invariant at load in `scripts/review_plan_v2/gates/registry.py` — a reference that does not resolve to an existing file fails the load (FR-007)
- [x] T010 Enforce the ordering invariant at load in `scripts/review_plan_v2/gates/registry.py` — every `cost: free` gate must have lower `order` than any `cost: llm` gate (FR-012)
- [x] T011 **DONE 2026-08-16.** `gates.yml` declares **10 gates**: five analyzers (gitleaks, ruff, actionlint, shellcheck, markdownlint), the structural completeness rule, and the four reviewers. The block below was real and cleared by T035 shipping the proofs. **Every deterministic gate enters BLOCKING**, because FR-014's advisory-first rule is about noise and there is none — measured repo-wide across every tracked file on 2026-08-16: gitleaks 0 findings, ruff 0, actionlint 0, shellcheck 40 (17 info / 23 nit) and markdownlint 315 nit, with an **actionable count of ZERO for all five**. That corrects this file: T063a and T063b describe markdownlint/shellcheck 'residuals' of 176 and 180, but those are nit/info tier, so neither was ever blocking anything — they are tidiness, not gate policy. Reviewers enter `advisory` with `promoted_at` ABSENT rather than null, since the schema forbids blocking without it. Original text: create `gates.yml` registering the existing analyzers and reviewers at their current tiers. **BLOCKED ON T035 BY CONSTRUCTION, and that is the design working**: `failure_proof` is required *and* must resolve to an existing file, so no gate can be registered before its proof exists. Discovered while attempting T011 — the invariant refuses the registry rather than accepting a placeholder path. Do T035 (analyzer proofs) first.
- [x] T010b **`path_filters` has never filtered anything in this repo.** Found 2026-08-14 while scoping a re-review. `.coderabbit.yaml` declares nine exclusions in CodeRabbit's `!pattern` syntax (`'!references/**'`, `'!**/*.png'`, `'!.claude/projects/**'`, …). `config.py:105` copies them verbatim and `orchestrator.py:74-78` excludes any file matching one via `fnmatch` — **the `!` is never stripped**, so each pattern can only match a path literally beginning with `!`. Verified: `fnmatch('references/a.md', '!references/**')` is False. Every declared exclusion is inert, which is why a 52-file diff produced 212 reviewer tasks and starved 92 of them. A config block that does nothing while reading as policy is this portfolio's own defect class, in its own configuration layer. Fix: strip a leading `!` and treat bare patterns as include-only per CR semantics, or reject `!`-prefixed patterns loudly at load. Either way, add a load-time test — this was invisible because nothing ever asserted a file was actually excluded. **WORSE THAN INERT — the semantics are INVERTED (measured 2026-08-15).** A bare pattern EXCLUDES. With 30 changed files (13 under `scripts/`, 17 elsewhere), `path_filters: ["scripts/**"]` reviewed **17** — the complement — and `["tests/**"]` reviewed 15. CodeRabbit's convention is the opposite: a bare pattern INCLUDES and `!` excludes. Since `!` is never stripped (above), this config has **no include mechanism at all**, and the include form a reader would reach for silently reviews everything they meant to skip while skipping everything they meant to review. I hit this live: a run I described as "scoped to production code" reviewed zero `scripts/` files, and the dry-run FILE COUNT could not reveal it — only listing the files it actually reported on did (17 either way). Any fix must make the count insufficient to hide the direction, e.g. `--dry-run` printing the paths. Until then the only reliable form is exclusion-by-name of everything else. **RESOLVED 2026-08-15.** All three defects fixed together in `scripts/review_plan_v2/path_filter.py`: the `!` is stripped and excludes, a bare pattern INCLUDES (CodeRabbit semantics), and `fnmatch` is replaced with globset semantics — `**/` matches zero or more segments, so `!**/*.png` now catches a top-level `a.png` which it would still have missed after the `!` fix alone; a single `*` no longer crosses a separator. The readability fix is the one that matters: `FilterDecision` reports WHICH pattern dropped each file, the summary names include/exclude explicitly, and `--dry-run` prints the PATHS. A filter that reports only a magnitude is unfalsifiable in the direction that decides whether it works. 27 tests, RED-proven against the old fnmatch behaviour (7 fail).
- [x] T010a **The `[DEAD-LEG]` banner misdiagnoses starvation as misconfiguration.** Found 2026-08-14 by running review-plan-v2 against this branch: the openai and google legs each reported "failed all 2 calls — this is a configuration failure, not a flaky run. Re-running will not fix it." Both were **false**. Their actual failure was `timed out — run budget 1800s exhausted (212 tasks at concurrency 4)`: they were queued behind 92 starved tasks and never got a slot. Re-running with a narrower diff absolutely would fix it. The detector counts failures without discriminating failure KIND, so a leg that never ran is indistinguishable from a leg that is broken — which is this portfolio's own thesis applied to its own alerting. A fail-visible mechanism that cries wolf gets ignored, and then the real 136-for-0 dead leg goes unnoticed again. Exclude deadline-starved calls from the dead-leg denominator, or report them as a distinct `[STARVED]` line. **Confirmed the same day**: re-running the identical branch scoped to 37 files at concurrency 12 produced 3/152 failures and **zero** `[DEAD-LEG]` banners. Nothing about either provider's configuration changed between the two runs, so the banner was reporting queue pressure as misconfiguration. **RESOLVED 2026-08-15.** A concurrency-level `TimeoutError` means the task never got a worker slot, so it is now counted as `starved` rather than against the provider, and the dead-leg test uses `attempted` (calls minus starved) as its denominator. Starvation gets a distinct `[STARVED]` line naming the actual remedy — narrow the diff or raise `--max-concurrency` — because the operator's next move differs from a dead leg's. Anti-vacuous control is the important one: a genuinely dead leg still fires, since suppressing false alarms at the cost of the real 136-for-0 signal would be worse than the bug. Backward compatibility fails SAFE: a summary lacking `attempted` derives it rather than defaulting to 0 and going silent. 6 tests, RED-proven (3 fail against the old denominator).
- [x] T011a **RESOLVED `d8c3752` — it was never flaky.** `test_concurrent_serialized_no_torn_writes` reported a real lost update, correctly, every time it lost the race. Re-measured 2026-08-14 with a proper sample: **9/25 failures in the container, 0/40 on macOS**, always `19 != 20` and never 18. That constant was the whole diagnosis — exactly one increment lost means the window happens once per run, which points at initialization. `state_session` created the state file OUTSIDE the flock, so a thread that had already evaluated `path.exists()` as False truncated a value another thread had just committed. Fixed with `O_CREAT|O_RDWR`: creates when missing, never truncates. Post-fix **0/40 in the container**. The earlier "load-dependent" reading came from a 4-run sample and was wrong. Note the host was 0/40 BEFORE the fix too, so a laptop-only before/after would have blessed a no-op — the baseline has to be measured where the bug reproduces. A deterministic companion test now forces the losing interleaving instead of racing for it (0.02s, red against the old code).
- [x] T012 **DONE 2026-08-16.** Loaded and validated in `run()` BEFORE diff capture, so a malformed portfolio costs nothing and cannot reach a provider — a test asserts that ordering by making diff capture raise a sentinel the registry error must beat. Verified end-to-end against the real CLI, not only in tests: a valid file prints `gate portfolio: 10 gate(s) declared (6 blocking, 4 advisory)`, and promoting one reviewer to `blocks` produced `gates/6: 'acceptance' is a required property` and **exit 2**. FR-014 is now impossible to violate by hand-editing the registry. Three states stay distinguishable, and the third is the point: valid → proceeds, invalid → stops loudly, **absent → proceeds but is REPORTED** (`NONE DECLARED`), because downstream repos have not adopted a portfolio and 'nobody declared tiers' must never print the same thing as 'the declared tiers held'. **Known divergence, named and pinned**: the registry does not yet drive exit codes — `exit_code_for` still returns 1 for any actionable finding, so an `advisory` reviewer can still fail a run. That is FR-013/T042. `test_the_registry_does_not_yet_drive_exit_codes` goes RED the moment T042 lands, so the declaration cannot quietly stay false.

---

## Phase 3: US3 — Completeness answered by enumeration (P1)

**Goal**: a deterministic answer to "did I get all the sites?" in milliseconds.
**Independent test**: the `describeThrown` rule enumerates every violating site at
`68db762a` and 0 at `083084e5`, across all formatting and comment shapes.

- [x] T013 [P] [US3] Move the validated rule to `rules/raw-caught-to-logger.yml` as the first shared base rule. Gained `**/rules/fixtures/**` in `ignores:` so a real scan does not report the proof material as findings; the fixture test copies the tree out from under that path, so the exclusion cannot also hide the fixture from its own check.
- [x] T014 [P] [US3] Move the hardened fixture to `rules/fixtures/raw-caught-to-logger/` — **a directory tree, not the single file this task named.** Moving it exposed that `ast-grep scan --rule <rule> specs/.../fixture.ts` returned **zero findings and exit 0**: the fixture path matched neither `files:` glob, so the scan that "validated" the rule was inert — and `rules/README.md` documented that exact command as the way to check your work. Scope is a constraint like any other and cannot be exercised from one path. Re-deriving the shapes from the rule's constraint list (FR-008a) found two more gaps recall had left: the `console.log` positive (the alternation has three members; the recalled list covered two) and two callee near-misses — `logger.error` (violates only `^console\.`) and `console.debug` (violates only the method list). Now 8 positives + 8 negatives across 4 files at scoped paths.
- [x] T015 [US3] Write the executable failure proof in `tests/proofs/raw_caught_to_logger.sh` — seeds the multi-line/own-line/trailing-comma violation at a glob-matching path, asserts red, restores, asserts green. **RED-proven in both directions**: emptying the rule fails it at "seeded violation was NOT detected"; a match-everything rule fails it at "clean tree reported findings". Without that second half the proof is satisfied by a gate that fails on everything. shellcheck clean.
- [x] T016 [US3] Write fixture tests in `tests/unit/test_structural_rules.py` — asserts **set equality** between lines marked `// sg-expect` and lines ast-grep reports, not "each positive found": a rule matching every identifier satisfies the latter perfectly. Plus a scope test whose control scans the same bytes at an in-scope path, so "the excluded file reported nothing" cannot be satisfied by an inert scan. **RED step run against six mutations derived from the rule's constraints** (drop catch-clause, drop `console.log`, widen callee to any logger, widen to any console method, drop the test ignore, widen the files glob) — all six go red, baseline green.
- [x] T017 [US3] Implement `StructuralAnalyzer` in `scripts/review_plan_v2/gates/structural.py` conforming to `analyzers/base.py`, one `ast-grep scan --json` invocation per rule (the CLI takes a single `--rule`, and per-rule invocation is what gives each gate its own health).
- [x] T018 [US3] Report absent deterministic coverage. `run()` has **six** ways to produce an empty findings list and only one of them means clean, so the result carries `rules: list[RuleOutcome]` and `coverage_is_complete` is false unless every configured rule actually ran. `bool(self.rules)` is load-bearing — `all([])` is True, the same class of accident as the `promoted_at: null` bypass. Also added `coverable_file_count`: with no repo in the fleet carrying `rules/` yet, the banner would otherwise fire on every markdown-only PR, and a warning that always fires is one nobody reads by the third week — which costs exactly the signal FR-004 buys. Unknown (`None`) is treated as a gap, never as covered.
- [x] T019 [US3] Join the structural gate to the parallel analyzer wave in `orchestrator.py` — free, and already ordered before every reviewer (FR-012). Coverage gaps render as `[NO-STRUCTURAL-COVERAGE]` **above** `No findings.`, following the existing `[INCOMPLETE]` / `[DEAD-LEG]` precedent, and travel in the summary so `--agent` consumers can gate on them too.
- [x] T020 [US3] Supersede reviewer completeness speculation in `aggregator.py`. **Demotes and annotates rather than drops**: the detector is prose matching and therefore approximate, so a false positive must cost a finding its severity, not its existence. Gated on the enumerator having actually run — if it did not, the reviewer's hedge is the only answer anyone has, and replacing it with a confident count manufactures certainty. Requires both a hedge and a completeness noun; either alone matches ordinary prose constantly.
- [x] T021 [US3] Verify SC-003 end-to-end. **Measured 2026-08-14**: `68db762a` → **30 findings across 10 files**, `083084e5` → **0**, exactly as claimed, in **46 ms** over 354 TypeScript files. Recorded in `specs/003-gate-portfolio/audit/sc003.md` with the per-file distribution, the reproduce command, and the note that 30 counts matched *identifiers*, not `console.*` calls. Used `git archive` rather than worktrees so mtg-cube-ai was not mutated.
- [x] T021a **DONE 2026-08-16** — `tests/integration/test_structural_seam.py`, driving the real `orchestrator.run` over a real git repo, both directions: absent coverage reaches the report as `[NO-STRUCTURAL-COVERAGE]`, and a real violation reaches it as a finding. **My first version passed for the wrong reason and hid a broken fixture.** It searched stdout+stderr for `raw-caught-to-logger` and went green against a run reporting `No findings.` — the string matched a stderr warning naming the rule FILE PATH (`reviewer task security:rules/raw-caught-to-logger.yml failed`). Two compounding errors: the selector could match a record I did not mean (third instance of that trap here), and the fixture used `logger.error`, which the rule deliberately does NOT match — it anchors on `^console\.` because `\.(error|warn|log)$` alone would flag every logger in a repo. Fixed by verifying against ast-grep DIRECTLY (1 match) before trusting the integration test, and anchoring on the finding line: `[ACTIONABLE] src/lib/server/handler.ts:5 … [raw-caught-to-logger]`, exit 1. Original: [US3] Add an integration test driving the full `orchestrator.run` path with a structural finding and with absent coverage. The unit tests cover `StructuralAnalyzer` thoroughly and SC-003 covers the rule against a real checkout, but nothing yet exercises the seam between them — where `coverage_is_complete` becomes a `[NO-STRUCTURAL-COVERAGE]` line. Needs a diff fixture that adds both a `rules/` file and a violating source file, since `make_repo_from_diff` builds the repo from the diff alone.
- [x] T021b **DONE 2026-08-16 — and the precondition it names DID ITS JOB.** It asks to "confirm `raw-caught-to-logger` reports 0 on each repo's current HEAD before it is registered as blocking". Measured across the fleet: **mtg-cube-ai 0** (→ blocking), **companion-ai 4** (→ advisory). All four companion-ai hits are GENUINE — `console.error(..., err)` on the catch binding, server-side, no `ssr = false`, so not the documented false-positive shape. Registering blocking there would have shipped a gate red on day one into a repo that never asked for it. **The stated mechanism does not exist**: `propagate-skill.sh` copies ONE `SKILL.md` and knows nothing about `rules/` or `gates.yml`, so `scripts/propagate_gates.py` was written, with the tier DERIVED from the measured baseline and **no override flag**. Original: [US3] Propagate `rules/` to the fleet via `scripts/propagate-skill.sh` and confirm `raw-caught-to-logger` reports 0 on each repo's current HEAD before it is registered as blocking. Until this runs, every consuming repo prints `[NO-STRUCTURAL-COVERAGE]` on any diff containing code — correct, and load-bearing as the forcing function, but it should not sit there for weeks.

- [x] T021c [US3] Close out Phase 3 against a **completing** self-review. The first run scoped to the full 52-file diff starved 92/212 tasks; scoping to code+config (37 files) at concurrency 12 brought that to 3/152, and the three remaining are the reasoning-budget `empty (HTTP 200)` case, not starvation. Eight real defects fixed from the result, each RED-proven — see the commit. 45 of 69 actionable findings were the known "no tests exist" blind spot (the reviewer sees per-file chunks, so it cannot see the test file added alongside the code); verified by sampling rather than assumed. Two `.dockerignore` findings claiming a negation cannot re-include past an excluded parent were refuted empirically — the container passes 249/249 including both tests that read those re-included files.

**Checkpoint**: the fleet gets zero-cost completeness checking. Independently shippable.

---

## Phase 4: US2 — Verify checkable claims before showing them (P1)

**Goal**: no finding asserting a checkable fact reaches the developer unchecked.
**Independent test**: gold-set replay refutes 3/3 checkable-false, retains 3/3 real.

- [x] T022 [P] [US2] Encode the 10-finding gold set as a fixture in `tests/fixtures/gold_set_20260813.json`, each entry carrying its pre-classified verdict from `spec.md`
- [x] T023 [P] [US2] Write failing tests for the finding-envelope invariants in `tests/unit/test_finding_envelope.py` — port all 12 validated cases: the 4 **omitted-claim bypass guards** (absent claim + confirmed/refuted/unchecked/unverifiable all rejected — the bug review-plan-v2 found on this PR), the 4 null-claim/verdict-detail conditionals, and the 3 `additionalProperties: false` negatives at root, `$defs/claim`, and `$defs/check`. **RED step**: remove `claim` from `required` and confirm the four bypass guards fail.
- [x] T024 [US2] Implement `Claim` and `Check` types plus envelope validation in `scripts/review_plan_v2/verification/classify.py` against `contracts/finding-envelope.schema.json`
- [x] T025 [US2] Extend the reviewer structured-output contract to let a reviewer self-declare a claim, in `scripts/review_plan_v2/reviewers/base.py` and the prompt templates under `scripts/review_plan_v2/prompts/`
- [x] T026 [US2] Implement the `enumerate` check method in `scripts/review_plan_v2/verification/verify.py` — resolves `symbol_exists` / `symbol_absent` / `count` via ast-grep or ripgrep against the checkout
- [x] T027 [US2] Implement the `typecheck` check method in `scripts/review_plan_v2/verification/verify.py` — resolves `return_shape` / `predicate_result` by reading the declaration. This is the method that kills the thrice-recurring `describeThrown` false positive.
- [x] T028 [US2] Resolve `execute` claims to `unverifiable` in `scripts/review_plan_v2/verification/verify.py` pending the sandboxing decision, with an explicit log line so the gap is visible rather than assumed handled (FR-024)
- [x] T028a [US2] Enforce the untrusted-input boundary in `scripts/review_plan_v2/verification/verify.py` (FR-022/FR-023) — a `check.input` is accepted only as a registered rule id, a symbol path resolved against the checkout, or a type name, each allowlist-validated. Free-form command strings are rejected regardless of phrasing.
- [x] T028b [US2] Write the prompt-injection failure proof in `tests/proofs/verification_injection.sh` — craft a diff whose content steers a reviewer toward a claim carrying a shell command, assert the verifier rejects the input rather than running it. **RED step**: remove the allowlist and confirm the proof goes red.
- [x] T029 [US2] Attach the verification stage in `scripts/review_plan_v2/aggregator.py` after dedup, before tiering, so a claim is checked once rather than once per reviewer
- [x] T030 [US2] Drop `refuted` findings and mark `unverifiable` / `unchecked` in `scripts/review_plan_v2/output_format.py` (FR-002, FR-003)
- [x] T031 [US2] Make verification failure loud in `scripts/review_plan_v2/verification/verify.py` — a timeout or crash yields `unchecked`, never silent promotion to `confirmed` (FR-003 acceptance 4)
- [x] T032 [US2] Write the gold-set replay test in `tests/integration/test_gold_set_replay.py` asserting 3/3 refuted and 3/3 retained as separate assertions, not an aggregate rate (SC-002). **RED step**: stub the verifier to return `confirmed` for everything and confirm the refutation assertions fail.
- [x] T033 [US2] Write the executable failure proof in `tests/proofs/verification_stage.sh`

**Checkpoint**: the highest-leverage quality change is live.

---

## Phase 5: US4 — Every gate proves it can fail (P1)

- [x] T034 [P] [US4] Add a required **Failure Proof** field to `.specify/templates/plan-template.md` with the input-shape enumeration requirement (FR-008)
- [x] T034a [US4] Write failing tests for the shape-derivation validator in `tests/unit/test_shape_derivation.py` — feed it the pre-fix `raw-caught-to-logger` fixture (11 shapes, missing the is-the-catch-binding near-miss) and the pre-fix finding-envelope test set (4 conditionals, no field-absent case) and assert **both are rejected**. **RED step**: these are the two proofs that actually shipped broken; a validator that accepts either one is not a validator. Run before `derive_shapes.py` exists.
- [x] T034b [US4] Implement the shape-derivation validator in `tests/proofs/derive_shapes.py` (FR-008a): parse an ast-grep rule YAML, count relational constraints (`inside`/`has`/`follows`/`regex`/metavariable unification), and reject a fixture carrying fewer near-miss negatives than constraints; parse a JSON Schema, enumerate every field named in an `if`, and reject a test set that omits the field-absent case for any of them. Counts are derived from the artifact, never from an author-supplied list.
- [x] T035 [P] [US4] Write executable failure proofs for the four existing analyzers in `tests/proofs/{gitleaks,markdownlint,actionlint,shellcheck}.sh`
- [x] T036 [US4] Write the failure proof for the reviewer wave in `tests/proofs/reviewers.sh` — seed a planted bug and assert it is found. **This is the `reasoning_effort=none` regression guard**: that change made every metric improve while returning 0 findings on both planted-bug fixtures.
- [x] T037 [US4] Implement `tests/proofs/run-all.sh` to execute every registered proof and fail if any gate does not go red. It MUST invoke `derive_shapes.py` (T034b) against each proof first — a proof that goes red but under-covers its rule's constraints is rejected before its red result is credited.
- [x] T038 [US4] Add the proof runner to `.github/workflows/tests.yml` so a gate rendered permanently incapable of failing is caught in CI (FR-007 acceptance 3)
- [x] T039 [US4] Verify SC-004: run every proof, confirm each produces a red result, record in `specs/003-gate-portfolio/audit/sc004.md`

---

## Phase 6: US6 — Tiered, ordered, earned blocking (P2)

- [x] T040 **DONE 2026-08-16.** 25 tests. The FR-013 half is weighted toward the risk it creates: making probabilistic findings advisory means a run can print 20 findings and exit 0, so `test_exit_zero_with_advisory_findings_is_explained` is as load-bearing as the exit code itself. Mutation caught one CONFOUNDED test of mine — `test_an_ADVISORY_finding_does_not_trigger_it` stayed green with the `is_deterministic` check deleted, because every reviewer in gates.yml is BOTH probabilistic and advisory, so the fixture could not say which condition did the work. Isolated with a synthetic promoted (blocking) probabilistic gate.
- [x] T041 **DONE 2026-08-16.** Generalised the secret-only halt, which was FR-012 implemented for exactly one gate; the trigger now reads off the portfolio, so registering a new deterministic gate as `blocks` gets the short-circuit without another hand-written branch — and no branch can be forgotten, which is how the rule stayed true for gitleaks and silently false for the other four. **SC-006 measured end-to-end, not reasoned about**: a syntax-error file on a worktree branch produced `SHORT-CIRCUIT: gate 'ruff' is deterministic and declared blocking`, exit 1, and `calls.jsonl` grew by **0 bytes**. The first attempt at that measurement returned 0 bytes too — for the wrong reason (detached HEAD killed the run before any gate), which is why the output was read rather than the number trusted.
- [x] T042 **DONE 2026-08-16.** `exit_code_for` consults the portfolio; an advisory gate cannot set exit 1. Two safeguards, both mutation-proven: a repo with NO gates.yml keeps blocking on everything (adopting this tool must never be a silent downgrade), and an UNATTRIBUTABLE finding blocks (mis-classifying a deterministic finding as advisory is silent, the reverse is loud). The `[ADVISORY]` notice is the other half — FR-013 would otherwise trade one silent failure for another, since '20 findings, exit 0' reading like '0 findings, exit 0' costs exactly the signal the tier was meant to preserve. **This closed the T012 divergence**, and the pin that was supposed to catch it FAILED: it called `exit_code_for` with no registry, so it was pinning backward compatibility rather than the divergence it named, and stayed green through T042. A pin must exercise the same call shape production uses.
- [x] T043 **DONE 2026-08-16.** `log_gate_outcome` + `acceptance_for`, with their OWN allowlist separate from the per-call one. `addressed` is not invented: `context/rounds.py` suppresses a repeat finding only when the flagged code CHANGED since, which is the closest observable proxy for 'the developer agreed' — a finding that keeps returning untouched is one they declined to act on. Whether a finding was good is a fact about what happened next, so it cannot be measured inside one run. FR-021 enforced at the writer, because a telemetry file that has accumulated content is not fixable after the fact.
- [x] T044 **DONE 2026-08-16.** Both directions documented, including demotion — a gate that starts producing noise should go back to advisory rather than be deleted or bypassed, and `promoted_at`/`acceptance` are cleared so the next promotion cites fresh numbers. Records why the bar exists (markdownlint's 2541-finding entry) AND why it did not apply here (a zero baseline has no backlog to grant amnesty to).

---

## Phase 7: US5 — Reviewers see referenced definitions (P2)

Closes issues #18, #19, #20, filed 2026-04-30 and unbuilt.

- [x] T045 [P] [US5] Implement `always_include_files` standing context in `scripts/review_plan_v2/context/standing.py` (**#18**)
- [x] T046 [P] [US5] Implement 1-hop importer resolution in `scripts/review_plan_v2/context/related.py` (**#19**) — the direct fix for the `describeThrown` false-positive class
- [x] T047 [US5] Mark added test files explicitly in the reviewer payload in `scripts/review_plan_v2/change_manifest.py` — kills the recurring "no tests exist" finding (FR-010)
- [x] T048 [US5] Implement round-N finding memory in `scripts/review_plan_v2/context/rounds.py` (**#20**)
- [x] T049 [US5] Report dropped context in `scripts/review_plan_v2/context/budget.py` — never silently truncate (FR-011)
- [x] T050 [US5] Verify SC-005: replay the gold set with related-file context on and verification **off**, confirming the two false-positive classes are not generated at all. Record in `specs/003-gate-portfolio/audit/sc005.md`.

---

## Phase 8: US7 — Pristine vendoring, legible drift (P2)

- [x] T051 **DONE 2026-08-16.** Read `coleam00/skills` `.claude/skills/rules-check-drift/SKILL.md`; adopted/rejected recorded in `research.md`. ADOPTED its "checked, still true" section (reporting what was VERIFIED, so "no drift" is unprintable by a run that examined nothing), its explicit no-drift sentence, and naming the location + minimal action per row. REJECTED its semantic judgement: "is this rule still true" needs a model and is right to use one; ours is "do the bytes match", which Principle III forbids routing to a reviewer. Also rejected "when in doubt suggest nothing" — right for prose advice, wrong here, since an unclassifiable file is exactly what must be reported. Original: [US7] Read Cole Medin's `rules-check-drift` skill (`github.com/coleam00/skills`) before designing the report format; record what was adopted or rejected in `specs/003-gate-portfolio/research.md`
- [x] T052 **DONE 2026-08-16.** 12 tests in `tests/unit/test_manifest_drift.py`, weighted toward the ways "no drift" can be printed by a run that established nothing: a corrupt manifest, an empty file list, an unreadable file. Includes a test against the REAL repo, because a manifest that validates in a fixture while the shipped one covers 4% of the surface is the gap that actually mattered. Original: [P] [US7] Write failing tests for drift classification in `tests/unit/test_manifest_drift.py` — a locally modified file must be reported distinctly from an upstream-changed-but-clean one
- [x] T053 **DONE 2026-08-16 — it tracked 1 file out of 23 and reported no drift.** Now 22, and provenance decides membership: a `.claude/skills/*/SKILL.md` is vendored only if it carries a `source:` field. `review-plan-v2` has none — it is ours, `specify init` will never touch it, and flagging it would be false. A report that cries wolf on a file nobody will overwrite is one people stop reading, costing the nine genuine ones. Original: [US7] Extend `.specify/integrations/speckit.manifest.json` to hash every vendored file, reading provenance from existing `metadata.source` frontmatter (FR-015, SC-007)
- [x] T054 **DONE 2026-08-16.** `scripts/speckit_drift.py`: pristine / modified / missing / untracked, all named. `untracked` counts against clean — a file the manifest never saw cannot be classified, and calling that "no drift" is the defect this portfolio exists to close. Deterministic by design (sha256), never a reviewer. Original: [US7] Implement pristine/modified classification in `scripts/speckit_drift.py`
- [x] T055 **DONE 2026-08-16.** Both version lookups fell back to `"unknown"` on failure, and `"unknown" == "unknown"` compared EQUAL → `needs_update=false` → green. An API outage, a revoked token or a renamed asset made the drift check report "you are up to date" from a lookup that never happened. Both now fail the run with a message saying the run checked NOTHING. Original: [US7] Fix the silent-failure in `.github/workflows/check-speckit-update.yml` — a run that produces no notification must fail, not pass (FR-016)
- [x] T056 **DONE 2026-08-16** — `audit/sc008.md`, verified by MODIFYING a real vendored file rather than reasoning: modified → exit 1 + named path + stated consequence; restored → exit 0; `git status` clean afterwards. The audit surfaced three things reasoning had not, including that rebuilding a manifest from disk baselines whatever is there — `.specify/templates/plan-template.md` carries a deliberate local edit that the rebuild recorded as "pristine", silencing the file most at risk. `local_edits` records the human judgement hashing destroyed. Original: [US7] Verify SC-008 in `specs/003-gate-portfolio/audit/sc008.md` — modify one vendored file under `.claude/skills/`, confirm `scripts/speckit_drift.py` names it distinctly from upstream-changed-but-clean files; restore
- [x] T057 **DONE 2026-08-16** — overlay pattern and never-edit-in-place in `quickstart.md`, including the rule that a rebuild must run IMMEDIATELY after `specify init`, never at an arbitrary moment, because rebuilding on top of an unrecorded local edit is how that edit stops being visible. Original: [US7] Document the overlay pattern and the never-edit-in-place rule in `specs/003-gate-portfolio/quickstart.md`

---

## Phase 9: US8 — Sweep remaining skills for silent failure (P3)

- [x] T058 **DONE 2026-08-16** — `audit/skill-sweep.md`. Skills are prompt documents with no exception handling to audit; the question asked of each was whether it tells its caller when it could not do its job. `review-plan/SKILL.md` is the repo's strongest example (SKIPPED / empty / `UNUSABLE:` / `TRUNCATED:` leg outcomes, and "never present a no-op run as a completed review"). The nine vendored `speckit-*` skills are upstream text, out of scope per the overlay rule. Original: [US8] Audit each skill in `.claude/skills/` for the silent-failure class, recording the failure signal and whether it is distinguishable from success, in `specs/003-gate-portfolio/audit/skill-sweep.md`
- [x] T059 **DONE 2026-08-16.** 33 swallowed handlers in `scripts/`, all read individually. **My first pass was a heuristic that reported 0 silent out of 33** — an implausibly clean result, and this repo's own rule is to distrust exactly that. It was junk: `"#" in above` matched any nearby comment and the signal check scanned the whole enclosing function. Recorded in the audit, because a check passing for a reason unrelated to what it claims is precisely what the sweep was looking for, produced by the tooling written to find it. Real pass: **31 adequately signalled** (each makes its degradation observable to its caller — table in the audit), **2 genuine gaps**. F1 fixed here; F2 filed. Original: [US8] Audit each script in `scripts/` for swallowed exceptions and warn-only paths that never escalate, appending to `specs/003-gate-portfolio/audit/skill-sweep.md`
- [x] T060 **DONE 2026-08-16.** Two gaps found. **F1 was FIXED rather than filed** — an analyzer exiting 0 with unparseable JSON reported CLEAN (measured: `skipped=False, findings=0`), the half T005e/#38 did not cover. `parse_output` now raises `AnalyzerOutputError`; `base.run()` converts it to a SKIP so the wave still survives one broken analyzer AND the gap is visible; wrong-SHAPE JSON raises too, since a schema change lands exactly there. A closed gap beats a tracked one. **F2 filed as #47** (a reviewer's unparseable response is uncounted) because it needs a design decision first: reviewer findings are advisory since FR-013, so it cannot simply fail the run. Original: [US8] File a GitHub issue per gap found, labelled `bug` (SC-009)

---

## Phase 10: Polish & cross-cutting

- [x] T061 **DONE 2026-08-16** — `tests/unit/test_run_health.py`, 10 tests. Pins BOTH halves, because neither alone is the fix: the leg is NAMED (a non-zero exit with no explanation sends the reader to source) and the run does not report success (a banner no script reads does not stop `review-plan-v2 && git push`). Equal weight on the anti-vacuous direction, which is why the banner had to be rewritten on 2026-08-14: it fired on two merely STARVED legs and told the operator their config was broken. Includes the backward-compat case — a summary lacking `attempted` must DERIVE it, since defaulting to 0 silences the banner on exactly the runs most likely to be broken. Original: [P] Add the SC-010 regression guard in `tests/unit/test_run_health.py` — a run with a dead provider leg exits non-zero and names it. Asserts what #27 fixed rather than assuming it holds.
- [x] T062 **DONE 2026-08-16** — `tests/unit/test_telemetry_content.py`, 7 tests, covering BOTH writers (`log_call` and the T043 `log_gate_outcome`). DERIVED from the allowlists themselves rather than a remembered list of forbidden names, so a `prompt_preview` added tomorrow is covered without anyone remembering. `calls.jsonl` is the one artefact here that cannot be un-shipped — by the time a leaked prompt body is noticed it exists on every machine that ran the tool — so the guard is at the WRITER and a widened allowlist fails HERE. Original: [P] Add an FR-021 telemetry-content guard in `tests/unit/test_telemetry_content.py` — assert no prompt body, diff content, or message content is ever written to `calls.jsonl`
- [x] T063 **DONE 2026-08-16 — the blocker was unstarted work, not an external dependency.** [mtg-cube-ai#2110](https://github.com/jabelk/mtg-cube-ai/issues/2110) was fully specified and one file, so it was fixed rather than waited on: mtg-cube-ai [#2121](https://github.com/jabelk/mtg-cube-ai/pull/2121), merged to `staging` as `66890d91` (the issue stays open until `staging` promotes — `Closes` only fires on the default branch). **SC-003b: 0 files where a comment-handling step deletes code**, measured with AST TOKEN positions as ground truth. Before: the naive strip removed **11,648 characters of real code** from `+server.ts` inside a 33,904-char span. The remaining stripper (the state machine in `turn-cost-total-usage.guard.test.ts`) deletes ZERO code from the one file it reads; it mishandles a regex literal in a file it never scans, and its raw-count assertion already fails loudly if its blind spot ever hides a call. **The measurement went wrong twice before it was trusted, in both directions.** First run: 284 of 285 files — `getChildren()` returns JSDoc as a CHILD NODE, so every docstring counted as code; that is the implausibly-unclean twin of the ~170-span error #2110 already records. It now self-tests its ground truth before measuring, and that self-test caught a wrong expectation of mine on its first execution (20 code chars, not 12 — the tokens of both swallowed lines count and the whitespace between them does not). **And the fix shipped the same bug one layer down**: the `.svelte` script extraction was a regex, which lifts script content out of an HTML comment, so a commented-out block read as live. Now parsed with `svelte/compiler`. Fifth instance of pattern-matching-where-structure-was-the-question in that single file. 4 of 4 mutations killed, including one proving the end-to-end control goes through `offenders()` — the in-memory controls pass either way, so only that one fails if someone reinstates a strip. Original: Re-verify SC-003b: run the portfolio's scanners over the proving ground's `staging` and confirm 0 files where a comment-handling step deletes code (down from 4). Depends on [mtg-cube-ai#2110](https://github.com/jabelk/mtg-cube-ai/issues/2110) landing.
- [x] T063b **CLOSED 2026-08-16 — the premise no longer holds; no cleanup needed.** The task says 180 findings across 15 shell files with `SC1091` dominating. Re-measured: **40 findings across 8 files, and ZERO actionable** (17 info, 23 nit). shellcheck maps only `error` level to actionable, so the residual never blocked anything, and shellcheck was already registered `blocking: blocks` in T011 — which is what this task existed to enable. Nothing to drive to zero that would change any outcome. Recorded rather than re-done, since the numbers in the original text are three-figure and misleading. Original: Drive the shellcheck residual to zero across the 15 shell files (180 findings, `SC1091` not-following-sourced-file dominating — resolvable with `# shellcheck source=/dev/null` or `-x`), then register `shellcheck` as **blocking**. Measured 2026-08-14 alongside T063a.
- [x] T063c **ALREADY SATISFIED by T011 (2026-08-16); no separate change needed.** This task assumed gates.yml would register gitleaks and actionlint as advisory first. It did not: all six deterministic gates entered BLOCKING on day one, because FR-014's advisory tier exists to absorb noise and the measured actionable baseline was ZERO for all five analyzers. Verified against the shipped registry — gitleaks, actionlint, shellcheck and markdownlint all read `blocking: blocks`, enforced by `test_no_probabilistic_gate_blocks` and the portfolio loader. Original: Register `gitleaks` and `actionlint` as **blocking** in `gates.yml`. Both measured at a repo-wide baseline of **zero** on 2026-08-14 (actionlint after this feature fixed the one pre-existing SC2129 in `check-speckit-update.yml`), so they satisfy the flip-at-zero rule today and are the first two gates eligible for it.

  **Promotability baseline, all four deterministic analyzers, measured 2026-08-14** — nobody had measured this, and FR-014 cannot be satisfied without it:

  | Gate | Repo-wide findings | Blocking-eligible? |
  |---|---|---|
  | gitleaks | 0 | **yes, now** |
  | actionlint | 0 (was 1) | **yes, now** |
  | markdownlint | 176 (was 2541) | after T063a |
  | shellcheck | 180 | after T063b |

- [x] T063a **DONE 2026-08-16 — residual 177 → ZERO, and the premise was stale in the WRONG direction.** The task says 176 findings over 39 files; re-measured it was **316 over 51**. It GREW, entirely from my own spec-003 writing — a residual is not self-maintaining, so `test_the_markdownlint_baseline_stays_at_zero` now holds it (asserted at zero, not under a threshold: a threshold is a budget and a budget gets spent). **`markdownlint --fix` CORRUPTED CONTENT and I nearly shipped it**: it rewrote the issue reference `#13` into `# 13`, an H1, via MD018. Caught by inspecting the 36-file diff for content changes rather than trusting the tool — the repo's own bulk-edit guardrail. The URL rewrites were verified 1:1 (equal +/- per file, no lines lost). MD036's last two hits were FALSE POSITIVES (a bolded conclusion, an italicised quotation — neither a heading) and the rule cannot tell those apart, so it is disabled with that reason recorded, not 'fixed' into a meaning change. Prompt bodies under `prompts/` are excluded via `.markdownlintignore`: adding an H1 changes what the reviewer model receives. Original: Drive the markdownlint residual to zero across the 39 remaining affected files (176 findings after `.markdownlint.json` disables MD013/MD060 and this feature's own files were cleaned; MD032 blanks-around-lists dominates and does change rendering in strict parsers), then register `markdownlint` as **blocking** in the gate registry. Measured 2026-08-14: 2541 errors on a clean tree made this gate unpromotable under FR-014, and a permanently-red check is Principle I's failure mode — flip to blocking only at a baseline of zero, never before.
- [x] T064 **DONE 2026-08-16.** `scripts/propagate_gates.py --apply`: dry-run by default (it writes into other people's repositories), never overwrites an existing `gates.yml`, and skips linked worktrees detected STRUCTURALLY (git-dir ≠ git-common-dir) — `companion-ai-wt-milestones` is a top-level sibling directory, so a path-based `worktrees` filter misses it, which the first dry run demonstrated. Applied to the 2 repos with in-scope files; the other 9 are reported BY NAME as not-applicable rather than counted. Three defects caught before or during the write, each by checking rather than assuming: the generated `failure_proof` pointed at a README.md that does not exist (every propagated registry would have been REFUSED by the loader); the generated proof scanned the fixture IN PLACE, which the rule's own `ignores:` excludes, so it correctly failed with "seeded violation was NOT detected"; and it omitted `unset CDPATH`, so `$(cd … && pwd)` returned the path twice and every derived path was garbage. Both repos verified end-to-end: registry loads, proof exits 0, only the two new paths appear in `git status`. Original: Propagate `rules/` and the gate registry to downstream repos via `scripts/propagate-skill.sh` (Principle VII)
- [x] T065 **DONE 2026-08-16.** README gains the portfolio model, the tier table and the ROUTING table; the skill gains corrected output semantics. **The skill was actively wrong**: it said "`[ACTIONABLE]` lines block the push", which FR-013/#42 made false for reviewer findings — live guidance I had been following all session. It now maps each line type to whether it blocks, and states that exit 0 alone never means "reviewed and clean". **Found while doing this: my T063a "markdownlint residual ZERO" claim in #50 was scoped narrower than stated.** `markdownlint .` does not descend into dot-directories, so `.claude/**` and `.specify/**` were never linted — 12 files, 139 findings, invisible. 11 are VENDORED (excluding them is correct per the T057 overlay rule) and 1 was ours. The exclusion is now DECLARED in `.markdownlintignore` with the reason rather than inherited from glob behaviour, the baseline test globs the dot-dirs explicitly, and an anti-vacuous companion asserts the glob matches real files — because an accidental exclusion and a deliberate one produce identical clean output. Fourth instance of the scope trap here. Original: Update `README.md` and the `review-plan-v2` skill with the portfolio model and the routing table
- [x] T066 **DONE 2026-08-16** — traceability sweep recorded at the end of this file. No drift requiring a change: zero orphan ids, and the nine FRs plus SC-001 that tasks.md never CITES were each verified against shipped work. Two came back "NO EVIDENCE" on the first pass and both were my own bad check (wrong path, wrong string) — re-verified rather than filed, since a sweep that reports false gaps spends the reader's trust on noise. Also caught an extraction artefact: a naive `FR-[0-9]+` scan reports FR-026, which is not a requirement here at all but a quoted mtg-cube-ai code comment. Original: Run `/speckit.analyze` and resolve any spec/plan/tasks drift

---

## Dependencies

```text
Phase 1 (Setup)
   └─> Phase 2 (Registry — blocks everything)
          ├─> Phase 3 (US3)  ──> Phase 4 (US2)     # US2 reuses US3's enumerate check
          ├─> Phase 5 (US4)                        # independent of US2/US3
          └─> Phase 6 (US6)
Phase 7 (US5), Phase 8 (US7), Phase 9 (US8)        # independent of each other
Phase 10                                            # after all
```

US7 and US8 touch no review-pipeline code and may run in parallel with Phases 3–7 by a
second worker.

## Parallel opportunities

- **Phase 1**: T002, T003, T004 together.
- **Phase 3**: T013, T014 together.
- **Phase 4**: T022, T023 together.
- **Phase 5**: T034, T035 together.
- **Phase 7**: T045, T046 together.
- **Phase 10**: T061, T062 together.

## Independent test criteria

| Story | Independently testable by |
|---|---|
| US1 ✅ | `/speckit.plan` produces a Constitution Check citing numbered principles; zero placeholders |
| US3 | rule enumerates 30 at `68db762a`, 0 at `083084e5`, across all shapes |
| US2 | gold-set replay: 3/3 refuted, 3/3 retained |
| US4 | every proof run produces a red result |
| US6 | deterministic failure ⇒ zero provider calls in telemetry |
| US5 | two false-positive classes not generated with context on, verification off |
| US7 | one locally modified vendored file is named distinctly |
| US8 | every skill has a recorded silent-failure answer |

## Suggested MVP

**Phases 1–3 (T001–T021)**. Delivers zero-cost deterministic completeness checking to the
whole fleet, on the one capability already validated end-to-end in Phase 0. Phase 4 (US2)
is the highest-value follow-on and the reason the spec exists, but Phase 3 ships value on
its own and builds the registry US2 plugs into.

## Progress

- [x] **US1 — constitution ratified v1.0.0**, zero placeholders, Constitution Check PASS
- [x] Phase 0 research: engine chosen and validated by measurement
- [x] Contracts written and their invariants verified (12/12, incl. the 4 omitted-claim bypass guards)
- [x] mtg-cube-ai#2110 filed for the live comment-stripper defect
- [x] **Constitution amended to v1.1.0** — Principle II gains the shape-derivation clause, after the finding-envelope schema became the fifth vacuous-control failure
- [x] **Phase 3 (US3) shipped and merged** — `a877efee`. SC-003 measured end-to-end: 30 sites / 10 files at `68db762a`, 0 on `staging`, 46ms over 354 TS files.
- [x] **Phase 4 (US2) complete** — SC-002 met: **3/3 checkable-false refuted, 3/3 real retained**, asserted separately, replayed against a hermetic vendored corpus so it runs identically on a laptop, in CI, and in the container. 398 tests + 3 proofs green in both host and image.
- [x] **Phase 7 (US5) COMPLETE — T045–T050.** Closes #18, #19 and #20.
- Implementation: counts asserted by grep, not by hand — see the header of this file

### What Phase 7 measured, and the half it could not

The "no tests exist" false positive — four occurrences in one session, all
against diffs whose test files were IN the diff — is closed, and closed by
measurement rather than by reasoning. Three live arms on one diff, same model:

| arm | manifest | context | the tests reviewer said |
|---|---|---|---|
| C (pre-T047) | off | on | "the diff adds **no test** covering it" — FALSE, actionable |
| B | on | off | "**deck-dedup.test.ts is in this diff**, but …" — TRUE |
| A | on | on | same observations at `nit`; exit 0 |

The finding did not vanish; it became true. The reviewer stopped asserting the
absence of tests and started assessing whether the tests present are adequate,
which is the job it is actually good at.

The `describeThrown` return-shape class (G6) was **not reproduced in the
control**, so it is recorded UNPROVEN rather than closed: a class that never
appears in arm C cannot be shown to be absent from arm A. Details and the
follow-on needed to reproduce it are in `audit/sc005.md`.

### T048: the suppression rule, and the two ways to get it wrong

Dropping a finding is the most dangerous thing this tool does, so suppression
requires TWO conditions, not one: the finding must be fingerprint-identical to an
earlier round AND **the code it points at must have changed since**. Without the
second, a finding the developer ignored disappears on round 2 — the feature
becomes a way to make a real problem vanish by running the tool twice.

Two design bugs, both caught by tests rather than by review:

- **Re-recording a suppressed finding with the CURRENT anchor** makes it read as
  unaddressed one round later, so it comes back. The feature undoes itself on
  run three, and no two-round end-to-end test can see it. Fixed by carrying the
  record forward with its ORIGINAL anchor and refreshing only recency, which
  needed `first_round` and `round` split into separate fields.
- **Dropping it from history entirely** ages it out and resurrects it.

Every suppression is NAMED in the output (the FR-011 rule) and `--force-full`
recovers all of them, so nothing is invisible.

### The proof found four decorative tests in my own suite

`tests/proofs/context_mutations.sh` breaks one guard at a time and asserts the
named test goes red. Writing it caught four tests that passed while measuring
nothing:

- a containment test that passed with containment DELETED — its
  `../../../../etc/passwd` had too many `..`, so the path did not exist and was
  rejected as unresolved before containment was ever consulted;
- an empty-render test whose subject was a redundant early return;
- an end-to-end manifest test reading the WRONG PROMPT, because `caller.ts`
  matched the prompt for `caller.test.ts` — whose context block cites that path.
  This feature made the old matching ambiguous, so the test degraded the moment
  the thing it tested started working;
- a delivery test needling `errMessage`, which appears in the changed line
  itself and so was present whether or not context was attached.

All four asserted true things. None measured what its name claimed.

### What Phase 4 measured, and what it deliberately did not

| Gold-set class | n | Outcome |
|---|---|---|
| real | 3 | retained; **1 affirmatively confirmed**, not merely un-refuted |
| checkable_false | 3 | refuted — `enumerate` ×2, `typecheck` ×1 |
| false_not_checkable | 1 | `unverifiable` — needs the TS compiler, deferred by FR-024 |
| test_blindness | 3 | untouched; US5's measure, fixed by FR-010 rather than by refutation |

G3 is the entry worth defending. It is FALSE in fact — the TypeScript parser
does produce a `CallExpression` for `a?.b()` — but settling that means running
the compiler, and marking it `refuted` would assert a verification that never
happened. The replay pins it at `unverifiable`, so a change that flips it
without shipping a sandbox fails the suite.

Two anti-vacuous controls guard the headline number from opposite directions,
because the classes fail opposite ways: a verifier that refuses everything
scores 3/3 on false findings while destroying the review, and one that confirms
everything scores 3/3 on real findings while doing nothing at all. Both
degenerate verifiers are exercised as stubs in `test_gold_set_replay.py`.

### Defect found by Phase 4's own proof

`tests/proofs/verification_stage.sh` failed on first execution and was right to.
A `claim: null` judgment finding one line from a false-claim finding merged into
it under the dedup window; the claim was refuted and **both** were deleted. Dedup
was already lossy there — it keeps one message — but verification turned lossy
into silently destructive. Fixed in `_overlap`: a checkable finding and a
judgment finding never merge, because a merged group carries one verdict and no
single verdict is right for both. Pinned by
`test_a_judgment_finding_is_not_merged_into_a_checkable_one`, with the
still-merge cases kept as controls.

### Correction to the injection proof's own claim

The RED step on `verification_injection.sh` showed the canary file does **not**
fire when the allowlist is deleted. It cannot: no code path hands a string to a
shell, so the architecture is the first layer of defence and the allowlist is
the second. What the mutation actually broke was quieter — an injected string
became a search needle, matched nothing, and the claim came back **refuted**,
which deletes the finding. So the regression the proof detects is corrupted
verdicts, and the acceptance checks are what detect them. The header now says
so and the canary is labelled a backstop, not the detector. Leaving it called
"the load-bearing assertion" would have been this spec's own defect class: a
check that passes for a reason unrelated to what it claims to prove.

## T066 traceability sweep — FR/SC coverage (2026-08-16)

`/speckit.analyze`'s question is whether spec, plan and tasks still agree. Run
as a measurement rather than a reading:

**No orphans.** Every `FR-`/`SC-` id cited in tasks.md exists in spec.md. That
direction is the dangerous one — a task citing a requirement that was deleted
looks like coverage and is not.

**One extraction artefact, not a gap.** A naive `FR-[0-9]+` sweep of spec.md
reports FR-026, which is not a requirement of this spec at all: it appears
inside a QUOTED mtg-cube-ai code comment
(`// delegate to /api/workflow/tools/* which enforces ownership (FR-026)`).
Anchoring on `^- \*\*FR-NNN\*\*` gives 25 real requirements. Worth recording
because the naive count is the one a reader would reach for.

**Nine FRs and SC-001 are never CITED by id in tasks.md.** All were checked
individually against shipped work rather than assumed:

| requirement | covered by | verified |
|---|---|---|
| FR-001 constitution has no placeholders, states four principles | `.specify/memory/constitution.md` | 0 placeholders; principles I Fail-Visible, II Provable Failure, III Deterministic Answers, IV Uncensored Measurement all present |
| FR-005 identical results across formatting variants | `rules/fixtures/raw-caught-to-logger/` | trailing-comma and multi-line variants present |
| FR-006 parse-aware comment handling | `context/code_scan.py` | `blank_noncode` masks same-length, never strips |
| FR-009 reviewers receive referenced definitions | `context/related.py` | US5, `[Referenced definitions]` block |
| FR-017 vendored files never hand-edited | `quickstart.md` §"never edit in place" | T057 overlay pattern + `local_edits` |
| FR-018 run health on every run | `orchestrator.py` | `gate portfolio: …` prints on success too |
| FR-019 never size a limit from data collected under it | practice | the `max_tokens` lesson; recorded in `rpv2-reasoning-budget` |
| FR-020 no gate writes the dataset that judges it | gold-set harness | fixtures are checked in, never regenerated by a run |
| SC-001 constitution + Constitution Check | Phase 1 | `/speckit.plan` produced a numbered Constitution Check |

**Two of those rows were "NO EVIDENCE" on my first pass, and both were MY bad
check** — a wrong path (`memory/` for `.specify/memory/`) and a wrong string
(`never-edit-in-place` for "never edit in place"). Re-verified rather than
filed. A drift sweep that reports false gaps is worse than none: it spends the
reader's trust on noise.

**Conclusion: no spec/plan/tasks drift requiring a change.** The gap is
citation, not coverage — which is why this table exists, so the next sweep can
confirm by grep instead of re-deriving it.
