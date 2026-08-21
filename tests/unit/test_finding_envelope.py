"""Finding-envelope invariants (T023, US2).

Two layers, and the second is the point.

LAYER 1 — declared cases. Positive controls plus one negative per constraint.

LAYER 2 — mutation coverage. For every constraint in the schema, delete it and
assert that at least one declared-invalid document then validates. A constraint
no negative case exercises is a constraint the tests cannot tell you is working,
and this repo has now shipped that mistake five times:

  * the rule fixture that never matched its rule (files: filtered the path)
  * `required` satisfied by an explicit null
  * `Path.exists()` satisfied by a directory
  * `case *"$want"*` satisfied by a different version
  * a version-pin guard whose test survived removing one of four case arms

Constitution v1.1.0 Principle II (FR-008a) makes the derivation mandatory AND
machine-checkable: the constraint set is enumerated from the schema itself, so a
constraint added later without a matching negative fails this file rather than
passing silently. That is the whole difference between a derived shape list and
a recalled one — recall only ever covers what the author already thought of.
"""
from __future__ import annotations

import copy
import json
import pathlib

import jsonschema
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_PATH = (REPO_ROOT / "scripts" / "review_plan_v2" / "gates" / "schemas"
               / "finding-envelope.schema.json")
SCHEMA = json.loads(SCHEMA_PATH.read_text())


def _claim(**over):
    c = {
        "kind": "return_shape",
        "subject": "describeThrown",
        "expected": "name, message",
        "check": {"method": "typecheck", "input": "src::describeThrown"},
    }
    c.update(over)
    return c


def _env(**over):
    e = {
        "gate_id": "reviewer.correctness",
        "file": "web/src/lib/server/describe-thrown.ts",
        "line": 18,
        "severity": "major",
        "body": "describeThrown(...).errMessage may be undefined.",
        "claim": _claim(),
        "verdict": "confirmed",
    }
    e.update(over)
    return e


def _without(d: dict, key: str) -> dict:
    out = copy.deepcopy(d)
    out.pop(key, None)
    return out


# --- valid documents (anti-vacuous controls) ---------------------------------
#
# Without these, every invalid-case assertion below is satisfied by a schema
# that rejects everything.

VALID: list[tuple[str, dict]] = [
    ("checkable claim, confirmed", _env()),
    ("judgment finding: null claim + unverifiable", _env(claim=None, verdict="unverifiable")),
    ("refutation carrying its reason", _env(verdict="refuted", verdict_detail="declares errName/errMessage/errCode")),
    ("unchecked with a claim present", _env(verdict="unchecked")),
    ("line may be null", _env(line=None)),
    ("verdict_detail may be null when not refuted", _env(verdict_detail=None)),
]


# --- invalid documents, one per constraint -----------------------------------
#
# The `constraint` field is what LAYER 2 matches against, and it is why these
# are written one-violation-at-a-time. A document that breaks two rules cannot
# prove either one is load-bearing.

