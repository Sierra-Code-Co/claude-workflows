# Comparison & When-to-Use Cheat Sheet

A practical decision matrix for picking the right tool per task. Updated as you form opinions — this is intentionally short and opinionated so you can mark it up.

## One-Line Positioning

| Tool | One-liner |
|------|-----------|
| **Claude Code** | The polished default. Best on-rails single-model experience. |
| **OpenCode** | Claude Code with vendor independence and cleaner config. Similar mental model. |
| **Codex CLI** | Second-opinion agent with OS-level sandbox. Trained differently → catches different bugs. |
| **Kilo Code** | Editor-integrated. Explicit agent modes (code / ask / plan / debug). |

## Decision Table

| Task | Reach for |
|------|-----------|
| Daily feature development, you trust the model | **Claude Code** or **OpenCode** (pick one and stick) |
| Want to try a non-Claude model today | **OpenCode** (`/models`) or **Kilo** (Gateway) |
| Reviewing AI-written changes before commit | **Codex CLI** — that's the whole reason it exists alongside your primary agent |
| Spec-driven review fan-out (step 4.5) | **Codex exec** in your pipeline |
| Scripting / CI / pre-commit hook | **Codex exec** (non-interactive, sandboxed) |
| Exploring unfamiliar code without risk | **Kilo `ask` mode** or **OpenCode Plan mode** |
| Writing a plan before executing | **Kilo `plan` mode** (writes to `.kilo/plans/`) or **OpenCode Plan mode** |
| Security-sensitive tasks in a fresh env | **Codex** (strong sandbox) |
| Need to run a local model for privacy | **OpenCode** (supports local providers directly) |
| Using your existing ChatGPT Plus subscription | **Codex** (no separate billing) |
| Using existing GitHub Copilot subscription | **OpenCode** (reuse the sub at zero markup) |
| Editor-native workflow in VS Code | **Kilo Code** |
| Want a sandbox to experiment without cost | **OpenCode Zen** free-tier models, or **Kilo Gateway** free tier |

## The Two Patterns Worth Memorizing

### Pattern 1: Primary + Reviewer

```text
Claude Code or OpenCode  →  writes the code
            ↓
Codex CLI                →  reviews it in a separate session before commit
            ↓
commit
```

The review step is what catches what your primary model missed. Different training → different blind spots.

### Pattern 2: Plan → Build → Review

```text
OpenCode Plan mode (Tab)     →  designs the change, no edits
            ↓
OpenCode Build mode (Tab)    →  executes the plan
            ↓
Codex exec                   →  reviews the diff
            ↓
commit
```

This is the single-tool-ish version of the spec-driven flow. Less ceremony than full SpecKit, but more structure than "just ask the agent to do it."

## Cost and Subscription Notes

- **Claude Code**: Anthropic API billing (Pro, Max plans, etc.)
- **OpenCode** BYOK: pay whatever your provider charges, no markup
- **OpenCode Zen**: pay-as-you-go, billed by OpenCode; free tier available
- **Codex CLI** via ChatGPT Plus/Pro/Business/Edu/Enterprise: included in the subscription
- **Codex CLI** via API key: OpenAI standard pricing
- **Kilo Gateway**: provider-rate pricing, no markup
- **Kilo BYOK**: your provider's pricing

For cost optimization: OpenCode with BYOK against your existing Anthropic/OpenAI keys is typically the cheapest. Codex on ChatGPT Plus is effectively "free" up to your subscription limits.

## Keep This Honest

This table is wrong in places because these tools ship weekly. If you notice something here doesn't match reality, edit it. The whole point of owning this repo is to keep your own ground truth rather than trust the docs (ours or theirs).
