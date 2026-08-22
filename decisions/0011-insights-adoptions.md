# 0011 — 2026-08 insights-report adoptions: evidence rules, scope discipline, batched review, /ship extraction

**Status:** active
**Date:** 2026-08-21
**Tags:** claude-md, workflow, review

## Context

The 2026-08-21 Claude Code insights report (506 messages / 19 sessions) surfaced recurring, evidence-backed friction: gate commands run piped locally masked exit codes so failures only appeared in CI; verification was sometimes claimed without being performed ("did you actually check databases"); removal requests got answered with elaborate rewrites (a contract clause took two extra strip-it-back rounds); serial CodeRabbit fix-and-recheck loops ran to six rounds, and a round-3 hardening pass reintroduced a previously-fixed parsing bug; ad-hoc perl/sed edits mangled an import alias and clobbered a test file. The report proposed CLAUDE.md additions, hooks, and a `/ship` custom skill.

Several proposals duplicated existing machinery, so each was triaged rather than pasted in — re-deciding the review-round pattern in particular is exactly the ADR trigger.

## Decision

**Adopted into the global CLAUDE.md** (all tagged ADR-0011 inline):

1. *Verification* sharpened with two mechanisms it lacked: pipes mask exit codes (run gates unpiped or check `PIPESTATUS`), and verification claims must carry the command + raw output or say NOT VERIFIED.
2. New *Scope Discipline* section: minimum change; removal means removal; propose additions in prose; never re-raise declined decisions.
3. *Waiting for PR review + CI* gains **batch the review round**: enumerate every CR comment in a table first, fix all real ones in one commit, and regression-check earlier rounds' fixes before pushing.
4. New *Prose style* section, deliberately scoped to personal/client-facing drafts — the evidence was letters and contracts, not PR bodies.
5. New *Editing files* section with a nuance the report's blanket ban missed: ad-hoc stream edits on source files are forbidden, but scripted stream edits inside committed, tested, fail-loud scripts (the template's drift re-apply) remain legitimate.
6. *Browser walkthroughs are the default for web-UI work* (user-reported friction, same day): with Claude in Chrome available, walking the affected flows in a real browser is part of verification, unprompted — API-level smoke tests verify the API, not the feature. Also enforced as a `/ship` gate item.

**Adopted as template work:** `/ship` — but as an *extraction* of `/feature` Phase 6 into a standalone skill (the small-fix pipeline: branch → failing test → unpiped gates → PR → batched CR → merge → per-project promote/verify), with `/feature` delegating to it. One source of truth for shipping mechanics; promote/verify steps read from the project's CLAUDE.md because staging pipelines are per-project.

**Declined:**

- *PreToolUse hook blocking perl/sed* — cannot distinguish ad-hoc edits from legitimate scripted ones; would have false-positived four times on the day it was proposed. The CLAUDE.md rule carries the intent.
- *Global "PR Workflow" block* — already encoded across the pre-push and PR-wait sections plus per-project promote docs; restating it globally with staging steps would be wrong for repos without staging.
- *Headless nightly CR triage* — overlaps ScheduleWakeup loops and the schedule skill; a third mechanism for the same shape.
- *The two "horizon" builds* — filed as backlog ideas instead (#63 evidence-gated promotion, #64 adversarial PR swarm). #63 is this repo's gates.yml philosophy extended to promotion and deserves a speckit feature when picked up.
- *PostToolUse format/lint hooks* — right idea, wrong repos here; belongs per-project in the TS/Python app repos, and the report's hook snippet uses a stale env-var interface, so generate with the update-config skill when wanted.

## Consequences

- The global CLAUDE.md grows four sections/amendments; the symlink propagates them to every machine on pull.
- `/ship` lands in the template and reaches the fleet with the pending spec-kit v1 propagation wave.
- Review rounds are expected to converge in 1–2 batched passes; a six-round serial grind is now a process violation, not a norm.
