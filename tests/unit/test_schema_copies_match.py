"""The packaged schemas and the spec contracts must not drift.

Two copies of one contract exist on purpose:

  specs/003-gate-portfolio/contracts/   authoritative; what review reads
  scripts/review_plan_v2/gates/schemas/ what the code loads at runtime

The duplication is not laziness. `.dockerignore` excludes `specs/`, so a runtime
read from the spec directory resolves on a dev laptop and raises inside the
image — a failure confined to the environment nobody runs tests in. The package
must therefore carry its own copy.

Duplication without a check is how the nine spec-kit skills forked invisibly
from upstream: one file was hashed and the other eight were not, so drift had
nothing to report it. This test is that check. It compares bytes, not parsed
JSON, because a reviewer reading the contract reads the bytes — a reformatted
copy that parses identically still shows a different file in the diff.
"""
from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "specs" / "003-gate-portfolio" / "contracts"
PACKAGED = REPO / "scripts" / "review_plan_v2" / "gates" / "schemas"

SCHEMAS = ["gate-registry.schema.json", "finding-envelope.schema.json"]


@pytest.mark.parametrize("name", SCHEMAS)
def test_packaged_schema_is_byte_identical_to_contract(name):
    contract = CONTRACTS / name
    packaged = PACKAGED / name

    assert contract.exists(), f"authoritative contract missing: {contract}"
    assert packaged.exists(), f"packaged copy missing: {packaged}"

    assert packaged.read_bytes() == contract.read_bytes(), (
        f"{name} has drifted between the spec contract and the packaged copy.\n"
        f"  contract: {contract}\n"
        f"  packaged: {packaged}\n"
        f"Copy the contract over the packaged file; do not edit the packaged "
        f"copy directly (Principle VI: the vendored artifact is never the one "
        f"you hand-edit)."
    )


def test_every_packaged_schema_has_a_contract():
    """A packaged schema with no authoritative source is an orphan.

    Without this, adding a schema to the package and forgetting the contract
    passes the test above vacuously — it only iterates the names it was told
    about. Derived from the parametrise list's own blind spot (FR-008a).
    """
    packaged_names = {p.name for p in PACKAGED.glob("*.json")}
    contract_names = {p.name for p in CONTRACTS.glob("*.json")}
    orphans = packaged_names - contract_names
    assert not orphans, (
        f"packaged schema(s) with no contract in {CONTRACTS}: {sorted(orphans)}"
    )


def test_parametrise_list_covers_every_packaged_schema():
    """And the list above must not fall behind the directory.

    The same blind spot one level up: a new schema pair added to both
    directories still escapes comparison until it is named in SCHEMAS.
    """
    packaged_names = {p.name for p in PACKAGED.glob("*.json")}
    uncovered = packaged_names - set(SCHEMAS)
    assert not uncovered, (
        f"packaged schema(s) not covered by the SCHEMAS list: {sorted(uncovered)}"
    )
