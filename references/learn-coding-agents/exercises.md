# Exercises

Hands-on practice tasks tied to your existing projects. Each exercise names which tool it's for, what you'll learn, and which of your projects to target.

## How to Use

- Always work on a branch (`git checkout -b learning-<tool>-<exercise>`).
- Time-box to 30 minutes. If you're still wrestling at 30, stop and write what went wrong.
- After each exercise, add two lines to `notes.md` (create it when needed): what worked, what surprised you.

## Warmup Track (`figment`)

Safe target. Small surface. Use this when you first install a new tool.

### W1 — OpenCode "hello world" (30 min)

```bash
cd ~/dev/projects/figment
git checkout -b learning-opencode-w1
opencode
```

In the TUI: `/init`, then in Plan mode ask "explain this project in 5 bullets." Toggle to Build mode, ask it to add that summary to README. Exit, diff, keep or discard.

**Goal**: finish the session with OpenCode installed, connected to a provider, and one commit (or intentionally discarded change).

### W2 — Codex read-only pass (20 min)

```bash
cd ~/dev/projects/figment
codex
```

Choose read-only mode. Ask: "What does this project do? What are the three files most important to understand it?" Don't let it touch anything.

**Goal**: experience the sandbox and approval flow without pressure.

### W3 — Kilo ask mode (20 min)

Open `figment` in VS Code with Kilo installed. Switch to `ask` mode (`Cmd+.`). Ask three architectural questions. Notice that it refuses to edit anything even if you accidentally phrase a question as a request.

**Goal**: feel the difference between scoped-agent and omni-agent behavior.

## Comparison Track

Run the same task across tools and notice the differences.

### C1 — Three agents, one refactor (`mtg-cube-ai`, 60 min)

Pick one function in `~/dev/projects/mtg-cube-ai` that is hard to read. Don't refactor it yet.

Then in three branches:

- `compare-claude`: let Claude Code refactor it
- `compare-opencode`: let OpenCode refactor it
- `compare-codex`: let Codex refactor it

Diff all three against main. In `notes.md`, write:

- Which one was most faithful to existing patterns?
- Which one introduced the most new imports or dependencies?
- Which one's tests (if it wrote any) actually pass?

**Goal**: build a mental model of each tool's defaults and biases.

### C2 — Review the same PR with two tools (`family-meeting`, 45 min)

Make a real change in `~/dev/projects/family-meeting` using Claude Code. Commit it. Then ask Codex to review the commit, and separately ask OpenCode (in a review-scoped custom agent) to review the same commit.

Compare what each caught. Which one found the real issue? Which one hallucinated a problem?

**Goal**: see whether cross-model review earns its keep on your actual code.

## Production-Adjacent Track

Only do these once you trust yourself with the tool. Always on a branch. Never on `main`.

### P1 — Add a feature via Plan → Build → Review (`choose-adventure` / novelflame.ai, 90 min)

1. In OpenCode Plan mode: "Design a change that adds a 'regenerate this scene' button to each adventure page." Let it write the plan.
2. Switch to Build mode: "Execute the plan."
3. Commit the change.
4. In Codex: "Review this commit. Focus on security (XSS in user-regenerated content), state management bugs, and performance regressions in the render path."
5. If Codex flags something real, go back to OpenCode to fix it.

**Goal**: do a real feature using the Primary + Reviewer pattern. Feel whether the overhead is worth it.

### P2 — SEO content audit via Kilo custom agent (`choose-adventure`, 60 min)

You already have SEO wins from the marketing consultant. Make them durable:

1. Define a custom Kilo agent called `seo-auditor` with read-only access.
2. Instructions: "Audit the site's page titles, meta descriptions, and H1 tags against the target keywords in `docs/seo/keywords.md`. Write findings to `docs/seo/audit-YYYY-MM-DD.md`."
3. Run it.
4. Schedule it (shell cron) weekly.

**Goal**: turn a recurring expert task into a scheduled agent — e.g. a Sunday-morning SEO-report cron.

### P3 — Integrate Codex into SpecKit step 4.5 (`claude-speckit-template`, 90 min)

Your custom `/feature` wrapper already fans out to Gemini + OpenAI + Claude for plan review. Add Codex as a fourth reviewer:

1. Find the step 4.5 implementation in `~/dev/projects/claude-speckit-template`.
2. Add a shell invocation that pipes the plan and tasks files into `codex exec`.
3. Aggregate Codex's findings alongside the other three.
4. Test on an existing spec from another project.

**Goal**: make Codex a first-class part of your workflow instead of a side experiment.

## Infrastructure Track

Skip unless you want to get serious about self-hosting.

### I1 — Local model via OpenCode

Install Ollama (`https://ollama.com/`). Pull a small model (e.g. `ollama pull llama3.1:8b`). In OpenCode, configure the local provider and use it on the `figment` warmup exercise. Note the quality drop and the privacy upgrade.

**Goal**: prove to yourself you could run an agent without any cloud LLM — useful for fully private, on-prem deployments.

### I2 — OpenCode Zen free-tier tour

Sign up for Zen (`https://opencode.ai/auth`). Use one of the free models (Big Pickle, MiniMax M2.5 Free, Ling 2.6 Flash, Hy3 Preview, Nemotron 3) on a warmup exercise. Compare output quality to Claude/GPT.

**Goal**: know what the free tier is capable of. Good data point for client conversations about budget options.

## Tracking

As you work through these, mark them off here. No pressure to do all of them. Do one warmup from each tool, then pick comparison or production track based on what you're actually doing that week.

- [ ] W1 — OpenCode hello world
- [ ] W2 — Codex read-only pass
- [ ] W3 — Kilo ask mode
- [ ] C1 — Three agents, one refactor
- [ ] C2 — Cross-tool review
- [ ] P1 — Plan → Build → Review feature
- [ ] P2 — SEO audit agent
- [ ] P3 — Codex in SpecKit 4.5
- [ ] I1 — Local model in OpenCode
- [ ] I2 — Zen free-tier tour
