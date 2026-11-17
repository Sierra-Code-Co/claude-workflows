# Claude Code Workflows

The working infrastructure [Sierra Code Co](https://github.com/Sierra-Code-Co) uses to run [Claude Code](https://claude.com/claude-code) across a fleet of ~20 real projects — published as teaching material.

This is not a demo repo. Everything here is in production use: the spec-driven development chain, the multi-model review gates, the decision records, and the propagation tooling that keeps every project's config consistent. It's published because the best way to evaluate a workflow is to read the one someone actually lives in — including the parts that failed and the postmortems that explain why.

## The skill library

Skills I use every day, published for anyone to install. The first is **writing-check**: it flags stock AI phrasing and formulaic structure in a draft before a person reads it, using a phrase list and a packed copy of [slop-guard](https://github.com/eric-tramel/slop-guard). It is a style aid for plain writing. It does not detect who wrote a text.

```text
/plugin marketplace add Sierra-Code-Co/claude-workflows
/plugin install writing-check@sierra-code-co
```

Microsoft 365 Copilot users: download [`dist/copilot/writing-check.zip`](dist/copilot/writing-check.zip) and use **Upload skill**. Details in [docs/installing-skills.md](docs/installing-skills.md).

## Start here

| You want to… | Read |
| --- | --- |
| Understand how the pieces fit together | [docs/architecture.md](docs/architecture.md) |
| Learn spec-driven development with Claude Code | [docs/spec-driven-development.md](docs/spec-driven-development.md) |
| Set up local multi-model code review (no vendor rate limits) | [docs/multi-model-review.md](docs/multi-model-review.md) |
| Install and manage Claude Code skills | [docs/installing-skills.md](docs/installing-skills.md) |
| Lay out a project so Claude loads the right guidance at the right time | [docs/organizing-projects-for-claude.md](docs/organizing-projects-for-claude.md) |
| See how this relates to GitHub's Spec Kit | [docs/relationship-to-spec-kit.md](docs/relationship-to-spec-kit.md) |
| Bootstrap a new project with all of this pre-wired | [internal-speckit-template](https://github.com/Sierra-Code-Co/internal-speckit-template) — the clone-me repo |
| Read why each decision was made | [decisions/](decisions/) — append-only ADRs |

## What's in this repo

| Path | What it is |
| --- | --- |
| `decisions/` | Architecture Decision Records. Append-only; reversed decisions are superseded, never deleted. The house rule: if you catch yourself re-deciding something, that's the signal it should have been an ADR. |
| `scripts/` | The tooling: `new-machine.sh` (fresh-machine bootstrap), `propagate-skill.sh` (fleet-wide skill updates), `review-plan.sh` (v1 plan review), `review-plan-v2.sh` + `review_plan_v2/` (the local diff-review orchestrator), `sync-public.sh` (produces this repo) |
| `tests/` | The review-plan-v2 test suite — unit + integration, runs in CI |
| `dotfiles/claude/` | The global `~/.claude/CLAUDE.md` (symlinked onto every machine), a sanitized `settings.example.json`, and `skills/`, the personal skill library (each one symlinked to `~/.claude/skills/`) |
| `dist/copilot/` | One Microsoft 365 Copilot upload zip per library skill, built by `scripts/build-copilot-zips.py` and checked against a fresh build in CI |
| `.claude-plugin/` | The plugin list that makes this repo a Claude Code marketplace |
| `specs/004-skill-library/` | The spec, plan and tasks for the skill library, including the Copilot test record |
| `rules/` | `ast-grep` structural rules that answer completeness questions deterministically — with fixture trees that prove each rule can actually fail |
| `gates.yml` | The declared review-gate portfolio: every gate carries a resolvable failure proof, deterministic gates order before LLM gates, probabilistic gates may only block with measured acceptance |
| `specs/001-review-plan-v2/` | A complete, real spec-kit feature — the spec, plan, and tasks that produced `scripts/review_plan_v2/` in this same repo. Read it side-by-side with the shipped code. |
| `references/learn-coding-agents/` | Lab notes on coding agents beyond Claude Code (OpenCode, Codex CLI, Kilo Code) and why multi-agent fluency matters |
| `experiments/` | WIP with explicit status: `active` / `graduated` / `killed`. Killed experiments keep their postmortem — the lesson is the value. |
| `docs/` | The guides linked above |

## How this repo is produced

This is a one-way curated mirror of our private workflows repo. `scripts/sync-public.sh` stages an explicit allowlist of paths (`scripts/public-manifest.txt`), overlays these docs, then runs two fail-closed gates — a denylist grep for names that must stay private, and a gitleaks scan — before anything is committed here. Client work, fleet inventory, and machine state never leave the private repo. The mechanism itself is in this repo, so you can copy the pattern.

## The three repos

```text
internal-claude-workflows (private)   — the source: config, ADRs, specs, client-aware fleet state
        │  scripts/sync-public.sh (allowlist + denylist + gitleaks, fail closed)
        ▼
claude-workflows (this repo, public)  — curated mirror + these docs + the personal
                                        skill library (plugin list, Copilot zips)

internal-speckit-template (public)    — the bootstrap template you actually clone
                                        for a new project; project skills live there
github/spec-kit (upstream)            — where the spec-driven skeleton came from
```

## License

[MIT](LICENSE) © Sierra Code Co
