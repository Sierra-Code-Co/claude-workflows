# Finding Schema Contract — review-plan-v2

**Phase**: 1 (Design & Contracts)

Internal JSON schema for the `Finding` object as it flows through the orchestrator. Each reviewer / analyzer emits findings in this shape; the aggregator merges, dedups, and tiers them; the output renderer converts to plain text or agent JSON.

This schema is **internal** — only the aggregator, reviewers, and renderer see it. The user-facing JSON in `--agent` mode is a slightly flattened version (defined in `output-format.md`).

---

## JSON Schema (informal)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["file", "severity", "category", "message", "sources", "confidence"],
  "properties": {
    "file": {
      "type": "string",
      "description": "Repo-relative path. Forward slashes on all platforms."
    },
    "line": {
      "type": "integer",
      "minimum": 0,
      "description": "Start line (1-based). 0 indicates a whole-file finding."
    },
    "line_end": {
      "type": ["integer", "null"],
      "minimum": 1,
      "description": "Inclusive end line for ranged findings; null when single-line."
    },
    "severity": {
      "type": "string",
      "enum": ["actionable", "nit", "info"],
      "description": "Tier. Actionable = block/fix; nit = optional polish; info = FYI."
    },
    "category": {
      "type": "string",
      "enum": ["bug", "security", "correctness", "tests", "consistency", "style", "prose", "docs", "secrets", "nit"],
      "description": "Authoritative list mirrors types.py + aggregator.SOFT_CATEGORIES."
    },
    "message": {
      "type": "string",
      "minLength": 1,
      "description": "Human-readable finding. Single sentence preferred."
    },
    "suggested_fix": {
      "type": ["string", "null"],
      "description": "Optional unified-diff snippet, like CR's 'Suggested fix' blocks."
    },
    "sources": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["kind", "name"],
        "properties": {
          "kind": { "type": "string", "enum": ["reviewer", "analyzer"] },
          "name": { "type": "string" },
          "model": { "type": ["string", "null"] }
        }
      }
    },
    "confidence": {
      "type": "string",
      "enum": ["high-confidence", "single-source"],
      "description": "high-confidence = multiple sources agree; single-source = one reviewer/analyzer."
    }
  }
}
```

---

## Producer contracts

Each reviewer (LLM) and analyzer (deterministic tool) emits findings in this shape. The orchestrator passes them to the aggregator.

### LLM reviewer output

The LLM is prompted to return a JSON array of findings. The reviewer's system prompt enforces this schema; the orchestrator validates against it before aggregation.

Example LLM response:

```json
[
  {
    "file": "src/lib/iap.ts",
    "line": 127,
    "severity": "actionable",
    "category": "bug",
    "message": "err.code comparison uses 'user-cancelled' (kebab) but expo-iap v3 returns 'UserCancelled' (PascalCase).",
    "suggested_fix": "-if (err.code === 'user-cancelled')\n+if (err.code === 'UserCancelled')",
    "sources": [{"kind": "reviewer", "name": "security", "model": "deepseek/deepseek-reasoner"}],
    "confidence": "single-source"
  }
]
```

(Confidence is set to `single-source` by the producer; the aggregator promotes to `high-confidence` when merging duplicates.)

### Static analyzer output

Each analyzer's stdout/stderr is parsed by the `parse_output` method on the `StaticAnalyzer` subclass in `scripts/review_plan_v2/analyzers/<name>.py`. Parsers normalize tool-specific output to the schema.

| Analyzer | Output format | Parser strategy |
|---|---|---|
| `gitleaks` | JSON via `--report-format=json` | Map `Description` → message, `File` → file, `StartLine` → line, severity always `actionable`, category always `secrets` |
| `markdownlint` | JSON via `--json` | Map `lineNumber` → line, `ruleNames[0]` → embedded in message, severity = `nit` (markdownlint findings are style-level), category = `style` or `docs` per filename |
| `actionlint` | JSON via `-format='{{json .}}'` | Map `Line` → line, `Message` → message, severity = `actionable` (actionlint catches CI errors) |
| `shellcheck` | JSON via `--format=json` | Map `line` → line, severity per `level` field (`error/warning/info` → `actionable/nit/info`), category = `bug` for `error`, `style` for `warning`/`info` |

---

## Aggregator behavior

### Dedup

Two findings are **the same finding** if all of:

- Same `file`
- Overlapping `line` or `line_end` within a configurable window (default **±5 lines**, override via `.review-plan-v2.yaml#dedup_line_window` or `--dedup-window`). ±5 covers common cases like a missing `try/except` block flagged at the start by one reviewer and at the end by another. ±2 is too tight; ±10 starts merging unrelated findings.
- Same `category`

When merged: `sources` is the union; `severity` takes the max (actionable > nit > info); `confidence` becomes `high-confidence` if `len(sources) > 1`; `message` keeps the longer/more-specific one (or concatenates with `;` if both are roughly equal length and add distinct info).

### path_instructions filter

After dedup, the aggregator applies path_instructions from `.coderabbit.yaml`:

1. For each finding, find the most-specific matching `path_glob` in `path_instructions`.
2. Pass the `instructions` text + finding metadata to a small "filter" prompt — should this finding be kept or downgraded per the instructions? (e.g., `**/*.md` instructions say "skip prose nits"; a `nit`+`style` finding on a `.md` file gets dropped.)
3. The filter step uses a small/cheap model (DeepSeek), not the cascade. Falls back to "keep" if filter call fails.

### Severity tiering

After dedup + filter:

- Actionables sorted first
- Within tier, sort by file then line
- Keep all in output (no truncation by default; future flag could limit)

---

## Edge cases

- **Line `0` and `line_end` `null`**: whole-file finding (e.g., "this entire file should be rewritten" — rare). Rendered as `file:0` in plain mode.
- **`suggested_fix` containing CR-incompatible diff**: rendered verbatim; user's terminal shows it as text. Not auto-applied.
- **`message` with newlines**: in plain mode, newlines are converted to `\n` (2-space indent for continuation). In agent mode, kept as-is in JSON.
- **Empty `sources` array**: invalid; aggregator drops the finding with a notice.
