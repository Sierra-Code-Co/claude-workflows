"""The gate registry: tier, ordering, and blocking policy as declared data.

Today the set of checks is implicit in orchestrator.py's control flow, which is
why nothing stops the next gate being added at the wrong tier by habit. Loading
the portfolio from a declared file lets three rules be enforced mechanically at
startup instead of by review convention:

  FR-007  every gate carries a failure proof, and the reference must resolve
  FR-012  every free gate orders before every llm gate, so a deterministic
          failure can short-circuit LLM spend
  FR-014  a probabilistic gate may only block with measured acceptance

A registry that cannot be validated is not a registry: load failures raise, they
do not warn. A warn-only load would let a malformed portfolio run as if it were
a valid one, which is the degradation this module exists to prevent.

The JSON Schema ships INSIDE the package (`gates/schemas/`) rather than being
read from `specs/003-gate-portfolio/contracts/`. The spec directory is excluded
by .dockerignore, so a runtime read from there resolves on a dev laptop and
raises inside the image — a failure that only appears in the environment nobody
runs tests in. `tests/unit/test_schema_copies_match.py` asserts the two copies
are byte-identical so the duplication cannot drift.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

from ..paths import safe_join

SCHEMA_DIR = pathlib.Path(__file__).resolve().parent / "schemas"
GATE_REGISTRY_SCHEMA = SCHEMA_DIR / "gate-registry.schema.json"


class RegistryError(Exception):
    """The portfolio is invalid. Always fatal — never downgraded to a warning."""


@dataclass(frozen=True)
class Acceptance:
    """Measured evidence that a probabilistic gate earned the right to block."""

    runs: int
    accepted: int
    measured_through: str

    def __post_init__(self) -> None:
        # Draft 2020-12 can bound each field independently but cannot compare
        # two of them, so `accepted: 50` against `runs: 3` validated against the
        # schema and yielded an acceptance rate of 1667%. FR-014 promotes gates
        # on that number. An impossible state that validates is worse than one
        # that crashes, because it promotes.
        if self.runs < 1:
            raise RegistryError(f"acceptance.runs must be >= 1, got {self.runs}")
        if self.accepted < 0:
            raise RegistryError(f"acceptance.accepted must be >= 0, got {self.accepted}")
        if self.accepted > self.runs:
            raise RegistryError(
                f"acceptance.accepted ({self.accepted}) exceeds runs ({self.runs}); "
                f"a gate cannot be accepted more often than it ran"
            )

    @property
    def rate(self) -> float:
        return self.accepted / self.runs


@dataclass
class GateHealth:
    """Per-run output. Rendered on every run, success included (FR-018).

    `ran` exists so callers can tell "found nothing" from "never ran". Those two
    states produced identical output in three separate checks in this fleet, and
    each time the silent one was read as clean for months.
    """

    ran: bool
    skipped_reason: str | None = None
    calls_attempted: int = 0
    calls_succeeded: int = 0
    dead_legs: list[str] = field(default_factory=list)
    dropped_context: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.ran and self.skipped_reason is not None:
            raise RegistryError("a gate that ran cannot carry a skipped_reason")
        if not self.ran and not self.skipped_reason:
            raise RegistryError(
                "a gate that did not run MUST state why; an unexplained skip is "
                "indistinguishable from a pass"
            )

    @property
    def is_clean(self) -> bool:
        """A run is clean only if it actually ran and no provider leg was dead."""
        return self.ran and not self.dead_legs


@dataclass
class Gate:
    """One entry in the portfolio."""

    id: str
    tier: str
    blocking: str
    order: int
    cost: str
    failure_proof: str
    enabled_since: str | None = None
    promoted_at: str | None = None
    acceptance: Acceptance | None = None
    rule: str | None = None
    health: GateHealth | None = None

    @property
    def is_deterministic(self) -> bool:
        return self.tier == "deterministic"

    @property
    def blocks(self) -> bool:
        return self.blocking == "blocks"

    @property
    def is_reportable(self) -> bool:
        """data-model.md invariant 4.

        `health` is per-run output, so it is absent at load time and attached
        when the gate runs. The renderer MUST refuse to emit a result for a gate
        whose health is unset rather than rendering it as clean.
        """
        return self.health is not None


@dataclass
class Registry:
    version: int
    gates: list[Gate]

    def by_id(self, gate_id: str) -> Gate:
        for g in self.gates:
            if g.id == gate_id:
                return g
        raise RegistryError(f"no gate with id {gate_id!r}")

    @property
    def ordered(self) -> list[Gate]:
        return sorted(self.gates, key=lambda g: (g.order, g.id))


def _validate_against_schema(doc: Any) -> None:
    """Structural invariants. Raises RegistryError naming the offending field.

    The field name matters: a load failure that does not say which key is wrong
    sends the reader to the whole file.
    """
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - declared in pyproject
        raise RegistryError(
            "jsonschema is required to validate the gate registry; "
            "install with `pip install -e .`"
        ) from exc

    schema = json.loads(GATE_REGISTRY_SCHEMA.read_text())
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    if not errors:
        return

    parts = []
    for err in errors:
        where = "/".join(str(p) for p in err.absolute_path) or "<root>"
        parts.append(f"{where}: {err.message}")
    raise RegistryError("invalid gate registry:\n  " + "\n  ".join(parts))


def _check_paths_are_contained(gates: list[Gate], repo_root: pathlib.Path) -> None:
    """T005g. `failure_proof` and `rule` must name files INSIDE the repo.

    Both arrive as unconstrained strings, and `failure_proof` is not merely read
    — SC-004 EXECUTES it to prove each gate can fail. `pathlib` discards the
    root on an absolute right operand, so before this check a gate declaring
    `failure_proof: /tmp/anything.sh` passed the existence test by pointing at a
    file outside the tree entirely, and then ran it.

    `gates.yml` is repo-controlled, so this is hardening rather than a live
    exploit. It is here because FR-022/FR-023 already draw an untrusted-input
    boundary around the verification stage, and a registry whose entries are
    executed deserves the same treatment: impossible by construction, not
    "the file is trusted". The schema refuses the textual forms; this refuses
    what the schema cannot see — a repo-internal symlink pointing outward.
    """
    escaped: list[str] = []
    for g in gates:
        for field_name, raw in (("failure_proof", g.failure_proof), ("rule", g.rule)):
            if raw is None:
                continue
            if safe_join(repo_root, raw) is None:
                escaped.append(f"{g.id}.{field_name} -> {raw!r}")
    if escaped:
        raise RegistryError(
            "gate path escapes the repository root; failure_proof is executed, "
            f"so this is refused rather than resolved: {', '.join(escaped)}"
        )


def _check_failure_proofs(gates: list[Gate], repo_root: pathlib.Path) -> None:
    """FR-007. A proof path that resolves to nothing is not a proof.

    Enforced here rather than in the schema because JSON Schema can check that a
    string is present, not that it names a file that exists.
    """
    # `.is_file()`, NOT `.exists()`. `exists()` is True for a directory, and an
    # empty failure_proof makes `repo_root / ""` resolve to repo_root itself —
    # which exists — so a gate declaring `failure_proof: ""` satisfied FR-007
    # while naming no proof at all. The whole rule, defeated by the empty
    # string. Second time on this branch that a presence check was mistaken for
    # a substance check; the first was `required` read as a non-null guarantee.
    missing = [g for g in gates if not (repo_root / g.failure_proof).is_file()]
    if missing:
        listed = ", ".join(f"{g.id} -> {g.failure_proof!r}" for g in missing)
        raise RegistryError(
            f"failure_proof does not resolve to an existing file: {listed}"
        )


def _check_ordering(gates: list[Gate]) -> None:
    """FR-012. Every free gate must order strictly before every llm gate.

    Without this the short-circuit is unenforceable: a free gate scheduled after
    an llm gate means a deterministic failure cannot prevent the spend it was
    supposed to prevent.
    """
    free = [g for g in gates if g.cost == "free"]
    llm = [g for g in gates if g.cost == "llm"]
    if not free or not llm:
        return
    latest_free = max(g.order for g in free)
    earliest_llm = min(g.order for g in llm)
    if latest_free >= earliest_llm:
        offending_free = [g.id for g in free if g.order >= earliest_llm]
        offending_llm = [g.id for g in llm if g.order <= latest_free]
        raise RegistryError(
            "order violates the free-before-llm rule (FR-012): "
            f"free gate(s) {offending_free} are not ordered before "
            f"llm gate(s) {offending_llm}"
        )


def _check_unique_ids(raw_gates: list[dict]) -> None:
    seen: set[str] = set()
    dupes: set[str] = set()
    for g in raw_gates:
        gid = g.get("id")
        if gid in seen:
            dupes.add(gid)
        seen.add(gid)
    if dupes:
        raise RegistryError(f"duplicate gate id(s): {sorted(dupes)}")


def load_registry(doc: Any, repo_root: pathlib.Path | str) -> Registry:
    """Validate and materialise the portfolio. Raises RegistryError on any defect."""
    repo_root = pathlib.Path(repo_root)

    if not isinstance(doc, dict):
        raise RegistryError(f"gate registry must be a mapping, got {type(doc).__name__}")

    _validate_against_schema(doc)
    _check_unique_ids(doc["gates"])

    gates = [
        Gate(
            id=g["id"],
            tier=g["tier"],
            blocking=g["blocking"],
            order=g["order"],
            cost=g["cost"],
            failure_proof=g["failure_proof"],
            enabled_since=g.get("enabled_since"),
            promoted_at=g.get("promoted_at"),
            acceptance=Acceptance(**g["acceptance"]) if g.get("acceptance") else None,
            rule=g.get("rule"),
        )
        for g in doc["gates"]
    ]

    # Containment BEFORE existence: an escaping path that happens to exist must
    # be refused for escaping, not accepted for existing.
    _check_paths_are_contained(gates, repo_root)
    _check_failure_proofs(gates, repo_root)
    _check_ordering(gates)

    return Registry(version=doc["version"], gates=gates)


def load_registry_file(path: pathlib.Path | str, repo_root: pathlib.Path | str) -> Registry:
    """Load `gates.yml` from disk."""
    path = pathlib.Path(path)
    if not path.exists():
        raise RegistryError(f"gate registry not found at {path}")

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - declared in pyproject
        raise RegistryError(
            "PyYAML is required to read the gate registry; install with `pip install -e .`"
        ) from exc

    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise RegistryError(f"gate registry at {path} is not valid YAML: {exc}") from exc

    return load_registry(doc, repo_root=repo_root)
