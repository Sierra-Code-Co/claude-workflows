"""Aggregate findings from multiple reviewers + analyzers.

- Dedup overlapping findings (same file + ±dedup_window lines + same category)
- Promote confidence on multi-source overlap
- Apply path_instructions severity demotion (two-layer per data-model.md#PathInstruction)
- Sort by file:line for stable output
"""
from __future__ import annotations

import fnmatch
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from .output_format import drop_refuted
from .types import Finding, PathInstruction
from .verification.classify import EnvelopeError, claim_from_dict
from .verification.verify import verify_claim


SOFT_CATEGORIES = {"style", "prose", "docs", "nit"}
HARD_CATEGORIES = {"security", "correctness", "bug", "secrets"}
SUPPRESSION_KEYWORDS = ("skip", "ignore", "do not flag", "not actionable")
# Severity tier ranking for sort order (lower number = higher priority)
_SEVERITY_RANK = {"actionable": 0, "nit": 1, "info": 2}


def _overlap(a: Finding, b: Finding, window: int) -> bool:
    if a.file != b.file or a.category != b.category:
        return False
    # Never merge a checkable finding with a judgment one, even on the same
    # lines. Merging keeps ONE message and ONE claim, so the group gets a single
    # verdict — and no single verdict is right for both. Found by
    # tests/proofs/verification_stage.sh: a claim:null finding on line 19 merged
    # into a false-claim finding on line 18, the claim was refuted, and the
    # judgment finding was deleted along with it. Dedup was already lossy here
    # (the second message is discarded); verification turned lossy into silently
    # destructive.
    if (a.claim is None) != (b.claim is None):
        return False
    a_start, a_end = a.line, (a.line_end or a.line)
    b_start, b_end = b.line, (b.line_end or b.line)
    # Two intervals overlap (within `window` of slack) when the latest start is
    # before the earliest end + window. Catches contained ranges (1-100 vs 50-60).
    return max(a_start, b_start) <= min(a_end, b_end) + window


def _merge(into: Finding, src: Finding) -> Finding:
    """Merge src into into (mutates into), promoting confidence."""
    for s in src.sources:
        if s not in into.sources:
            into.sources.append(s)
    if len(into.sources) >= 2:
        into.confidence = "high-confidence"
    if src.severity == "actionable" and into.severity != "actionable":
        into.severity = "actionable"
    # `into.claim` is deliberately NOT replaced. `_overlap` guarantees both
    # sides are claim-bearing or neither is, and a merged finding renders
    # `into.message` — so the surviving claim must be the one belonging to the
    # text the developer will actually read. Adopting src's claim would verify
    # one finding's assertion and print another finding's words.
    return into


def _glob_specificity(glob: str) -> int:
    """Heuristic specificity: longer globs with fewer wildcards win."""
    return len(glob) - 5 * glob.count("*") - 5 * glob.count("?")


def _demote_for_path_instructions(findings: list[Finding], path_instructions: list[PathInstruction]) -> list[Finding]:
    if not path_instructions:
        return findings
    for f in findings:
        if f.category in HARD_CATEGORIES:
            continue
        # Collect all matching path_instructions, then pick the most specific.
        # Prevents broad globs (e.g., '**/*') from shadowing narrower ones.
        matches = [pi for pi in path_instructions if fnmatch.fnmatch(f.file, pi.path_glob)]
        if not matches:
            continue
        best = max(matches, key=lambda pi: _glob_specificity(pi.path_glob))
        inst_lower = best.instructions.lower()
        if not any(kw in inst_lower for kw in SUPPRESSION_KEYWORDS):
            continue
        if f.category in SOFT_CATEGORIES and f.severity in ("actionable", "nit"):
            f.severity = "info"
    return findings


# A reviewer speculating about completeness is answering a question it cannot
# answer: the sites it is guessing about are, by construction, the ones not in
# the diff it was shown. Constitution Principle III routes that question to the
# enumerator instead. Detection needs BOTH a hedge and a completeness noun —
# one alone matches ordinary prose constantly ("this may be wrong", "the call
# site is fine").
_HEDGES = (
    "may ", "might ", "could ", "possibly", "potentially", "likely ",
    "consider checking", "worth checking", "should verify", "make sure",
)
_COMPLETENESS_NOUNS = (
    "call site", "callsite", "other occurrence", "similar instance",
    "other instance", "elsewhere", "other place", "remaining", "all the sites",
    "same pattern", "other usages", "other usage",
)


def _is_completeness_speculation(f: Finding) -> bool:
    """Prose matching, and therefore approximate — which is exactly why the
    caller DEMOTES AND ANNOTATES rather than drops. A false positive here costs
    a reviewer finding its severity, so it must not cost the finding itself.
    Deterministic analyzers are never candidates; they do not speculate."""
    if any(s in ("gitleaks", "markdownlint", "actionlint", "shellcheck", "ast-grep") for s in f.sources):
        return False
    msg = (f.message or "").lower()
    return any(h in msg for h in _HEDGES) and any(n in msg for n in _COMPLETENESS_NOUNS)


