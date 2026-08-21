"""Gate registry load invariants (T006).

The shape list below is DERIVED from the schema, not recalled (constitution
Principle II, FR-008a). The derivation procedure and what it found:

  Fields named in an `if` block:  tier, blocking, id
  Conditionally-required fields:  acceptance, promoted_at
  Nullable fields:                promoted_at

  For each, cover every value in its domain AND the absent case.

Deriving rather than recalling is what surfaced `test_blocking_with_null_promoted_at
_is_rejected` below — a probabilistic gate carrying `promoted_at: null` (which the
data model defines as "never promoted") satisfied `required` and was accepted as
blocking, because JSON Schema `required` checks presence and not non-nullness. That
is the identical bypass found in finding-envelope.schema.json, in the sibling
contract, found the same way. Nobody writes that case from memory; both times the
author tested the shape they had in mind and stopped.

Two invariants are NOT expressible in JSON Schema and are enforced by the loader:
dangling `failure_proof` (T009) and free-before-llm ordering (T010).
"""
from __future__ import annotations

import json
import pathlib

import pytest

from review_plan_v2.gates import registry

CONTRACT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "specs"
    / "003-gate-portfolio"
    / "contracts"
    / "gate-registry.schema.json"
)


def _det(**over):
    """A valid deterministic structural gate."""
    gate = {
        "id": "structural.raw-caught-to-logger",
        "tier": "deterministic",
        "blocking": "blocks",
        "order": 20,
        "cost": "free",
        "rule": "rules/raw-caught-to-logger.yml",
        "failure_proof": "tests/proofs/run-all.sh",
    }
    gate.update(over)
    return gate


def _prob(**over):
    """A valid probabilistic reviewer gate, advisory by default."""
    gate = {
        "id": "reviewer.correctness",
        "tier": "probabilistic",
        "blocking": "advisory",
        "order": 100,
        "cost": "llm",
        "failure_proof": "tests/proofs/run-all.sh",
    }
    gate.update(over)
    return gate


ACCEPTANCE = {"runs": 40, "accepted": 31, "measured_through": "2026-08-01"}


def _doc(*gates, version=1):
    return {"version": version, "gates": list(gates)}


# --- the schema file itself -------------------------------------------------


def test_contract_file_is_valid_json_schema():
    """A malformed contract must fail loudly, not validate everything vacuously."""
    from jsonschema import Draft202012Validator

    schema = json.loads(CONTRACT.read_text())
    Draft202012Validator.check_schema(schema)


# --- accepted shapes --------------------------------------------------------


def test_valid_deterministic_structural_gate_loads(tmp_path):
    registry.load_registry(_doc(_det()), repo_root=_root())


def test_valid_probabilistic_advisory_gate_loads():
    registry.load_registry(_doc(_prob()), repo_root=_root())


def test_probabilistic_blocking_with_acceptance_and_promotion_loads():
    registry.load_registry(
        _doc(_prob(blocking="blocks", acceptance=ACCEPTANCE, promoted_at="2026-08-01")),
        repo_root=_root(),
    )


# --- derived from `if` block 1: tier=probabilistic AND blocking=blocks -------


def test_probabilistic_blocking_without_acceptance_is_rejected():
    """FR-013/FR-014: promotion to blocking must cite measured acceptance."""
    with pytest.raises(registry.RegistryError, match="acceptance"):
        registry.load_registry(_doc(_prob(blocking="blocks")), repo_root=_root())


def test_probabilistic_blocking_without_promoted_at_is_rejected():
    with pytest.raises(registry.RegistryError, match="promoted_at"):
        registry.load_registry(
            _doc(_prob(blocking="blocks", acceptance=ACCEPTANCE)), repo_root=_root()
        )


def test_blocking_with_null_promoted_at_is_rejected():
    """The derived case: present-but-null is not promoted.

    `required` checks presence only. `promoted_at: null` means "never promoted"
    in data-model.md, so accepting it lets a probabilistic gate block having
    never been promoted — FR-014 defeated while every field is technically
    present. Found by deriving the shape list, not by recalling it.
    """
    with pytest.raises(registry.RegistryError, match="promoted_at"):
        registry.load_registry(
            _doc(_prob(blocking="blocks", acceptance=ACCEPTANCE, promoted_at=None)),
            repo_root=_root(),
        )


