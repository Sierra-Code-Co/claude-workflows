# Specification Quality Checklist: /review-plan v2

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-04-27
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
  - **Caveat**: This is fundamentally a developer tool that orchestrates LLM APIs and static analyzers. Specific tool names (DeepSeek R1, Claude Sonnet, gitleaks, markdownlint, actionlint, shellcheck) appear in the spec but are framed as **defaults** or **examples**, with FRs requiring the underlying capability to be **provider-pluggable** (FR-003) and analyzer-pluggable (FR-005). This matches the spec template's intent.
- [x] Focused on user value and business needs
  - Each User Story leads with developer-facing value (pre-push, no rate limits, multi-perspective review, drop-in replacement, etc.) before any implementation discussion.
- [x] Written for non-technical stakeholders
  - **Caveat**: Hard ceiling — the audience IS developers. Background section names CR rate-limit symptoms in human terms; user stories describe developer workflows.
- [x] All mandatory sections completed
  - User Scenarios & Testing ✅, Requirements ✅, Success Criteria ✅. Out of Scope explicit.

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
  - 20 functional requirements, each independently verifiable. Each tagged MUST/SHOULD per priority.
- [x] Success criteria are measurable
  - 10 success criteria with concrete numbers (80% catch parity, <2 min runtime, <$0.20/run, 0 rate-limit errors over 100 runs, etc.)
- [x] Success criteria are technology-agnostic (no implementation details)
  - **Caveat**: SC-001 references "CodeRabbit CLI" as the comparison baseline. This is unavoidable — CR is the empirical baseline we're trying to match without rate limits. SC-003 mentions cost in USD which is also unavoidable for a tool that uses paid APIs.
- [x] All acceptance scenarios are defined
  - Each User Story has 2-3 Given/When/Then scenarios.
- [x] Edge cases are identified
  - 11 edge cases covering empty diff, large diff, binary files, generated files, missing keys, network failures, missing config, missing analyzers, no upstream, invalid yaml.
- [x] Scope is clearly bounded
  - Explicit "Out of Scope (v2)" section listing 7 things deferred (remote execution, PR-side bot, RAG learnings, autofix, UI, replacing existing /review-plan, multi-language).
- [x] Dependencies and assumptions identified
  - 8 assumptions documented.

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
  - Each FR maps to at least one acceptance scenario or success criterion.
- [x] User scenarios cover primary flows
  - 7 user stories, P1-P3 priorities. P1 stories alone constitute MVP (pre-push runs without rate limits, specialized parallel reviewers, project-aware via .coderabbit.yaml). P2 adds drop-in CLI compatibility + static analyzers. P3 adds cascade + auto-pause.
- [x] Feature meets measurable outcomes defined in Success Criteria
  - SC-001 through SC-010 define measurable outcomes; each maps to one or more user stories.
- [x] No implementation details leak into specification
  - **Caveat**: Same as Content Quality — tool/model names appear as defaults but functional requirements keep them pluggable.

## Resolved Ambiguities (decisions made during spec authoring)

The spec resolves these without `[NEEDS CLARIFICATION]` markers, using stated assumptions:

1. **Default LLM provider mix**: DeepSeek R1 (broad-pass) + Claude Sonnet (cascade on high-risk). Rationale: matches the audit's "intentional drift" pattern in 11 projects + matches the cost/quality cascade described in earlier session research. Pluggable per FR-003.
2. **Static analyzer set**: gitleaks + markdownlint + actionlint + shellcheck. Rationale: matches CR's bundled set; matches what's already documented in claude-workflows' own `.coderabbit.yaml` `tools` section. Pluggable per FR-005.
3. **Config source**: `.coderabbit.yaml` (read-only — CR's schema is honored as-is per FR-004) **plus** a separate `.review-plan-v2.yaml` for v2-specific fields (`high_risk_paths`, `max_concurrency`, `auto_pause_n`, `dedup_line_window`). Rationale: extending CR's schema would break compatibility with the upstream PR-side bot, so v2 keeps a stable read-only `.coderabbit.yaml` and puts review-plan-v2-only knobs in the second file. Per FR-016 / ADR-0008.
4. **Auto-pause-N default**: 3. Rationale: matches PR-Agent's `auto_pause_after_reviewed_commits: 3` precedent.
5. **Severity tiering**: 3-tier (`actionable` / `nit` / `info`). Rationale: matches CR's distinction; binary actionable/non-actionable was considered but loses signal on truly informational findings.
6. **Categories**: 10-tier (`bug` / `security` / `correctness` / `tests` / `consistency` / `style` / `prose` / `docs` / `secrets` / `nit`). Authoritative list lives in `types.py` + `aggregator.SOFT_CATEGORIES`. Rationale: covers reviewer specializations + analyzer outputs + the soft-category subset used by aggregator severity demotion.
7. **Existing /review-plan skill (spec/plan review)**: NOT replaced. v2 is for diff review; existing skill stays for spec/plan review. Shared infrastructure is acceptable; collision is forbidden per Out of Scope.
8. **Output format**: Mirror `coderabbit review --plain` plain-text format. Rationale: drop-in compatibility with downstream tooling and existing CLAUDE.md instructions.

## Open Questions for Plan Phase

These are appropriate for `/speckit.plan` to resolve, not the spec:

- Architecture: single-process orchestrator vs. shell script that exec's subprocesses?
- Reviewer prompts: file-per-prompt vs. structured prompt library?
- API call infrastructure: roll-our-own vs. LiteLLM or similar abstraction?
- Diff capture: `git diff` shell-out vs. libgit2 binding?
- Output streaming: results streamed as they arrive vs. buffered until aggregation?
- Issue #13 (DeepSeek R1 in v1 docs vs. only OpenAI+Gemini in v1 script): resolve as part of v2 plan; v2 spec assumes DeepSeek IS available because v1 docs say so AND user has DEEPSEEK_API_KEY noted in audit memory.

## Notes

- Items marked incomplete require spec updates before `/speckit.clarify` or `/speckit.plan`.
- All checklist items pass on first iteration. Spec is ready for the planning phase.
- This spec is unusually detailed because it codifies a session's worth of design discussion. The plan phase will whittle it down to implementation tasks.