def supersede_completeness_speculation(
    findings: list[Finding], coverage: dict | None
) -> list[Finding]:
    """Replace "you may have missed some sites" with what was actually counted.

    No-ops unless the enumerator genuinely ran to completion (`covered`). If it
    did not, the reviewer's hedge is the ONLY answer available and silencing it
    would trade a vague warning for no warning — strictly worse (FR-004
    acceptance 3).
    """
    if not coverage or not coverage.get("covered"):
        return findings
    # Absent counts are NOT zero. Coercing them would print "enumerated the
    # whole checkout: 0 site(s)" — a confident, specific, fabricated number —
    # over a reviewer's correct hedge. Missing means unknown, and unknown must
    # resolve to "leave the hedge alone", the same defaulting rule as
    # `coverable_file_count=None` in the structural gate.
    if coverage.get("finding_count") is None or coverage.get("file_count") is None:
        return findings
    total = int(coverage["finding_count"])
    files = int(coverage["file_count"])
    rules = ", ".join(coverage.get("rule_ids") or []) or "the configured rules"
    answer = (
        f"[superseded by enumeration] {rules} enumerated the whole checkout: "
        f"{total} site(s) across {files} file(s). Original reviewer note: "
    )
    for f in findings:
        if _is_completeness_speculation(f):
            f.severity = "info"
            f.message = answer + (f.message or "")
    return findings


def verify_findings(
    findings: list[Finding],
    repo_root: Path,
    *,
    rule_paths: dict[str, Path] | None = None,
    log: Callable[[str], None] = lambda m: print(m, file=sys.stderr),
) -> list[Finding]:
    """Resolve every finding's claim against the checkout (T029, FR-002/FR-003).

    Runs after dedup so a claim three reviewers raised is checked once, and
    before tiering so a refutation can remove a finding from the severity counts
    rather than merely from the printout.

    A malformed claim is `unchecked`, never dropped and never confirmed. A
    reviewer that emits garbage should cost us a marker, not a finding — and
    certainly not a fabricated verification.
    """
    for f in findings:
        try:
            claim = claim_from_dict(f.claim)
        except EnvelopeError as e:
            log(f"[verify] malformed claim on {f.file}:{f.line}: {e}")
            f.verdict, f.verdict_detail = "unchecked", f"claim did not parse: {e}"
            continue
        v = verify_claim(claim, repo_root, rule_paths=rule_paths, log=log)
        f.verdict, f.verdict_detail = v.verdict, v.detail
    return findings


def aggregate(
    findings_groups: Iterable[Iterable[Finding]],
    path_instructions: list[PathInstruction] | None = None,
    dedup_window: int = 5,
    structural_coverage: dict | None = None,
    repo_root: Path | None = None,
    rule_paths: dict[str, Path] | None = None,
    verify_log: Callable[[str], None] | None = None,
    refuted_out: list[Finding] | None = None,
) -> list[Finding]:
    """Merge groups of findings, dedup, verify, demote per path_instructions, sort.

    `repo_root=None` disables verification entirely and leaves every verdict at
    None — the honest encoding of "the stage did not run", which renders exactly
    as it did before US2. Callers that want the stage pass the checkout.

    Refuted findings are removed here, not only at render time, so exit codes and
    printed output can never disagree. `refuted_out`, when given, receives them:
    the count is reported by the caller (FR-003), because a silent drop is
    indistinguishable from never having generated the finding.
    """
    flat: list[Finding] = []
    for group in findings_groups:
        flat.extend(group)

    merged: list[Finding] = []
    for f in flat:
        # Try merge into existing
        for existing in merged:
            if _overlap(existing, f, dedup_window):
                _merge(existing, f)
                break
        else:
            merged.append(f)

    # After dedup so a claim made by three reviewers is superseded once, before
    # sort so the demotion actually moves it down the list.
    merged = supersede_completeness_speculation(merged, structural_coverage)
    if repo_root is not None:
        kwargs = {"rule_paths": rule_paths}
        if verify_log is not None:
            kwargs["log"] = verify_log
        merged = verify_findings(merged, repo_root, **kwargs)
        merged, refuted = drop_refuted(merged)
        if refuted_out is not None:
            refuted_out.extend(refuted)
    merged = _demote_for_path_instructions(merged, path_instructions or [])
    # Severity tier first (actionable → nit → info), then file, then line.
    # Prevents high-priority findings from being buried behind earlier-file nits.
    merged.sort(key=lambda x: (_SEVERITY_RANK.get(x.severity, 99), x.file, x.line))
    return merged