# --- derived from `if` block 2: tier=deterministic ---------------------------


def test_deterministic_gate_costing_llm_is_rejected():
    with pytest.raises(registry.RegistryError, match="cost"):
        registry.load_registry(_doc(_det(cost="llm")), repo_root=_root())


# --- derived from `if` block 3: id matches ^structural\. ---------------------


def test_structural_gate_without_rule_is_rejected():
    gate = _det()
    del gate["rule"]
    with pytest.raises(registry.RegistryError, match="rule"):
        registry.load_registry(_doc(gate), repo_root=_root())


def test_non_structural_gate_needs_no_rule():
    """The near-miss for block 3: same shape, id outside the pattern, must pass."""
    registry.load_registry(_doc(_prob()), repo_root=_root())


# --- derived from `required` at each level ----------------------------------


@pytest.mark.parametrize(
    "field", ["id", "tier", "blocking", "order", "cost", "failure_proof"]
)
def test_gate_missing_a_required_field_is_rejected(field):
    gate = _det()
    del gate[field]
    with pytest.raises(registry.RegistryError, match=field):
        registry.load_registry(_doc(gate), repo_root=_root())


@pytest.mark.parametrize("field", ["runs", "accepted", "measured_through"])
def test_acceptance_missing_a_required_field_is_rejected(field):
    acc = dict(ACCEPTANCE)
    del acc[field]
    with pytest.raises(registry.RegistryError, match=field):
        registry.load_registry(
            _doc(_prob(blocking="blocks", acceptance=acc, promoted_at="2026-08-01")),
            repo_root=_root(),
        )


# --- derived from `additionalProperties: false` at each level ----------------


def test_unknown_key_at_root_is_rejected():
    doc = _doc(_det())
    doc["extra"] = True
    with pytest.raises(registry.RegistryError):
        registry.load_registry(doc, repo_root=_root())


def test_unknown_key_on_a_gate_is_rejected():
    with pytest.raises(registry.RegistryError):
        registry.load_registry(_doc(_det(blockign="blocks")), repo_root=_root())


def test_unknown_key_on_acceptance_is_rejected():
    with pytest.raises(registry.RegistryError):
        registry.load_registry(
            _doc(
                _prob(
                    blocking="blocks",
                    acceptance={**ACCEPTANCE, "notes": "looked fine"},
                    promoted_at="2026-08-01",
                )
            ),
            repo_root=_root(),
        )


# --- derived from the root schema's own constraints -------------------------


def test_empty_gate_list_is_rejected():
    """`minItems: 1`. An empty portfolio must not load as a valid portfolio."""
    with pytest.raises(registry.RegistryError):
        registry.load_registry(_doc(), repo_root=_root())


def test_wrong_version_is_rejected():
    with pytest.raises(registry.RegistryError):
        registry.load_registry(_doc(_det(), version=2), repo_root=_root())


# --- loader-only invariants, not expressible in JSON Schema ------------------


def test_dangling_failure_proof_is_rejected():
    """FR-007. A proof path that resolves to nothing is not a proof."""
    with pytest.raises(registry.RegistryError, match="failure_proof"):
        registry.load_registry(
            _doc(_det(failure_proof="tests/proofs/does-not-exist.sh")),
            repo_root=_root(),
        )


def test_llm_gate_ordered_before_a_free_gate_is_rejected():
    """FR-012. A free gate must never run after an llm gate; otherwise a
    deterministic failure cannot short-circuit LLM spend."""
    with pytest.raises(registry.RegistryError, match="order"):
        registry.load_registry(
            _doc(_prob(order=10), _det(order=20)),
            repo_root=_root(),
        )


def test_free_gate_ordered_before_an_llm_gate_loads():
    """The near-miss for the ordering rule: same two gates, correct order."""
    registry.load_registry(_doc(_det(order=20), _prob(order=100)), repo_root=_root())


def test_duplicate_gate_ids_are_rejected():
    """Two gates with one id makes provenance ambiguous and silently drops one."""
    with pytest.raises(registry.RegistryError, match="duplicate"):
        registry.load_registry(_doc(_det(), _det(order=30)), repo_root=_root())


def _root():
    return pathlib.Path(__file__).resolve().parents[2]
