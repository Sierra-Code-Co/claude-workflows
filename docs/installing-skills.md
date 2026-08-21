# Installing and managing Claude Code skills

A **skill** is a packaged instruction set Claude Code loads on demand: a directory containing a `SKILL.md` with YAML frontmatter (`name`, `description`, options) followed by the instructions themselves. When a skill is installed, you can invoke it as a slash command (`/review-plan`), and Claude can invoke it automatically when the description matches the task — unless you turn that off (below).

## Where skills live

| Scope | Path | Use for |
| --- | --- | --- |
| Project | `<repo>/.claude/skills/<name>/SKILL.md` | Anything the whole team (or every clone) should have. Checked into the repo. |
| Personal | `~/.claude/skills/<name>/SKILL.md` | Skills that follow *you* across every project. |

Installation is file-copying — there is no registry step. Copy the skill directory into one of those locations and it's available in the next session.

```bash
# install one skill from the template into the current project
cp -R ~/dev/projects/internal-speckit-template/.claude/skills/review-plan .claude/skills/
```

## Getting the full set: the template

Rather than installing skills one at a time, new projects here start from [internal-speckit-template](https://github.com/Sierra-Code-Co/internal-speckit-template), which ships the complete kit: the `speckit-*` chain, the `/review-plan` gate, and the `/feature` orchestrator, plus the `.specify/` framework they depend on. Its README covers both a one-off bootstrap (`new-project.sh`) and a `newproject` shell function for creating template-derived repos daily.

Note the dependency: the `speckit-*` skills read templates and scripts from `.specify/` — installing those skills without that directory gives you commands that can't find their machinery. Take the template wholesale, then delete what you don't want.

## One deliberate frontmatter choice: `disable-model-invocation: true`

Every skill in this fleet sets it. Default Claude Code behavior lets the model auto-invoke any skill whose description matches the task — which sounds helpful until `/speckit.specify` fires because you *mentioned* a spec, or a heavyweight workflow starts because your question resembled its trigger. With `disable-model-invocation: true`, a skill runs only when a human types the slash command. Pipelines that chain phases (like `/feature`) invoke the next skill explicitly, so nothing is lost — but nothing runs by surprise.

The general form of the lesson: **workflow-shaped skills should be opt-in commands; only knowledge-shaped skills should auto-trigger.**

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
