"""Single-writer telemetry log. Thread-safe append to JSONL via module-level lock."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_FALLBACK_LOG_DIR = str(Path.home() / ".claude" / "review-plan-v2" / "logs")


def _log_dir() -> Path:
    """Resolve the log dir each call (env may differ across processes/tests)."""
    d = Path(os.environ.get("REVIEW_PLAN_V2_LOG_DIR", _FALLBACK_LOG_DIR))
    d.mkdir(parents=True, exist_ok=True)
    return d


# Strict allowed keys per FR-015 — no prompt content, no diff content, no message bodies
_ALLOWED_KEYS = {
    "provider", "model", "reviewer", "input_tokens", "output_tokens",
    "latency_ms", "status_code", "error_kind", "retry_count", "timestamp",
    # The budget in force and whether the call came close to exhausting it.
    # Without these the log is censored at whatever the ceiling happened to be
    # that day — `output_tokens max ever = 4,587` once read as "8192 is plenty"
    # when every call that needed more had already been dropped. Counts and a
    # boolean; no prompt, diff, or message content (FR-015).
    "max_tokens", "near_budget",
    # The LATENCY ceilings in force, for the same reason and learned the same
    # way. A row reading `latency_ms: 180200, error_kind: transient` does not say
    # whether 180s was the limit or a coincidence, so reconstructing the
    # 2026-08-25 timeout kills meant reading the constant out of the source as it
    # stands today and assuming it had not changed. Two floats, no content.
    "timeout_sec", "max_call_sec",
}


# Per-gate outcome keys (T043). Deliberately a SEPARATE allowlist from the
# per-call one: sharing it would let a gate record carry `model`, or a future
# call record carry a gate id. An allowlist is worth having because it says
# what THIS record shape may contain, not what some record shape may.
_ALLOWED_GATE_KEYS = {
    "gate", "tier", "blocking", "raised", "addressed", "timestamp",
}


def log_gate_outcome(record: dict[str, Any], filename: str = "gates.jsonl") -> None:
    """Append one gate's per-run counts, for FR-014 acceptance measurement.

    FR-014 permits promoting a probabilistic gate to blocking only with
    MEASURED acceptance, and until now nothing measured it — which is exactly
    why all four reviewers sit at `advisory` with `promoted_at` absent. This is
    the raw material for that number.

    "Accepted" cannot be observed inside a single run: whether a finding was
    any good is a fact about what the developer did next. That signal already
    exists here, though — `context/rounds.py` suppresses a repeat finding ONLY
    when the code it points at has changed since, which is precisely "the
    developer addressed it", and a finding that keeps returning untouched is
    one they declined to act on. So `addressed` is fed from round-memory
    suppressions rather than invented.

    COUNTS ONLY (FR-021): a gate id, its declared tier, and two integers. No
    message bodies, no file paths, no diff content. Enforced here rather than
    trusted at each call site, the same way `log_call` does it, because a
    telemetry file that has accumulated content is not fixable after the fact.
    """
    safe = {k: v for k, v in record.items() if k in _ALLOWED_GATE_KEYS}
    safe.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    line = json.dumps(safe, sort_keys=True)
    path = _log_dir() / filename
    with _lock, open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def acceptance_for(gate_id: str, filename: str = "gates.jsonl") -> dict[str, int]:
    """→ {"runs": n, "raised": n, "addressed": n} for one gate.

    Read back so a promotion decision can cite a number rather than a feeling.
    A missing or unreadable log yields zeros instead of raising: this informs a
    judgement call and must never be able to break a review.
    """
    totals = {"runs": 0, "raised": 0, "addressed": 0}
    path = _log_dir() / filename
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return totals
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            # A torn line from a killed process must not discard the rest of the
            # history; the whole point is a running total.
            continue
        if not isinstance(rec, dict) or rec.get("gate") != gate_id:
            continue
        totals["runs"] += 1
        for k in ("raised", "addressed"):
            try:
                totals[k] += int(rec.get(k, 0))
            except (TypeError, ValueError):
                continue
    return totals


def log_call(record: dict[str, Any], filename: str = "calls.jsonl") -> None:
    """Append a single sanitized record line to the telemetry log.

    `timestamp` was in _ALLOWED_KEYS from the start but no caller ever passed
    it, so 30,956 records carried no time axis — dating the 2026-05-09 OpenAI
    cascade breakage required using file line-order as a proxy, and "zero
    failures since the fix" was unprovable. Stamped here rather than in each
    provider so no future provider can forget it.
    """
    safe = {k: v for k, v in record.items() if k in _ALLOWED_KEYS}
    safe.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    line = json.dumps(safe, sort_keys=True)
    path = _log_dir() / filename
    with _lock, open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
