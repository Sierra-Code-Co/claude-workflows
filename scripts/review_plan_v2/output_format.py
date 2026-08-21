"""Render findings to plain-text or NDJSON. Parse-compatible with `coderabbit review --plain` (FR-013)."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Iterable

from .types import Finding


SEVERITY_PREFIX = {
    "actionable": "[ACTIONABLE]",
    "nit": "[NIT]",
    "info": "[INFO]",
}

# How long a verification detail may run before it is elided. The detail is
# evidence — "declares ThrownDescription = {errName, errMessage, errCode}" is
# the whole reason to believe the refutation — so it is truncated, never
# dropped, and the ellipsis says which happened.
MAX_VERDICT_DETAIL = 160


def drop_refuted(findings: Iterable[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Split findings into (kept, refuted). FR-002.

    Lives here rather than in the aggregator because presentation is what FR-002
    governs — but the aggregator calls it too, so exit codes and rendered output
    can never disagree about what the review found. A run that prints nothing and
    exits 1 is its own kind of silent failure.

    A refuted finding is dropped, and the COUNT of drops is reported. Silently
    removing findings would be indistinguishable from never generating them, and
    the whole argument for this stage is that the difference is visible.
    """
    kept: list[Finding] = []
    refuted: list[Finding] = []
    for f in findings:
        (refuted if f.verdict == "refuted" else kept).append(f)
    return kept, refuted


def _verdict_marker(f: Finding) -> str:
    """The suffix a finding carries out of verification, or "" if none applies.

    `None` (the stage did not run) is deliberately unmarked: annotating every
    finding on a verification-less run would train the reader to ignore the
    marker, and the absence of the stage belongs in run health, not on each line.
    """
    if f.verdict in (None, "refuted"):
        return ""
    # Strip ALL control characters, not just LF.
    #
    # `verdict_detail` carries checkout-derived text — file names, declared type
    # names — so a repository can put whatever it likes in it. CR alone rewrites
    # the line in a terminal; ESC opens the door to cursor movement, colour, and
    # title-setting sequences. The `safe_msg` path already scrubbed \r\n, \n and
    # \r; this one replaced only \n, so the newer channel was the weaker one.
    # Same class as FR-022: content from the thing under review reaching a
    # rendering surface unfiltered.
    detail = "".join(
        " " if (ord(c) < 0x20 or ord(c) == 0x7F) else c
        for c in (f.verdict_detail or "")
    ).strip()
    if len(detail) > MAX_VERDICT_DETAIL:
        detail = detail[:MAX_VERDICT_DETAIL - 1] + "…"
    label = {
        "confirmed": "verified",
        "unverifiable": "UNVERIFIED",
        "unchecked": "UNCHECKED",
    }.get(f.verdict, f.verdict)
    return f"  [{label}: {detail}]" if detail else f"  [{label}]"


