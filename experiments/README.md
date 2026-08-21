# experiments/

WIP that's being tried but hasn't graduated to template + active projects yet.

## Convention

One subdirectory per experiment: `experiments/<short-name>/`. Each contains:

- `README.md` — what's being tried, why, what success looks like, when to evaluate
- Any code/config/scripts the experiment needs

When an experiment **graduates**: write an ADR, propagate to template, propagate to active projects, then either delete the experiment dir or convert its README into reference doc.

When an experiment **dies**: keep the directory, change `Status:` in README to `killed`, write a one-paragraph postmortem. The lesson is more valuable than the code.

## Suggested experiments (from `/insights` report 2026-04-26)

These are flagged as ideas worth trying but not yet started:

| Name                          | What                                                    |
| ----------------------------- | ------------------------------------------------------- |
| `coderabbit-auto-remediation` | Long-running agent that polls PR comments, classifies, auto-applies safe fixes, escalates judgment calls |
| `sentry-bug-hunter`           | Loop: pull top Sentry issue → write failing test → fix → PR → next |
| `parallel-feature-factory`    | Dispatch multiple `/feature` runs in isolated git worktrees overnight |
| `code-intel-plugins`          | Evaluate TypeScript and Python intelligence plugins from `/plugin` for catching `buggy_code` frictions earlier |
| `claude-md-import-split`      | Split the 500+ line `companion-ai/CLAUDE.md` into `@import`-referenced sub-files (the doc explicitly warns: bloated CLAUDE.md → Claude ignores rules) |

Promote any of these to GitHub issues to track + assign yourself.
