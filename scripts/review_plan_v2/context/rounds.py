"""Round-N finding memory (T048, #20).

Filed 2026-04-30: on the second review of a branch, findings the developer has
already dealt with come back identical, and the noise trains people to skim.

The suppression rule is deliberately narrow, because dropping a finding is the
most dangerous thing this tool can do. A finding is suppressed only when BOTH
hold:

  1. it is fingerprint-identical to one raised in an earlier round, and
  2. **the code it points at has changed since** — measured by hashing the
     anchor lines at record time and re-hashing them now.

Condition 2 is what separates "addressed" from "still there". Without it, a
finding the developer ignored would vanish on round 2, which converts this
feature from noise-reduction into a way to make a real problem disappear by
running the tool twice.

Two more guards, both borrowed from stages that already got this right:

  * every suppression is NAMED in the output, not counted (the FR-011 rule) —
    a developer must be able to see exactly what was withheld; and
  * `--force-full` shows everything, so a suppressed finding is always
    recoverable, the same escape hatch `--no-verify` gives the verification
    stage.

Anchors are hashed rather than stored, so nothing in the state file contains
source text — FR-015 bars message bodies and diff content from persisted
telemetry, and this file lives beside that telemetry.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from ..paths import contained
from ..types import Finding

#: Lines either side of the anchor included in the hash. Wide enough that a real
#: edit to the flagged code changes it, narrow enough that an unrelated edit ten
#: lines away does not.
ANCHOR_RADIUS = 3

#: How many rounds of history to keep. The question is only ever "was this
#: raised before, and has it moved since", so unbounded growth buys nothing.
MAX_ROUNDS = 5

_WS_RE = re.compile(r"\s+")
_NUM_RE = re.compile(r"\b\d+\b")


@dataclass(frozen=True)
class Suppression:
    file: str
    line: int
    message: str
    first_seen_round: int
    fingerprint: str = ""


def fingerprint(finding: Finding) -> str:
    """Stable identity for "the same finding, raised again".

    Normalised so that trivial rewording by a non-deterministic model does not
    read as a new finding: whitespace collapsed, numbers masked (line numbers and
    counts drift between rounds), lowercased, and truncated — the tail of a long
    message is where models vary most.
    """
    body = _NUM_RE.sub("#", _WS_RE.sub(" ", finding.message.strip().lower()))[:160]
    raw = repr((finding.file, finding.category, body))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def anchor_hash(repo_root: Path | str, file: str, line: int,
                radius: int = ANCHOR_RADIUS) -> str | None:
    """Hash of the lines around `line`. None when the file cannot be read.

    None is a first-class answer and NOT a match: if the anchor cannot be read
    now, we cannot say the code changed, so the finding is not suppressed. The
    safe direction is always "show it".
    """
    root = Path(repo_root)
    path = root / file
    # `Path("/repo") / "/etc/passwd"` is `/etc/passwd`: pathlib DISCARDS the left
    # side when the right is absolute. `file` arrives from reviewer output, so it
    # is model-controlled — a hallucinated or hostile path would otherwise make
    # this read an arbitrary file. Only a hash leaves the function, but reading
    # the file at all is the part to prevent.
    if not contained(path, root):
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    start = max(0, line - 1 - radius)
    window = "\n".join(lines[start:line + radius])
    return hashlib.sha256(window.encode("utf-8")).hexdigest()[:32]


def record_for(repo_root: Path | str, findings: list[Finding], round_number: int) -> list[dict]:
    """Serialise findings for the state file. Hashes only — never message text.

    `first_round` and `round` are separate on purpose and the distinction is
    load-bearing. `first_round` is when the finding was originally raised and
    never moves; `round` is when the record was last touched and is what `trim`
    ages out. Collapsing them into one field meant a suppressed finding was
    re-recorded with the CURRENT anchor, so a round later the anchor matched,
    the finding read as "not addressed", and it came back — the feature undoing
    itself on the third run.
    """
    out: list[dict] = []
    for f in findings:
        out.append({
            "fingerprint": fingerprint(f),
            "anchor": anchor_hash(repo_root, f.file, f.line),
            "first_round": round_number,
            "round": round_number,
        })
    return out


def carry_forward(prior: list[dict], suppressed: list[Suppression],
                  round_number: int) -> list[dict]:
    """Refresh the `round` of records for findings suppressed THIS round.

    The ORIGINAL anchor is kept: it is the evidence that the code has moved
    since the finding was raised, and replacing it with the current one destroys
    exactly that. Only recency is updated, so an addressed finding does not age
    out of the window and reappear as though it were new.
    """
    if not suppressed:
        return prior
    stale = {s.fingerprint for s in suppressed}
    out: list[dict] = []
    for record in prior:
        if isinstance(record, dict) and record.get("fingerprint") in stale:
            record = {**record, "round": round_number}
        out.append(record)
    return out


def _first_round(record: dict) -> int:
    """When this finding was FIRST raised, tolerating pre-`first_round` rows."""
    try:
        return int(record.get("first_round", record.get("round", 0)))
    except (TypeError, ValueError):
        return 0


def partition(repo_root: Path | str, findings: list[Finding], prior: list[dict],
              ) -> tuple[list[Finding], list[Suppression]]:
    """Split into (kept, suppressed).

    Suppressed = raised in an earlier round AND its anchor has since changed.
    """
    if not prior:
        return list(findings), []

    by_fingerprint: dict[str, dict] = {}
    for record in prior:
        # The state file is shared with the auto-pause counter and gets edited by
        # hand during debugging. A junk row must degrade to "no memory", never
        # take the review down — a crash here would turn a noise-reduction
        # feature into an outage.
        if not isinstance(record, dict):
            continue
        fp = record.get("fingerprint")
        if not isinstance(fp, str):
            continue
        # Keep the EARLIEST sighting: "first raised in round 1" is the useful
        # fact to report, and re-recording each round would otherwise walk it
        # forward to "round 4" and lose it.
        existing = by_fingerprint.get(fp)
        if existing is None or _first_round(record) < _first_round(existing):
            by_fingerprint[fp] = record

    kept: list[Finding] = []
    suppressed: list[Suppression] = []
    for f in findings:
        record = by_fingerprint.get(fingerprint(f))
        if record is None:
            kept.append(f)
            continue
        previous_anchor = record.get("anchor")
        current_anchor = anchor_hash(repo_root, f.file, f.line)
        # Unreadable now, unrecorded then, or a malformed row: cannot establish
        # that the code moved, so the finding stands.
        #
        # The `isinstance` check is not defensive noise. A junk anchor — an int,
        # an empty string, a hand-edited scribble — can never EQUAL the current
        # hash, so without this it takes the "changed" branch and suppresses a
        # finding nobody addressed. Malformed input must fail toward showing
        # the finding, never toward hiding it.
        if (not isinstance(previous_anchor, str) or not previous_anchor
                or current_anchor is None):
            kept.append(f)
            continue
        if previous_anchor == current_anchor:
            # Raised before and the code is untouched — it is still true, and
            # suppressing it here is how a tool teaches people that ignoring it
            # works.
            kept.append(f)
            continue
        suppressed.append(Suppression(
            file=f.file, line=f.line,
            message=f.message[:120],
            first_seen_round=_first_round(record),
            fingerprint=fingerprint(f),
        ))
    return kept, suppressed


def render_suppressions(suppressed: list[Suppression]) -> list[str]:
    """Operator-facing lines. Named, never merely counted."""
    if not suppressed:
        return []
    lines = [
        f"[ROUND-MEMORY] {len(suppressed)} finding(s) were raised in an earlier "
        "round and the code they point at has changed since, so they are not "
        "shown again. Re-run with --force-full to see them:"
    ]
    for s in suppressed:
        lines.append(f"  - {s.file}:{s.line} (round {s.first_seen_round}) {s.message}")
    return lines


def trim(records: list[dict], round_number: int, max_rounds: int = MAX_ROUNDS) -> list[dict]:
    """Drop history older than `max_rounds` rounds.

    Tolerates the same junk rows `partition` does. It did not, which made the
    two functions disagree about what a valid record is — one skipping a
    hand-edited row and the other raising on it, in a file whose docstring says
    it is shared and hand-edited.
    """
    floor = round_number - max_rounds
    out: list[dict] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        try:
            round_of = int(r.get("round", 0))
        except (TypeError, ValueError):
            continue
        if round_of > floor:
            out.append(r)
    return out