def render_plain(findings: Iterable[Finding], summary: dict | None = None) -> str:
    """Return CR-style plain-text output. Each line: `[TIER] file:line[-end] [category] message`."""
    lines: list[str] = []
    findings_list = list(findings)
    # Coverage first: "No findings." on a run that never executed is the
    # single most dangerous string this tool can print, so the caveat has to
    # sit ABOVE it where an operator (or a piping script) sees it first.
    failed = int((summary or {}).get("failed_task_count") or 0)
    if failed:
        total = int((summary or {}).get("total_task_count") or 0)
        scope = f"{failed}/{total}" if total else str(failed)
        lines.append(
            f"[INCOMPLETE] {scope} reviewer tasks did not run — this review is "
            "PARTIAL and its verdict is not trustworthy. Re-run, or raise "
            "--max-concurrency, or narrow the diff."
        )
        lines.append("")
    # A leg that failed EVERY call needs its own line. The [INCOMPLETE] banner
    # above prescribes re-running or lowering concurrency, which is the right
    # advice for a timeout and useless advice for a stale model id or a
    # rejected parameter — the failure that actually persists. `providers_called`
    # has always carried this information and was never rendered anywhere.
    for entry in (summary or {}).get("providers_called") or []:
        # Defensive: this renders a diagnostic about a broken run, so it must
        # not itself crash on a malformed summary and take the findings with it.
        if not isinstance(entry, dict):
            continue
        try:
            calls = int(entry.get("calls") or 0)
            failed = int(entry.get("failed") or 0)
            starved = int(entry.get("starved") or 0)
            # Absent and empty DERIVE; 0 is a number. Two bugs live here and
            # they pull in opposite directions, which is why the check is
            # spelled out rather than written as a one-liner:
            #
            #   `int(x) if x is not None else ...` — an `"attempted": ""` raises
            #   inside the try, the `except` skips the whole entry, and BOTH the
            #   STARVED and DEAD-LEG banners for that provider vanish. A
            #   malformed field silently deleting a fail-visible warning, inside
            #   the warning.
            #
            #   `x or None` — a legitimate `attempted: 0` reads as missing and
            #   gets derived back up to calls - starved, which can fire DEAD-LEG
            #   for a leg that never attempted anything.
            raw_attempted = entry.get("attempted")
            if raw_attempted is None or raw_attempted == "":
                attempted = calls - starved
            else:
                attempted = int(raw_attempted)
        except (TypeError, ValueError):
            continue
        if starved > 0:
            # A DISTINCT line, because the operator's next move is different:
            # narrow the diff or raise concurrency, not go debug a provider.
            lines.append(
                f"[STARVED] provider '{entry.get('provider')}' had {starved} of "
                f"{calls} task(s) never start — they ran out of run budget while "
                "queued. This is queue pressure, not a broken leg; re-running with "
                "a narrower diff or a higher --max-concurrency should fix it."
            )
            lines.append("")
        # `attempted`, never `calls`. On 2026-08-14 both the openai and google
        # legs were reported as "a configuration failure, not a flaky run" when
        # every one of their tasks had simply been queued behind 92 starved ones
        # and never reached a provider at all. Re-running the identical branch at
        # concurrency 12 produced zero of these banners with nothing about either
        # provider changed — so the banner was reporting queue pressure as
        # misconfiguration.
        #
        # That matters beyond the wrong words: a fail-visible mechanism that
        # cries wolf gets ignored, and the next real 136-for-0 dead leg goes
        # unnoticed the way the last one did for three months.
        if attempted > 0 and failed == attempted:
            lines.append(
                f"[DEAD-LEG] provider '{entry.get('provider')}' failed all {attempted} "
                "calls it actually made and contributed no findings — this is a "
                "configuration failure, not a flaky run. Re-running will not fix it."
            )
            lines.append("")
    # Absent deterministic coverage sits above "No findings." for the same
    # reason [INCOMPLETE] does: a completeness question that was never asked
    # and a completeness question answered "none" print identically, and the
    # reader stops at the first line either way (FR-004 acceptance 4).
    for gap in (summary or {}).get("structural_coverage_gaps") or []:
        lines.append(
            f"[NO-STRUCTURAL-COVERAGE] {gap} — completeness questions "
            "(\"did I get all the call sites?\") were NOT answered for this run. "
            "A reviewer cannot answer them; do not read a clean verdict as coverage."
        )
        lines.append("")
    # Context the reviewers were configured to receive and did not (FR-011).
    # Sits with the other coverage banners for the same reason: a review run
    # with a symbol's definition missing is not the same review as one with it,
    # and only this line distinguishes them after the fact.
    for gap in (summary or {}).get("context_gaps") or []:
        lines.append(
            f"[CONTEXT-GAP] {gap}. Findings that assert what those symbols "
            "contain or return rest on a guess."
        )
        lines.append("")
    # Round memory (T048). Sits with the other "what you are not seeing" lines.
    for line in (summary or {}).get("round_memory") or []:
        lines.append(line)
    if (summary or {}).get("round_memory"):
        lines.append("")
    # FR-013 (T042). Belongs in the same family: things true of this run that
    # the exit code alone cannot express. Here it is the reverse of the others —
    # findings you CAN see that are deliberately not failing the run.
    for line in (summary or {}).get("advisory_notice") or []:
        lines.append(line)
    if (summary or {}).get("advisory_notice"):
        lines.append("")
    # A refuted finding is not shown (FR-002), so the COUNT has to be, or the
    # stage is indistinguishable from a prompt change that produced fewer
    # findings. This line is the receipt for work the reader cannot otherwise see.
    dropped = int((summary or {}).get("refuted_dropped") or 0)
    if dropped:
        lines.append(
            f"[VERIFIED-OUT] {dropped} finding(s) asserted something checkable that "
            "turned out to be false about this checkout, and are not shown. "
            "Re-run with --no-verify to see them."
        )
        lines.append("")
    if not findings_list:
        lines.append("No findings.")
    else:
        for f in findings_list:
            prefix = SEVERITY_PREFIX.get(f.severity, "[INFO]")
            line_num = f.line if f.line is not None else 0  # whole-file finding renders as file:0
            line_part = f"{line_num}-{f.line_end}" if f.line_end and f.line_end != line_num else str(line_num)
            # Sanitize embedded newlines so each finding stays on a single line
            # (preserves grep-compat per FR-013; otherwise downstream `grep '^\[ACTIONABLE\]'` breaks)
            safe_msg = (f.message or "").replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
            marker = _verdict_marker(f).replace("\n", " ")
            lines.append(f"{prefix} {f.file}:{line_part} [{f.category}] {safe_msg}{marker}")
    if summary:
        lines.append("")
        lines.append(_summary_footer(findings_list, summary))
    return "\n".join(lines) + "\n"


