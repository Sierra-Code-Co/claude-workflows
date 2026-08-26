"""Core data types per data-model.md. Frozen dataclasses for hashability + safety."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FileChange:
    path: str
    is_binary: bool
    is_renamed_from: str | None
    added_lines: tuple[tuple[int, int], ...]  # (start, end) ranges of added/modified lines
    diff_text: str
    language: str | None  # ts, py, sh, md, yml, etc.; None if unknown


@dataclass(frozen=True)
class Diff:
    base_ref: str
    head_ref: str
    files: tuple[FileChange, ...]


@dataclass
class Finding:
    file: str
    line: int
    line_end: int | None
    severity: str  # actionable | nit | info
    category: str  # security | correctness | tests | consistency | style | docs | secrets | bug
    message: str
    sources: list[str]  # ["security", "deepseek"] or ["gitleaks"]
    confidence: str = "single-source"  # single-source | high-confidence
    # --- US2 verification (spec 003) -------------------------------------
    # `claim` is the reviewer's self-declared checkable assertion, carried as a
    # raw dict and validated against gates/schemas/finding-envelope.schema.json.
    # None means the finding rests on judgment, which is a FIRST-CLASS state and
    # not a degraded one: design-consequence findings are what a reviewer is
    # uniquely good at, and penalising them for carrying no claim would drop the
    # best findings in the gold set (G1 and G7 are both claim: null).
    claim: dict | None = None
    # None means the verification stage did NOT run for this review. That is a
    # different fact from "ran and could not check" (unverifiable/unchecked),
    # which is a different fact again from "ran and confirmed". Collapsing the
    # three is precisely how a gate comes to report clean because it never
    # executed.
    verdict: str | None = None  # confirmed | refuted | unverifiable | unchecked | None
    verdict_detail: str | None = None


@dataclass
class PathInstruction:
    path_glob: str
    instructions: str


@dataclass
class HighRiskPath:
    path_glob: str
    reason: str = ""


def _default_broad() -> str:
    """registry.DEFAULT_BROAD, imported lazily to break a cycle.

    types -> providers.registry -> providers.google -> types (for CallResult).
    A module-level import here would be circular, so this resolves at RunConfig()
    construction time, by which point every module is loaded. The indirection is
    worth it: the alternative is a literal default that has to be remembered
    whenever the provider set changes, which is the bug this replaced.
    """
    from .providers import registry

    return registry.DEFAULT_BROAD


@dataclass
class RunConfig:
    base: str | None = None
    scope: str = "all"
    config_path: str | None = None
    plain: bool = True
    agent: bool = False
    no_color: bool = False
    force_full: bool = False
    auto_pause_n: int = 3
    max_concurrency: int = 4
    dedup_window: int = 5
    no_static_analyzers: bool = False
    no_cascade: bool = False
    #: Provider tag for the BROAD pass — the four reviewers that see every file.
    #: Was hardcoded to deepseek in four factories and three orchestrator dicts.
    #: It is configurable because "which vendors may see this code" is a property
    #: of the repository, not of this tool: an employer repo under a data-egress
    #: policy needs a different answer than a personal one, and forking four
    #: reviewer modules to express that is how the two copies drift apart.
    #: Precedence: REVIEW_PLAN_V2_BROAD_PROVIDER env > .review-plan-v2.yaml
    #: `broad_provider` > this default. Validated against
    #: providers.registry.REVIEW_CAPABLE at load, not at call time, so a typo is
    #: a config error rather than four rounds of `auth (HTTP no-response)`.
    #:
    #: The default is NOT a literal here. It was `"deepseek"`, and the field was
    #: added precisely so employer repos could opt out — but a default is what
    #: applies when config loading degrades, and the YAML loader returns early on
    #: a machine with no `yq`. So the opt-out silently did not apply on exactly
    #: the machines least likely to notice. DeepSeek is now refused outright and
    #: the default lives in one place.
    broad_provider: str = field(default_factory=lambda: _default_broad())
    #: Display label for WHERE broad_provider came from, set by
    #: config._apply_broad_provider and printed on the `broad pass:` line.
    #:
    #: Exists because a reviewer keeps raising, correctly, that this setting can
    #: come from a file in the branch under review and decides where the diff of
    #: every changed file is sent. The bound on that is documented in
    #: orchestrator.py — an out-of-repo allowlist, a required key, and env
    #: precedence — and one of those three is only usable if the operator can
    #: SEE which origin won. `[default]` alone could not distinguish "nobody
    #: chose this" from "the reviewed branch chose this and happens to agree".
    broad_provider_source: str = "default"
    # Escape hatch for the verification stage. Its existence is what makes the
    # "[VERIFIED-OUT] … re-run with --no-verify to see them" line honest: a
    # dropped finding a developer cannot get back is a dropped finding they have
    # to take on faith, which is the posture this stage exists to end.
    no_verify: bool = False
    max_cost_usd: float | None = None
    dry_run: bool = False
    strict_config: bool = False
    #: T005k. Treat "0 files reviewed" as a failure. Off by default because an
    #: empty diff is genuinely nothing to do and `|| exit 1` pre-push hooks are
    #: a documented use — but a CI job that means "prove you reviewed this"
    #: needs the strict reading, since exit 0 cannot otherwise distinguish
    #: "reviewed everything, clean" from "reviewed nothing".
    require_changes: bool = False
    path_filters: list[str] = field(default_factory=list)
    # --- US5 reviewer context (spec 003) ---------------------------------
    # Operator-declared files attached to every reviewer call (#18).
    always_include_files: list[str] = field(default_factory=list)
    # Module-specifier prefix -> repo-relative directory, e.g. {"$lib": "web/src/lib"}.
    # No built-in defaults: guessing an alias silently attaches the wrong file,
    # which is worse than attaching none.
    import_aliases: dict[str, str] = field(default_factory=dict)
    context_budget_chars: int = 40000
    no_context: bool = False
    path_instructions: list[PathInstruction] = field(default_factory=list)
    high_risk_paths: list[HighRiskPath] = field(default_factory=list)
    config_warnings: list[str] = field(default_factory=list)
    config_has_error: bool = False  # set True on parse-error / missing-yq / wrong-variant


@dataclass
class ChangeManifest:
    files_added: list[str] = field(default_factory=list)
    files_removed: list[str] = field(default_factory=list)
    files_renamed: list[dict[str, str]] = field(default_factory=list)
    # Every test file in the diff, added OR modified (FR-010). Kept separate
    # from files_added because a developer extending an existing suite HAS
    # added coverage, and the false finding this closes — "no tests were added"
    # — is about coverage, not about file creation.
    tests_in_diff: list[str] = field(default_factory=list)


@dataclass
class CallResult:
    content: str | None
    error_kind: str | None  # auth | rate_limit | transient | parse | empty | unknown | None
    retryable: bool = False
    status_code: int | None = None
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    # Operator-facing failure detail (provider error body, truncated + redacted).
    # NEVER logged to telemetry — FR-015 forbids message bodies in calls.jsonl,
    # so this rides the return value to stderr only. The providers already read
    # this body off the wire and then discarded it, which is why 136 consecutive
    # HTTP 400s never revealed they were answering, verbatim,
    # "Use 'max_completion_tokens' instead".
    error_detail: str | None = None


def merge_cli_into_config(args: Any, base: RunConfig) -> RunConfig:
    """Apply CLI argv overrides on top of file-loaded RunConfig.

    Boolean CLI flags only override the base config when explicitly passed
    (i.e., truthy on argv). Argparse defaults to False for `store_true` flags;
    if we assigned unconditionally, a config-file true would be clobbered by
    the argparse default. We OR the two so that `truthy in either source` wins.
    """
    base.base = args.base if args.base is not None else base.base
    base.scope = args.type
    base.config_path = args.config
    base.plain = bool(args.plain) and not args.agent
    base.agent = bool(args.agent)
    # OR-merge: don't let argparse's False default clobber a config-file True
    base.no_color = bool(base.no_color) or bool(args.no_color)
    base.force_full = bool(base.force_full) or bool(args.force_full)
    base.no_static_analyzers = bool(base.no_static_analyzers) or bool(args.no_static_analyzers)
    base.no_cascade = bool(base.no_cascade) or bool(args.no_cascade)
    base.no_verify = bool(base.no_verify) or bool(getattr(args, "no_verify", False))
    base.dry_run = bool(base.dry_run) or bool(args.dry_run)
    base.no_context = bool(base.no_context) or bool(getattr(args, "no_context", False))
    base.strict_config = bool(base.strict_config) or bool(args.strict_config)
    base.require_changes = bool(base.require_changes) or bool(getattr(args, "require_changes", False))
    if args.auto_pause_n is not None:
        base.auto_pause_n = args.auto_pause_n
    if args.max_concurrency is not None:
        base.max_concurrency = args.max_concurrency
    if args.dedup_window is not None:
        base.dedup_window = args.dedup_window
    if args.max_cost_usd is not None:
        base.max_cost_usd = args.max_cost_usd
    return base
