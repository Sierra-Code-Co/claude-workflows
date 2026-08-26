---
name: speckit-agent-context-update
description: Refresh the managed Spec Kit section in the coding agent context file
compatibility: Requires spec-kit project structure with .specify/ directory
metadata:
  author: github-spec-kit
  source: agent-context:commands/speckit.agent-context.update.md
---

# Update Coding Agent Context

Refresh the managed Spec Kit section inside the active coding agent's context/instruction file (e.g. `CLAUDE.md`, `.github/copilot-instructions.md`, `AGENTS.md`).

## Behavior

The script reads the agent-context extension config at
`.specify/extensions/agent-context/agent-context-config.yml` to discover:

- `context_file` — the path of the coding agent context file to manage.
- `context_markers.start` / `.end` — the delimiters surrounding the managed section. Defaults to `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` when the field is missing.

It then creates, replaces, or appends the managed block so that the section points at the most recent plan path when one can be discovered (`specs/<feature>/plan.md`).

If `context_file` is empty, the command reports nothing to do and exits successfully. If `context_file` is set but the file does not exist, the command **creates it** containing just the managed block.

If the file exists but holds only one of the two markers, or holds them out of order, the command refuses to write, names the malformed state on stderr, and exits non-zero, leaving the file unchanged.

## Execution

- **Bash**: `.specify/extensions/agent-context/scripts/bash/update-agent-context.sh [plan_path]`
- **PowerShell**: `.specify/extensions/agent-context/scripts/powershell/update-agent-context.ps1 [plan_path]`

When `plan_path` is omitted, the script auto-detects the most recently modified `specs/*/plan.md`.