def render_agent_ndjson(findings: Iterable[Finding], summary: dict) -> str:
    """Return NDJSON: one finding per line + a final summary line."""
    out: list[str] = []
    for f in findings:
        out.append(json.dumps({"type": "finding", **_finding_dict(f)}, sort_keys=True))
    out.append(json.dumps({"type": "summary", **summary}, sort_keys=True))
    return "\n".join(out) + "\n"


def _finding_dict(f: Finding) -> dict:
    d = asdict(f)
    return d


def _summary_footer(findings: list[Finding], summary: dict) -> str:
    counts = {"actionable": 0, "nit": 0, "info": 0}
    for f in findings:
        if f.severity in counts:
            counts[f.severity] += 1
    parts = [
        f"=== Summary: {counts['actionable']} actionable, {counts['nit']} nits, {counts['info']} info"
    ]
    if summary.get("auto_paused"):
        parts.append("=== Auto-paused (last N runs trivial) — pass --force-full to override")
    if summary.get("config_warnings"):
        parts.append("=== Config warnings:")
        for w in summary["config_warnings"]:
            parts.append(f"  - {w}")
    if summary.get("analyzers_skipped"):
        parts.append(f"=== Analyzers skipped: {', '.join(summary['analyzers_skipped'])}")
    if summary.get("context_gaps"):
        parts.append("=== Context gaps:")
        for gap in summary["context_gaps"]:
            parts.append(f"  - {gap}")
    return "\n".join(parts)


def exit_code_for(findings: Iterable[Finding], failed_task_count: int = 0,
                  registry=None) -> int:
    """Map findings + coverage → exit code per contracts/cli-flags.md.

    Exit codes 3 (cost cap) and 5 (--strict-config) are emitted by the
    orchestrator's early-return paths before this function is reached.

    Coverage rule: if any reviewer task failed to execute, the run did not
    review everything it was asked to, so a "clean" verdict is unproven and
    MUST NOT be reported as 0 — it returns 2 (tool error) instead.

    Actionable findings still outrank incomplete coverage: a real problem was
    found and deserves to surface as a review failure (1) rather than be
    reclassified as a tooling problem. The [INCOMPLETE] banner renders either
    way, so the operator sees both facts.

    This exists because a 2026-08-01 run printed "No findings." and exited 0
    while 34 of 48 reviewer tasks had been cancelled by the wall-clock
    deadline — a gate that never ran read exactly like a gate that passed.

    FR-013 (T042): only DETERMINISTIC gates may hard-block, so an actionable
    finding sets exit 1 only when the gate that produced it is declared
    blocking. Passing NO registry keeps the pre-portfolio behaviour — every
    actionable finding blocks — because a downstream repo that has not adopted
    a portfolio must not silently get a weaker gate by upgrading this tool.

    The risk this introduces is handled in the renderer rather than here: exit
    0 with twenty advisory findings on screen must never read as "clean". See
    `render_advisory_notice`.
    """
    from .gates.attribution import blocks

    findings = list(findings)
    for f in findings:
        if f.severity == "actionable" and blocks(f, registry):
            return 1
    if failed_task_count > 0:
        return 2
    return 0


def render_advisory_notice(findings: Iterable[Finding], registry=None) -> list[str]:
    """Lines explaining why a run with findings still exits 0.

    Without this, FR-013 trades one silent failure for another. The point of
    advisory tiering is that noisy probabilistic gates stop failing builds —
    but the moment "20 findings, exit 0" is indistinguishable from "0 findings,
    exit 0", the tier has bought nothing and cost the signal instead.
    """
    from .gates.attribution import split

    if registry is None:
        return []
    _, advisory = split([f for f in findings if f.severity == "actionable"], registry)
    if not advisory:
        return []
    by_source: dict[str, int] = {}
    for f in advisory:
        for s in f.sources or ["?"]:
            by_source[s] = by_source.get(s, 0) + 1
    named = ", ".join(f"{k} ({v})" for k, v in sorted(by_source.items()))
    return [
        f"[ADVISORY] {len(advisory)} actionable finding(s) came from gates declared "
        f"advisory in gates.yml, so they do NOT fail this run: {named}.",
        "           They are printed above and are real output — advisory means "
        "not yet proven reliable enough to block on (FR-013/FR-014), not unimportant.",
    ]