INVALID: list[dict] = [
    # -- root required. Each omits exactly one key. -----------------------
    {"id": "omit-gate_id", "doc": _without(_env(), "gate_id"), "constraint": "required:gate_id"},
    {"id": "omit-file", "doc": _without(_env(), "file"), "constraint": "required:file"},
    {"id": "omit-severity", "doc": _without(_env(), "severity"), "constraint": "required:severity"},
    {"id": "omit-body", "doc": _without(_env(), "body"), "constraint": "required:body"},
    {"id": "omit-verdict", "doc": _without(_env(), "verdict"), "constraint": "required:verdict"},

    # -- the omitted-claim bypass, all four verdicts. ---------------------
    # Found by review-plan-v2 on the spec PR. With `claim` merely optional, a
    # finding could carry verdict:confirmed and NO claim at all and validate —
    # defeating FR-002 entirely. The original tests only covered explicit null,
    # which is the shape the author thought of; absence is the shape a model
    # emits when it has nothing to say.
    #
    # The refuted variant carries verdict_detail on purpose: without it the case
    # would be rejected by the refuted conditional instead, and would prove
    # nothing about `required: claim`.
    {"id": "bypass-confirmed", "doc": _without(_env(verdict="confirmed"), "claim"),
     "constraint": "required:claim"},
    {"id": "bypass-refuted", "doc": _without(_env(verdict="refuted", verdict_detail="x"), "claim"),
     "constraint": "required:claim"},
    {"id": "bypass-unchecked", "doc": _without(_env(verdict="unchecked"), "claim"),
     "constraint": "required:claim"},
    {"id": "bypass-unverifiable", "doc": _without(_env(verdict="unverifiable"), "claim"),
     "constraint": "required:claim"},

    # -- allOf[0]: a null claim is not eligible for verification. ---------
    # All three non-unverifiable verdicts, because "the author tested confirmed"
    # is exactly how the sibling gate-registry schema shipped a biconditional
    # enforced in one direction.
    {"id": "null-claim-confirmed", "doc": _env(claim=None, verdict="confirmed"),
     "constraint": "allOf[0]"},
    {"id": "null-claim-refuted", "doc": _env(claim=None, verdict="refuted", verdict_detail="x"),
     "constraint": "allOf[0]"},
    {"id": "null-claim-unchecked", "doc": _env(claim=None, verdict="unchecked"),
     "constraint": "allOf[0]"},

    # -- allOf[1]: a refutation must say what refuted it. -----------------
    {"id": "refuted-no-detail", "doc": _env(verdict="refuted"), "constraint": "allOf[1]"},
    {"id": "refuted-null-detail", "doc": _env(verdict="refuted", verdict_detail=None),
     "constraint": "allOf[1]"},
    {"id": "refuted-empty-detail", "doc": _env(verdict="refuted", verdict_detail=""),
     "constraint": "allOf[1]"},

    # -- additionalProperties, all three levels. --------------------------
    {"id": "extra-root", "doc": _env(reviewer_confidence=0.9),
     "constraint": "additionalProperties:root"},
    {"id": "extra-claim", "doc": _env(claim=_claim(rationale="because")),
     "constraint": "additionalProperties:claim"},
    {"id": "extra-check", "doc": _env(claim=_claim(check={
        "method": "typecheck", "input": "src::describeThrown", "shell": "rm -rf /"})),
     "constraint": "additionalProperties:check"},

    # -- $defs/claim required. --------------------------------------------
    {"id": "claim-omit-kind", "doc": _env(claim=_without(_claim(), "kind")),
     "constraint": "claim.required:kind"},
    {"id": "claim-omit-subject", "doc": _env(claim=_without(_claim(), "subject")),
     "constraint": "claim.required:subject"},
    {"id": "claim-omit-expected", "doc": _env(claim=_without(_claim(), "expected")),
     "constraint": "claim.required:expected"},
    {"id": "claim-omit-check", "doc": _env(claim=_without(_claim(), "check")),
     "constraint": "claim.required:check"},

    # -- $defs/check required. --------------------------------------------
    {"id": "check-omit-method", "doc": _env(claim=_claim(check={"input": "x"})),
     "constraint": "check.required:method"},
    {"id": "check-omit-input", "doc": _env(claim=_claim(check={"method": "enumerate"})),
     "constraint": "check.required:input"},

    # -- value constraints. -----------------------------------------------
    {"id": "bad-severity", "doc": _env(severity="blocker"), "constraint": "enum:severity"},
    {"id": "bad-verdict", "doc": _env(verdict="probably"), "constraint": "enum:verdict"},
    {"id": "bad-kind", "doc": _env(claim=_claim(kind="vibes")), "constraint": "enum:claim.kind"},
    {"id": "bad-method", "doc": _env(claim=_claim(check={"method": "shell", "input": "x"})),
     "constraint": "enum:check.method"},
    {"id": "empty-body", "doc": _env(body=""), "constraint": "minLength:body"},
    {"id": "empty-subject", "doc": _env(claim=_claim(subject="")),
     "constraint": "minLength:claim.subject"},
    {"id": "empty-expected", "doc": _env(claim=_claim(expected="")),
     "constraint": "minLength:claim.expected"},
    {"id": "empty-check-input", "doc": _env(claim=_claim(check={"method": "enumerate", "input": ""})),
     "constraint": "minLength:check.input"},
    {"id": "line-zero", "doc": _env(line=0), "constraint": "minimum:line"},
]


