"""The finding envelope: types + validation against the packaged contract (T024).

A finding leaves a reviewer as prose. Before it reaches a developer it has to
answer one question: *is the thing you asserted actually true of this checkout?*
The envelope is where that answer lives, and the schema is what stops it from
being skipped.

The design constraint that shapes everything here is FR-022: a reviewer reads
diff content, diff content is attacker-influenceable, therefore **a claim is
attacker-influenceable output**. Nothing in this module may treat a claim as
trustworthy. It is parsed, validated against a closed schema, and handed to a
verifier that resolves its `input` through an allowlist — never interpolated,
never executed. See `verify.resolve_input`.

`claim: null` is a first-class, correct state, not a degraded one. A finding
about a design consequence has no checkable fact in it; penalising that would
drop exactly the findings a reviewer is uniquely good at. The schema therefore
*requires* a null claim to carry `verdict: unverifiable`, and requires the key
to be present rather than merely allowed — an omitted `claim` alongside
`verdict: confirmed` was a real bypass of the whole mechanism.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_PATH = Path(__file__).parent.parent / "gates" / "schemas" / "finding-envelope.schema.json"

CONFIRMED = "confirmed"
REFUTED = "refuted"
UNVERIFIABLE = "unverifiable"
UNCHECKED = "unchecked"
VERDICTS = (CONFIRMED, REFUTED, UNVERIFIABLE, UNCHECKED)

# Kinds are drawn from the 2026-08-13 gold set rather than invented. Every
# checkable-false finding measured was one of these three: return_shape (the
# describeThrown recurrence), predicate_result (the AST predicate claim), or
# symbol_absent ("no tests exist").
ENUMERATE_KINDS = ("symbol_exists", "symbol_absent", "count")
TYPECHECK_KINDS = ("return_shape", "predicate_result")


class EnvelopeError(ValueError):
    """An envelope violated the contract. Raised, never returned as a default.

    Returning a default here would reproduce the failure this whole spec exists
    to close: a malformed claim would silently become "nothing to check", which
    renders identically to "checked and clean".
    """


@dataclass(frozen=True)
class Check:
    method: str  # enumerate | typecheck | execute
    input: str

    def to_dict(self) -> dict[str, str]:
        return {"method": self.method, "input": self.input}


@dataclass(frozen=True)
class Claim:
    kind: str
    subject: str
    expected: str
    check: Check

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "expected": self.expected,
            "check": self.check.to_dict(),
        }


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_envelope(doc: dict[str, Any]) -> None:
    """Raise EnvelopeError if `doc` is not a valid finding envelope."""
    try:
        jsonschema.validate(doc, load_schema())
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        raise EnvelopeError(f"{path}: {e.message}") from e


def claim_from_dict(raw: Any) -> Claim | None:
    """Parse a reviewer-supplied claim. `None` and `null` both mean "judgment"."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise EnvelopeError(f"claim must be an object or null, got {type(raw).__name__}")
    missing = [k for k in ("kind", "subject", "expected", "check") if k not in raw]
    if missing:
        raise EnvelopeError(f"claim is missing {', '.join(missing)}")
    check = raw["check"]
    if not isinstance(check, dict) or "method" not in check or "input" not in check:
        raise EnvelopeError("claim.check requires both method and input")
    # Reject non-strings; do NOT coerce them. `str({"a": 1})` yields the string
    # "{'a': 1}", which then flows on as a perfectly well-formed subject or
    # search input and gets verified — the malformed claim disappears into a
    # plausible one. Raising surfaces it as `unchecked` with a log line instead,
    # which is the whole difference between "we could not check this" and "we
    # checked something else".
    fields = {"kind": raw["kind"], "subject": raw["subject"], "expected": raw["expected"],
              "check.method": check["method"], "check.input": check["input"]}
    bad = [k for k, v in fields.items() if not isinstance(v, str)]
    if bad:
        raise EnvelopeError(
            f"claim fields must be strings, got non-string: {', '.join(sorted(bad))}"
        )
    return Claim(
        kind=raw["kind"],
        subject=raw["subject"],
        expected=raw["expected"],
        check=Check(method=check["method"], input=check["input"]),
    )


def build_envelope(
    *,
    gate_id: str,
    file: str,
    severity: str,
    body: str,
    claim: Claim | None,
    verdict: str,
    line: int | None = None,
    verdict_detail: str | None = None,
) -> dict[str, Any]:
    """Assemble and validate an envelope.

    Validation is not optional and not deferred to a caller. Every invariant the
    schema encodes — a null claim implies `unverifiable`, a refutation names what
    refuted it — is a rule this session watched get violated by habit, so the
    only construction path runs the check.
    """
    doc: dict[str, Any] = {
        "gate_id": gate_id,
        "file": file,
        "line": line,
        "severity": severity,
        "body": body,
        "claim": claim.to_dict() if claim is not None else None,
        "verdict": verdict,
    }
    if verdict_detail is not None:
        doc["verdict_detail"] = verdict_detail
    validate_envelope(doc)
    return doc


def method_for_kind(kind: str) -> str | None:
    """The check method a claim kind is answerable by, or None if unknown.

    Used to catch a mismatched pair (`return_shape` routed to `enumerate`)
    before it reaches a verifier that would answer the wrong question and
    report the answer as though it were the right one.
    """
    if kind in ENUMERATE_KINDS:
        return "enumerate"
    if kind in TYPECHECK_KINDS:
        return "typecheck"
    return None
