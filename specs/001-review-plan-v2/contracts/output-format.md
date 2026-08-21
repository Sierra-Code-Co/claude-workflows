# Output Format Contract — review-plan-v2

**Phase**: 1 (Design & Contracts)

Defines `--plain` and `--agent` output formats. **Plain mode is parse-compatible with `coderabbit review --plain`** so downstream tooling (grep, awk, scripts conditioning on output) doesn't break when swapping tools (FR-013).

---

## `--plain` mode (default)

Each finding is rendered as a single line with severity prefix, file:line locator, category tag, and message. Multi-line messages are continued with leading spaces (CR convention).

### Line format

```text
<severity-prefix> <file>:<line>[-<line-end>] [<category>] <message>
```

Where:

- `<severity-prefix>` is one of: `[ACTIONABLE]`, `[NIT]`, `[INFO]`
- `<file>` is repo-relative path
- `<line>` is the start line; if a range, `<line>-<line-end>`
- `<category>` is one of: `bug`, `security`, `correctness`, `tests`, `consistency`, `style`, `prose`, `docs`, `secrets`, `nit` (authoritative list lives in `scripts/review_plan_v2/types.py` + `aggregator.SOFT_CATEGORIES`)
- `<message>` is the finding text (single line preferred; multi-line is wrapped with 2-space indent on continuation lines)

### Example output

```text
[ACTIONABLE] src/lib/iap.ts:127 [bug] Comparing err.code === 'user-cancelled' but expo-iap v3 returns 'UserCancelled' (PascalCase). User-cancelled flows will be treated as failures. [high-confidence: security, correctness]

[ACTIONABLE] src/api/checkout.ts:42 [security] Direct string concatenation into SQL: 'SELECT * FROM orders WHERE id = ' + req.body.id — use parameterized queries. [high-confidence: security]

[ACTIONABLE] .github/workflows/deploy.yml:18 [secrets] gitleaks: matched rule 'aws-access-token' in committed file (entropy=4.8) [single-source: gitleaks]

[NIT] specs/001-review-plan-v2/spec.md:142 [style] Trailing whitespace on line 142 [single-source: markdownlint]

[INFO] CHANGELOG.md:9 [consistency] Section header style differs from neighboring entries (no period). [single-source: consistency]
```

### Footer

After all findings, a one-line summary:

```text
=== 3 actionable, 1 nit, 1 info | wall: 87s | cost: $0.04 | run: a8f2c1 ===
```

If no findings:

```text
=== Clean (no findings) | wall: 12s | cost: $0.02 | run: 4b1d3e ===
```

If auto-paused:

```text
=== Auto-paused (last 3 runs trivial) — pass --force-full to override | run: 9c2a1b ===
```

### Compatibility with `coderabbit review --plain`

- Same line shape: `<severity> <file>:<line> [<category>] <message>`
- Same severity vocabulary (CR uses different exact words but similar tiers; we standardize on `ACTIONABLE`/`NIT`/`INFO`)
- Same use of bracketed source attribution
- Footer line summary added (CR has its own; ours is shorter but parse-compatible)

A consumer like `grep '^\[ACTIONABLE\]' | wc -l` works identically against either tool.

---

## `--agent` mode (structured JSON)

For piping into Claude or other agent tools. One JSON object per line (JSON Lines / NDJSON), terminated by a final summary object.

### Per-finding line

```json
{"type":"finding","file":"src/lib/iap.ts","line":127,"line_range":null,"severity":"actionable","category":"bug","message":"Comparing err.code === 'user-cancelled' but expo-iap v3 returns 'UserCancelled' (PascalCase). User-cancelled flows will be treated as failures.","suggested_fix":"-if (err.code === 'user-cancelled')\n+if (err.code === 'UserCancelled')","sources":[{"kind":"reviewer","name":"security","model":"deepseek/deepseek-reasoner"},{"kind":"reviewer","name":"correctness","model":"anthropic/claude-sonnet-4-6"}],"confidence":"high-confidence"}
```

### Final summary line

```json
{"type":"summary","run_id":"a8f2c1","wall_clock_ms":87000,"cost_usd":0.04,"counts":{"actionable":3,"nit":1,"info":1},"providers_called":[{"provider":"deepseek","model":"deepseek-reasoner","calls":4,"input_tokens":12000,"output_tokens":3500,"cost_usd":0.012},{"provider":"anthropic","model":"claude-sonnet-4-6","calls":2,"input_tokens":6000,"output_tokens":1800,"cost_usd":0.028}],"analyzers_run":["gitleaks","markdownlint","actionlint","shellcheck"],"auto_paused":false}
```

### Empty-diff or auto-paused case

Single summary line with `counts: {actionable:0, nit:0, info:0}` and `auto_paused: true` (or no diff to review). No finding lines.

---

## Error / degraded output

If a provider fails mid-run (transport error, quota exhausted), a `notice` line is emitted before the affected reviewers' findings:

### Plain mode

```text
[NOTICE] Reviewer 'security' (anthropic/claude-sonnet-4-6) skipped: ANTHROPIC_API_KEY not set
[NOTICE] Reviewer 'correctness' partial: 1 of 2 model calls succeeded (deepseek-reasoner OK, claude-sonnet-4-6 transport error)
```

### Agent mode

```json
{"type":"notice","level":"info","reviewer":"security","reason":"missing_api_key","provider":"anthropic"}
{"type":"notice","level":"warn","reviewer":"correctness","reason":"partial","detail":"deepseek-reasoner OK, claude-sonnet-4-6 transport error"}
```

These are informational — they don't change the exit code. Per FR-009, "the tool runs on available providers and notes the absent ones; doesn't fail the whole run."