@pytest.mark.parametrize("why, doc", VALID, ids=[v[0] for v in VALID])
def test_valid_envelopes_validate(why, doc):
    jsonschema.validate(doc, SCHEMA)


@pytest.mark.parametrize("case", INVALID, ids=[c["id"] for c in INVALID])
def test_invalid_envelopes_are_rejected(case):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(case["doc"], SCHEMA)


# --- LAYER 2: every constraint is exercised by a negative ---------------------


def _enumerate_constraints(schema: dict) -> list[str]:
    """Derive the constraint list FROM THE SCHEMA, not from the author.

    Recall lists what you already handle. Deriving lists what exists, which is
    how the four bypass guards above got written at all — nobody remembered the
    absent-claim case; enumerating `required` produced it.
    """
    out: list[str] = []
    for key in schema.get("required", []):
        out.append(f"required:{key}")
    for i, _ in enumerate(schema.get("allOf", [])):
        out.append(f"allOf[{i}]")
    if schema.get("additionalProperties") is False:
        out.append("additionalProperties:root")
    for defname in ("claim", "check"):
        d = schema["$defs"][defname]
        if d.get("additionalProperties") is False:
            out.append(f"additionalProperties:{defname}")
        for key in d.get("required", []):
            out.append(f"{defname}.required:{key}")
    return out


def _drop_constraint(schema: dict, constraint: str) -> dict:
    s = copy.deepcopy(schema)
    if constraint.startswith("required:"):
        s["required"] = [k for k in s["required"] if k != constraint.split(":", 1)[1]]
    elif constraint.startswith("allOf["):
        idx = int(constraint[len("allOf["):-1])
        s["allOf"] = [c for i, c in enumerate(s["allOf"]) if i != idx]
    elif constraint == "additionalProperties:root":
        s.pop("additionalProperties", None)
    elif constraint.startswith("additionalProperties:"):
        s["$defs"][constraint.split(":", 1)[1]].pop("additionalProperties", None)
    elif ".required:" in constraint:
        defname, key = constraint.split(".required:")
        d = s["$defs"][defname]
        d["required"] = [k for k in d["required"] if k != key]
    else:  # pragma: no cover - guarded by the enumeration above
        raise AssertionError(f"unknown constraint form: {constraint}")
    return s


CONSTRAINTS = _enumerate_constraints(SCHEMA)


def test_the_constraint_enumeration_is_not_empty():
    """Anti-vacuous control for LAYER 2 itself.

    `all([])` is True and every for-loop over an empty list passes. An
    enumeration bug would otherwise turn the mutation test into a no-op that
    reports full coverage of nothing — the same shape as the structural gate's
    `had_nothing_to_cover` trap.
    """
    assert len(CONSTRAINTS) >= 14, CONSTRAINTS


@pytest.mark.parametrize("constraint", CONSTRAINTS)
def test_every_constraint_is_load_bearing(constraint):
    """Delete one constraint; at least one declared negative must now pass.

    If none does, that constraint is untested — the schema could lose it in a
    refactor and this file would stay green. The failure message names the
    constraint so the fix is "write the missing negative", not "go hunting".
    """
    mutated = _drop_constraint(SCHEMA, constraint)
    survivors = [
        c["id"] for c in INVALID
        if _validates(c["doc"], mutated)
    ]
    assert survivors, (
        f"no negative case exercises {constraint!r}: removing it from the schema "
        f"changes nothing this file can detect. Add a document that violates "
        f"{constraint!r} and nothing else."
    )


@pytest.mark.parametrize("constraint", CONSTRAINTS)
def test_dropping_a_constraint_never_invalidates_a_valid_document(constraint):
    """The mutation harness must only ever loosen the schema.

    A mutation that made a VALID document fail would mean `_drop_constraint`
    corrupted the schema rather than relaxing it, and the test above would then
    be measuring the corruption instead of the constraint.
    """
    mutated = _drop_constraint(SCHEMA, constraint)
    for why, doc in VALID:
        assert _validates(doc, mutated), f"{constraint} mutation broke a valid doc: {why}"


def _validates(doc: dict, schema: dict) -> bool:
    try:
        jsonschema.validate(doc, schema)
        return True
    except jsonschema.ValidationError:
        return False
