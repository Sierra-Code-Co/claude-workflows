# Installing and managing Claude Code skills

A **skill** is a packaged instruction set Claude Code loads on demand: a directory containing a `SKILL.md` with YAML frontmatter (`name`, `description`, options) followed by the instructions themselves. When a skill is installed, you can invoke it as a slash command (`/review-plan`), and Claude can invoke it automatically when the description matches the task — unless you turn that off (below).

The format is an open standard ([agentskills.io](https://agentskills.io/specification)), and Microsoft 365 Copilot reads it too. Skills here use only the standard's frontmatter fields (`name`, `description`, `license`, `compatibility`, `metadata`), because claude.ai uploads and Copilot reject anything else.

## Where skills live

| Scope | Path | Use for |
| --- | --- | --- |
| Project | `<repo>/.claude/skills/<name>/SKILL.md` | Anything the whole team (or every clone) should have. Checked into the repo. |
| Personal | `~/.claude/skills/<name>/SKILL.md` | Skills that follow *you* across every project. |
| Plugin | installed by `/plugin install` | Skills someone else publishes and you want to keep updated. |

## Three ways to install

### 1. From the Sierra Code Co. plugin list (Claude Code)

This repo is a plugin marketplace. In Claude Code:

```text
/plugin marketplace add Sierra-Code-Co/claude-workflows
/plugin install writing-check@sierra-code-co
```

The skill is then available as `/writing-check:writing-check`, and Claude reaches for it on its own when a draft needs checking. It needs nothing installed beyond `python3` 3.11 or newer.

Updates: third-party marketplaces do not update in the background unless you turn that on, so update now and then: in Claude Code run `/plugin marketplace update sierra-code-co`, or from a shell `claude plugin update writing-check@sierra-code-co`. The plugin entry has no `version` field on purpose: you always get the latest commit of this repo, and nobody can forget to bump a number (ADR-0013).

### 2. As a Microsoft 365 Copilot skill

Download [`dist/copilot/writing-check.zip`](../dist/copilot/writing-check.zip). In Copilot (browser or the Microsoft 365 app): **Agents**, **More agents**, **Add**, **Upload skill**, and pick the zip. It has `SKILL.md` at its root, which is what the upload dialog requires.

Copilot runs skill scripts in a sandbox with no network and no package installs. Where the scripts cannot run, the skill's instructions tell Copilot to apply the same rules by reading. The tested result is recorded in [`specs/004-skill-library/research.md`](../specs/004-skill-library/research.md).

On Windows, `.md` files have no default program (Windows may offer Acrobat). To read `SKILL.md` before uploading, open Notepad, set the file filter to **All files**, and open it from there.

### 3. By copying (any project)

Copy the skill directory into one of the locations above and it is available in the next session.

```bash
# install one skill from the template into the current project
git clone https://github.com/Sierra-Code-Co/internal-speckit-template /tmp/speckit-template
mkdir -p .claude/skills
cp -R /tmp/speckit-template/.claude/skills/review-plan .claude/skills/
```

## Personal skills: one copy, linked

The skills I use myself live in this repo under `dotfiles/claude/skills/<name>/`, and `scripts/new-machine.sh` links each one to `~/.claude/skills/<name>`, the same way `dotfiles/claude/CLAUDE.md` *is* `~/.claude/CLAUDE.md`. Editing the skill in either place edits the one copy, `git diff` shows it, and every machine gets it on the next pull. The plugin list and the Copilot zip are built from that same folder, so what you install is what I run.

## Getting the full set: the template

Rather than installing skills one at a time, new projects here start from [internal-speckit-template](https://github.com/Sierra-Code-Co/internal-speckit-template) (public, despite the name), which ships the complete kit: the `speckit-*` chain, the `/review-plan` gate, and the `/feature` orchestrator, plus the `.specify/` framework they depend on. Its README covers both a one-off bootstrap (`new-project.sh`) and a `newproject` shell function for creating template-derived repos daily.

Note the dependency: the `speckit-*` skills read templates and scripts from `.specify/` — installing those skills without that directory gives you commands that can't find their machinery. Take the template wholesale, then delete what you don't want.

## A frontmatter choice, reversed: `disable-model-invocation`

Every skill in this fleet used to set `disable-model-invocation: true`. Default Claude Code behavior lets the model auto-invoke any skill whose description matches the task, and the reasoning was that this sounds helpful until `/speckit.specify` fires because you *mentioned* a spec, or a heavyweight workflow starts because your question resembled its trigger.

**As of 2026-08-28 the default is `false`, and the reversal is worth reading as a lesson in its own right.** The blanket rule failed the only test that matters: it was manually undone in every instance. Each new project arrived with all eleven skills unreachable by the model, and the operator flipped them back by hand — one project had all eleven flipped, the next had ten of eleven, and that missing eleventh is how a fleet drifts. A default reverted in every instance is not a safety property, it is a chore.

It also inverted the value of the descriptions. Every skill is described in terms of when a model should reach for it, and `true` made every one of those sentences unreachable. The pre-push review gate is the clearest case: a skill Claude cannot reach is a skill Claude will not use at the moment it should.

The concern was real, though, for a narrow class — so it is handled per-skill instead of fleet-wide. `/ship` keeps `disable-model-invocation: true`, because it merges PRs, pushes branches, and runs promote/deploy steps, and externally visible, hard-to-reverse actions are the one category that must not fire on a model's judgement that the moment looked right. The reason is recorded in `ship/SKILL.md`'s own frontmatter and in `scripts/assert-skill-invocation.sh`'s `KEEP_DISABLED` list, which enforces the default and fails loudly if it examined nothing.

The general form of the lesson: **a fleet-wide default that every instance overrides is a bug in the default, not discipline in the fleet.** Narrow the rule to the skills whose actions are irreversible, and state the reason next to the flag.

## Managing skills across many repos

One project's skills are a copy problem; twenty projects' skills are a distribution problem. The pattern here has three parts (full mechanics in [architecture.md](architecture.md)):

1. **One canonical source.** The template holds the authoritative copy of every shared skill. Skills are never edited in a downstream project and copied backwards — improvements land in the template first, then propagate outward.
2. **A propagation script, not a memory.** `scripts/propagate-skill.sh <name>` finds every project with the skill, shows a diff per project, and prompts before overwriting. `--install-missing` extends the sweep to projects that don't have it yet. Idempotent, so running it "just in case" is free.
3. **Drift is explicit.** Projects that customized a skill on purpose go on a skip-list, and the script warns instead of clobbering. Divergence you chose is fine; divergence you forgot about is how fleets rot. A periodic audit ("which projects differ from the template, and is each difference intentional?") keeps the ledger honest.

## Writing your own

Start from any skill in the template as a shape reference. The parts that matter:

- **`description` is the API.** Claude decides relevance from it, and so will you in six months. Say *when* to use it, not just what it does.
- **Small verifiable steps beat one big narrative** — if the skill has a checklist, an agent can turn it into tracked todos.
- **End-of-skill handoffs are markers, not stop signs.** If your skill ends with "next, run /foo", decide whether that means *the pipeline continues automatically* or *a human decides* — and say which explicitly. Ambiguity there is how workflows stall (or run away).
- **Put constraints in the skill, not in hope.** "Never propagate without updating the template first" lives in written instructions precisely because it's the kind of rule that gets skipped under time pressure.
