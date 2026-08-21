"""Map a finding back to the gate that produced it (T041, T042).

Both of Phase 6's rules need this and neither can be written without it:

  FR-012  a DETERMINISTIC failure short-circuits before any LLM spend
  FR-013  only DETERMINISTIC gates may hard-block

Both quantify over "findings from gate X", and until now nothing could answer
that question — `Finding.sources` carries an analyzer or reviewer name, the
registry carries gate ids, and the two are related by convention rather than by
code.

THE RULE THIS MODULE MUST NEVER BREAK: an unattributable finding is treated as
BLOCKING. Every other choice in this file bends toward showing and blocking,
because the failure modes are not symmetric — mis-classifying a deterministic
finding as advisory silently stops it failing the build, and nothing downstream
would ever say so. Mis-classifying the other way is loud and gets fixed. This is
the same asymmetry `partition()` follows in rounds.py: malformed input must fail
toward the safe side, never toward silence.
"""
from __future__ import annotations

from ..types import Finding
from .registry import Gate, Registry

#: The structural enumerator reports itself as `ast-grep` (the binary) while the
#: registry declares `structural.<rule-id>`. Bridged explicitly rather than by
#: prefix-guessing, so a future analyzer named `ast-grep-something` cannot be
#: swept into the structural family by accident.
_STRUCTURAL_SOURCE = "ast-grep"

#: A cascade leg is the SAME reviewer escalated to a second model on a
#: high-risk path — `orchestrator.py` names them `<reviewer>-cascade-openai` and
#: `<reviewer>-cascade-google`. They belong to their base reviewer's gate.
#:
#: Found by running this tool on its own Phase 6 diff: 19 actionable findings,
#: 18 advisory, exit 1. The nineteenth came from a cascade leg alone, which
#: matched no gate id, fell to the unattributable-blocks default, and FAILED
#: THE RUN — a probabilistic gate blocking, which is the exact thing FR-013
#: forbids and this phase was written to prevent. The fail-safe default was
#: right; the mapping was incomplete.
_CASCADE_MARKER = "-cascade-"


def gate_for(finding: Finding, registry: Registry) -> Gate | None:
    """→ the declared Gate that produced `finding`, or None if unattributable.

    Three naming conventions have to be reconciled, and they are tried in order
    of specificity so a source can never match two families:

      analyzers   `sources=["ruff"]`        → gate id `ruff`
      reviewers   `sources=["correctness"]` → gate id `reviewer.correctness`
      structural  `sources=["ast-grep"]`    → the structural.* gate for its rule
    """
    for source in finding.sources or []:
        # A cascade leg is its base reviewer, so `correctness-cascade-openai`
        # resolves to `reviewer.correctness`. Split on the FIRST marker: a
        # reviewer named `x-cascade-y` would otherwise lose part of its name.
        base = source.split(_CASCADE_MARKER, 1)[0] if _CASCADE_MARKER in source else source
        for candidate in (source, f"reviewer.{source}", base, f"reviewer.{base}"):
            for gate in registry.gates:
                if gate.id == candidate:
                    return gate

        if source == _STRUCTURAL_SOURCE:
            # A structural finding's message is `[<rule-id>] ...` (see
            # StructuralAnalyzer.parse_output), which is what distinguishes one
            # structural gate from another when several rules are registered.
            rule_id = ""
            if finding.message.startswith("["):
                rule_id = finding.message[1:].partition("]")[0]
            for gate in registry.gates:
                if gate.id == f"structural.{rule_id}":
                    return gate
            # Exactly one structural gate declared: no ambiguity to resolve, so
            # attribute it rather than dropping to unattributable and blocking
            # on a technicality.
            structural = [g for g in registry.gates if g.id.startswith("structural.")]
            if len(structural) == 1:
                return structural[0]
    return None


def blocks(finding: Finding, registry: Registry | None) -> bool:
    """True if `finding` may set a failing exit code.

    With no registry (a repo that has not adopted a portfolio) EVERYTHING
    blocks — that is the pre-portfolio behaviour, and quietly relaxing it for
    downstream repos would turn adopting this tool into a downgrade.
    """
    if registry is None:
        return True
    gate = gate_for(finding, registry)
    if gate is None:
        # Unattributable. See the module docstring: this direction is loud, the
        # other is silent.
        return True
    return gate.blocks


def split(findings: list[Finding], registry: Registry | None,
          ) -> tuple[list[Finding], list[Finding]]:
    """→ (blocking, advisory). Order preserved within each half."""
    blocking_findings, advisory = [], []
    for f in findings:
        (blocking_findings if blocks(f, registry) else advisory).append(f)
    return blocking_findings, advisory


def deterministic_failure(findings: list[Finding], registry: Registry | None,
                          ) -> Gate | None:
    """→ the first blocking DETERMINISTIC gate with an actionable finding.

    This is FR-012's trigger: its presence means the run may stop before any
    provider is called. Returns the Gate rather than a bool so the operator can
    be told which gate stopped the run — "short-circuited" without a name is
    the kind of message that sends people to read source.
    """
    if registry is None:
        return None
    for f in findings:
        if f.severity != "actionable":
            continue
        gate = gate_for(f, registry)
        if gate is not None and gate.is_deterministic and gate.blocks:
            return gate
    return None
