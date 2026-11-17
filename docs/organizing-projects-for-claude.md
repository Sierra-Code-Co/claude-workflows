# Organizing a project for Claude Code

How I lay out a repository so Claude starts each session with what it needs and nothing else. The facts about what loads when were checked against the Claude Code documentation on 2026-11-16; each section names the page.

## The cost model

Everything Claude reads takes up the context window, and some of it is paid for again after every compaction. So the question for each piece of guidance is when it should load:

| Kind of guidance | Put it in | Loads |
| --- | --- | --- |
| Rules that apply every session, the read order, the folder layout | the root `CLAUDE.md` | at launch, and again after every compaction |
| Guidance for one folder | a `CLAUDE.md` inside that folder | the first time Claude reads, writes or edits a file there |
| Guidance for a kind of file (client prose, personal data) | `.claude/rules/<name>.md` with `paths:` | when Claude touches a matching file |
| A procedure (how to build the PDF, how to ship) | a skill | when invoked, or when its description matches the task |
| Where the work stands today | a short current-state file the root `CLAUDE.md` tells Claude to read first | on that read |
| Preferences and corrections about how I work | auto memory | first 200 lines or 25 KB of `MEMORY.md` at start; topic files on demand |

Source: [memory](https://code.claude.com/docs/en/memory), [context window](https://code.claude.com/docs/en/context-window), [skills](https://code.claude.com/docs/en/skills).

## The root `CLAUDE.md`

Keep it under 200 lines. The documentation gives that target for every `CLAUDE.md`, and Claude Code warns at startup when a file is longer, because a long file costs context and Claude follows it less closely.

Mine holds three things: the read order ("read `STATUS.md` first"), the hard rules that must hold in every session, and a tree of the folders with one line each. Anything procedural moves to a skill, and anything about one folder moves into that folder.

Two details change what belongs here:

- An `@path` import does not save context. Imported files load together with the file that imports them. A plain sentence ("read `STATUS.md` before anything else") is an on-demand read instead, which suits a file that changes often.
- Block-level HTML comments are stripped before the file reaches Claude, so `<!-- why this rule exists, review 2027-03 -->` costs nothing. I use them for maintainer notes.

## Nested `CLAUDE.md` files

At launch Claude loads the `CLAUDE.md` in the working directory and in each folder above it. A `CLAUDE.md` further down loads only when Claude reads, writes or edits a file in that folder. So per-track or per-project guidance goes in that track's folder, kept short, and costs nothing in sessions that never go there.

One trap: `--add-dir` does not load the added folder's `CLAUDE.md` unless `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` is set.

## Path-scoped rules

A file in `.claude/rules/` without frontmatter loads at launch, like the root file. With a `paths:` list it loads only when Claude works on a matching file. `paths` is the only frontmatter field Claude Code reads there.

I use two on client repos: one for any document a client will read (the prose rules, and "run the writing check before it goes out"), and one for any file that holds personal data.

## The current-state file

A short file, under about 150 lines, that answers "where are we?": what is open, what was decided last, what is waiting on whom. The root `CLAUDE.md` points at it as the first read.

Keep history out of it. A dated log in a separate file holds what happened, and superseded plans move out of the first-read path. Compaction re-reads up to five recently modified files, and a file over about 5,000 tokens comes back as a path without its content, so a large first-read file is either paid for repeatedly or comes back without its content.

## Memory versus the repo

Auto memory is for preferences and corrections: how I like things done, mistakes not to repeat. Facts about the project belong in versioned files in the repo, where a teammate, a reviewer and the next session all see the same thing.

## Conflicts and stale instructions

When two instructions contradict each other, Claude may follow either. `/doctor prompt-audit` lists contradictions, references to files that no longer exist and outdated model instructions. I also put a reason and a review date beside any standing instruction, so it can be retired once the reason is gone.

## The layout I use for client work

```text
client-repo/
├── CLAUDE.md               # read order, hard rules, this tree
├── STATUS.md               # current state, under ~150 lines, read first
├── history/                # dated log; superseded plans
├── .claude/rules/
│   ├── client-prose.md     # paths: docs/**, correspondence/**
│   └── personal-data.md    # paths: data/**
├── <track-a>/CLAUDE.md     # one folder per track, short nested guidance
├── <track-b>/CLAUDE.md
├── correspondence/         # one file per outgoing email
└── reference/              # raw client material, gitignored
```

Habits that go with it:

- Each outgoing email is its own file with a status line. It says SENT only after I confirm I sent it.
- After every client meeting or message, the current-state file, the history log and any affected track are updated together, in one change.
- Unknowns are written as TBD, never guessed.
- Raw client material stays in the gitignored `reference/` folder and never enters a tracked file.

## Related

- [Installing skills](installing-skills.md), including the Sierra Code Co. plugin list
- [Architecture](architecture.md): how this repo, the template and active projects relate
- ADR-0006 (why this repo is separate) and ADR-0013 (personal skills) in [decisions/](../decisions/)
